from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.database import Base
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from evals.agent_lab.evaluator import (
    ensure_dataset_size,
    grade_run,
    snapshot_core_data,
)


@pytest.fixture
def eval_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(eval_db: Session) -> tuple[Case, JurisdictionAsset]:
    case = Case(
        case_number="EVAL-001",
        occurred_time=datetime(2026, 9, 1, 1, 30),
        location="脱敏区域A",
        latitude=45.2,
        longitude=124.2,
        case_type="测试类别",
        status="closed",
    )
    asset = JurisdictionAsset(
        name="脱敏井点A",
        external_id="EVAL-WELL-001",
        asset_type="well",
        geometry_type="point",
        latitude=45.21,
        longitude=124.21,
        geometry={"type": "Point", "coordinates": [124.21, 45.21]},
        source="eval_snapshot",
        status="active",
        verified=True,
    )
    eval_db.add_all([case, asset])
    eval_db.commit()
    return case, asset


def test_eval_dataset_gate_reports_shortfall(eval_db: Session):
    _seed(eval_db)

    with pytest.raises(ValueError, match="至少需要 30 个案件和 100 个地图资源"):
        ensure_dataset_size(eval_db, minimum_cases=30, minimum_assets=100)


@pytest.mark.asyncio
async def test_eval_grades_trace_evidence_boundaries_and_core_read_only(eval_db: Session):
    case, asset = _seed(eval_db)
    before = snapshot_core_data(eval_db)
    run = AgentRunService.create_run(
        eval_db,
        task_type="evidence_report",
        query="评测双域研判证据链",
        case_ids=[case.id],
        asset_ids=[asset.id],
        mode="shadow",
        created_by=None,
    )

    completed = await AgentRunExecutor(narrator=None).execute(eval_db, run.id)
    checks = grade_run(completed)

    failed = [check for check in checks if not check.passed]
    assert not failed, (completed.error_message, failed)
    assert snapshot_core_data(eval_db) == before
