from datetime import datetime

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, MetaData, String, Table, create_engine, func, select

from scripts.migrate_sqlite_to_postgres import (
    MigrationError,
    _decrypt_source_secret,
    _encrypt_target_secret,
    _ordered_target_tables,
    _remove_schema_seed_rows,
    prepare_row,
    transform_sensitive_row,
)
from app.database import Base


def test_ai_model_key_is_reencrypted_for_target_secret():
    source_secret = "source-secret-key-for-migration-tests"
    target_secret = "target-secret-key-for-migration-tests"
    encrypted = _encrypt_target_secret("sk-sensitive-value", source_secret)

    row = transform_sensitive_row(
        "ai_models",
        {"id": 1, "api_key": encrypted},
        source_secret=source_secret,
        target_secret=target_secret,
    )

    assert row["api_key"] != encrypted
    assert "sk-sensitive-value" not in row["api_key"]
    assert _decrypt_source_secret(row["api_key"], target_secret) == "sk-sensitive-value"
    with pytest.raises(MigrationError):
        _decrypt_source_secret(row["api_key"], source_secret)


def test_plaintext_system_secret_is_encrypted_during_migration():
    row = transform_sensitive_row(
        "system_configs",
        {
            "config_key": "meeting_api_key",
            "config_type": "api_key",
            "config_value": "plain-legacy-secret",
            "is_encrypted": "false",
        },
        source_secret=None,
        target_secret="target-secret-key-for-migration-tests",
    )

    assert row["is_encrypted"] == "true"
    assert "plain-legacy-secret" not in row["config_value"]
    assert _decrypt_source_secret(
        row["config_value"],
        "target-secret-key-for-migration-tests",
    ) == "plain-legacy-secret"


def test_prepare_row_converts_sqlite_values_to_target_types():
    metadata = MetaData()
    table = Table(
        "sample",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("enabled", Boolean),
        Column("created_at", DateTime),
        Column("payload", JSON),
        Column("name", String),
    )

    row = prepare_row(
        table,
        {
            "id": 1,
            "enabled": 1,
            "created_at": "2026-08-14T08:30:00",
            "payload": '{"risk": "high"}',
            "name": "测试",
            "removed_column": "ignored",
        },
        source_secret=None,
        target_secret="target-secret-key-for-migration-tests",
    )

    assert row == {
        "id": 1,
        "enabled": True,
        "created_at": datetime(2026, 8, 14, 8, 30),
        "payload": {"risk": "high"},
        "name": "测试",
    }


def test_encrypted_source_requires_matching_source_key():
    encrypted = _encrypt_target_secret("secret", "correct-source-key")

    with pytest.raises(MigrationError, match="无法使用"):
        transform_sensitive_row(
            "ai_models",
            {"api_key": encrypted},
            source_secret="wrong-source-key",
            target_secret="target-secret-key-for-migration-tests",
        )


def test_migration_order_breaks_meeting_report_cycle_safely():
    ordered = _ordered_target_tables(
        {"ai_models", "meetings", "reports", "meeting_conversations"}
    )
    names = [table.name for table in ordered]

    assert names.index("ai_models") < names.index("meetings")
    assert names.index("meetings") < names.index("reports")
    assert names.index("meetings") < names.index("meeting_conversations")


def test_schema_seeded_chain_configs_can_be_replaced():
    engine = create_engine("sqlite://")
    table = Base.metadata.tables["system_configs"]
    table.create(bind=engine)
    rows = [
        {
            "config_key": key,
            "config_value": "1",
            "config_type": "number",
            "category": "chain_analysis",
        }
        for key in (
            "chain_radius_km",
            "chain_time_window_days",
            "chain_min_confidence",
        )
    ]

    with engine.begin() as connection:
        connection.execute(table.insert(), rows)
        removed = _remove_schema_seed_rows(connection, table)
        remaining = connection.execute(select(func.count()).select_from(table)).scalar_one()

    assert removed == 3
    assert remaining == 0
