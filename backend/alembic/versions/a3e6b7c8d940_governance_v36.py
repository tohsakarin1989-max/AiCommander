"""governance and evaluation v3.6

Revision ID: a3e6b7c8d940
Revises: f2d5a6b7c839
Create Date: 2026-09-08
"""

import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3e6b7c8d940"
down_revision: Union[str, None] = "f2d5a6b7c839"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _checksum(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("situation_briefs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "algorithm_version",
                sa.String(length=80),
                nullable=False,
                server_default="deployment-advisor-3.5.0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "scope_policy_version",
                sa.String(length=80),
                nullable=False,
                server_default="area-scope-3.6.0",
            )
        )

    op.create_table(
        "algorithm_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("component", "version", name="uq_algorithm_component_version"),
    )
    op.create_table(
        "scope_policy_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("case_ids", sa.JSON(), nullable=False),
        sa.Column("ground_truth", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_evaluation_dataset_version"),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("algorithm_manifest", sa.JSON(), nullable=False),
        sa.Column("scope_policy_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("trace_manifest", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_datasets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_runs_dataset_status", "evaluation_runs", ["dataset_id", "status"])

    algorithm_rows = [
        ("case-profile", "case-profile-3.3.0", {"mode": "deterministic", "max_gaps": 3}),
        ("dual-domain", "dual-domain-3.4.0", {"mode": "deterministic", "max_candidates": 3}),
        ("deployment-advisor", "deployment-advisor-3.5.0", {"mode": "deterministic", "max_advice": 3}),
    ]
    algorithm_table = sa.table(
        "algorithm_versions",
        sa.column("component", sa.String),
        sa.column("version", sa.String),
        sa.column("configuration", sa.JSON),
        sa.column("checksum", sa.String),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        algorithm_table,
        [
            {
                "component": component,
                "version": version,
                "configuration": configuration,
                "checksum": _checksum(configuration),
                "status": "active",
            }
            for component, version, configuration in algorithm_rows
        ],
    )
    policy = {
        "dimensions": ["operational_area", "role", "access_level"],
        "default": "deny",
        "raw_case_external_model": False,
        "precise_production_coordinate_external_model": False,
        "agent_formal_fact_write": False,
        "agent_execution_task_create": False,
    }
    policy_table = sa.table(
        "scope_policy_versions",
        sa.column("version", sa.String),
        sa.column("policy", sa.JSON),
        sa.column("checksum", sa.String),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        policy_table,
        [
            {
                "version": "area-scope-3.6.0",
                "policy": policy,
                "checksum": _checksum(policy),
                "status": "active",
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_dataset_status", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_datasets")
    op.drop_table("scope_policy_versions")
    op.drop_table("algorithm_versions")
    with op.batch_alter_table("situation_briefs") as batch_op:
        batch_op.drop_column("scope_policy_version")
        batch_op.drop_column("algorithm_version")
