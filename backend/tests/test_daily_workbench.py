"""v5.0 日常只读汇总：全库、当前画像、分页与权限均独立验证。"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api import workbench
from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState
from app.models.map_foundation import OperationalArea
from app.services.daily_workbench_service import DailyWorkbenchService, information_gaps
from tests.test_workbench import _case, _client, _session


def _profile(db, case, *, state_status="completed", profile_hash="same", current=True):
    db.add(CasePipelineState(
        case_id=case.id, status=state_status, source_hash="same",
        schema_version="4.1.0", dictionary_version="fixture-1",
    ))
    db.add(CaseAnalysisProfile(
        id=str(uuid4()), case_id=case.id, profile_version=1,
        source_hash=profile_hash, schema_version="4.1.0", dictionary_version="fixture-1",
        payload={}, quality_score=80, analysis_readiness="ready", is_current=current,
    ))
    db.commit()


def test_daily_is_read_only_and_full_authorized_summary_not_latest_500():
    db = _session()
    for index in range(600):
        db.add(Case(
            case_number=f"DAILY-{index:04}", occurred_time=datetime(2020, 1, 1),
            location="测试厂区", description="案件正式描述", status="processing",
            created_at=datetime(2020, 1, 1) + timedelta(seconds=index),
        ))
    db.commit()
    oldest = db.query(Case).order_by(Case.id).first()
    oldest.description = ""
    db.commit()
    _profile(db, oldest)
    client = _client(db)
    statements = []

    def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", record_sql)
    try:
        response = client.get("/api/workbench/daily?limit=7&offset=593")
    finally:
        event.remove(db.bind, "before_cursor_execute", record_sql)

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "daily-workbench-5.0-1"
    assert payload["summary"] == {
        "total_cases": 600, "needs_information": 1,
        "analysis_pending": 599, "analysis_ready": 1,
    }
    assert payload["pagination"] == {"limit": 7, "offset": 593, "returned": 7, "total": 600}
    assert [row["case_number"] for row in payload["cases"]] == [
        f"DAILY-{index:04}" for index in range(6, -1, -1)
    ]
    assert payload["cases"][-1]["information_gaps"] == ["案情描述"]
    assert payload["cases"][-1]["profile_ready"] is True
    assert payload["cases"][-1]["case_status"] == "processing"
    assert len(statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert not db.new and not db.dirty and not db.deleted
    # The retained legacy entry also must not hide old missing-information rows.
    legacy = client.get("/api/workbench/today").json()
    assert legacy["summary"]["total_cases"] == 600
    assert [row["source_id"] for row in legacy["tasks"]] == [oldest.id]


def test_daily_requires_matching_current_profile_and_completed_pipeline():
    db = _session()
    ready = _case(db, "DAILY-READY")
    stale = _case(db, "DAILY-STALE")
    historical = _case(db, "DAILY-HISTORY")
    pending = _case(db, "DAILY-PENDING")
    missing = _case(db, "DAILY-MISSING")
    wrong_schema = _case(db, "DAILY-SCHEMA")
    _profile(db, ready)
    _profile(db, stale, profile_hash="old")
    _profile(db, historical, current=False)
    _profile(db, pending, state_status="processing")
    _profile(db, wrong_schema)
    db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == wrong_schema.id).update(
        {CaseAnalysisProfile.schema_version: "old-schema"}
    )
    db.commit()
    payload = _client(db).get("/api/workbench/daily").json()
    assert payload["summary"] == {
        "total_cases": 6, "needs_information": 0, "analysis_pending": 5, "analysis_ready": 1,
    }
    rows = {row["id"]: row for row in payload["cases"]}
    assert rows[ready.id]["profile_ready"] is True
    assert all(not rows[item.id]["profile_ready"] for item in (
        stale, historical, pending, missing, wrong_schema,
    ))
    assert rows[missing.id]["pipeline_status"] == "not_started"
    assert rows[pending.id]["pipeline_status"] == "processing"


def test_daily_information_gaps_use_official_fields_not_old_quality_score():
    db = _session()
    location_only = _case(db, "DAILY-LOCATION", latitude=None, longitude=None, quality_score=0)
    location_only.quality_issues = {"missing_required": ["oil_volume"]}
    coordinates_only = _case(db, "DAILY-COORDINATES")
    coordinates_only.location = "\t \n\u3000"
    invalid = _case(db, "DAILY-INVALID", latitude=100)
    invalid.location = "\t \n\u3000"
    invalid.description = "\t\r\n\u3000"
    db.commit()
    payload = _client(db).get("/api/workbench/daily").json()
    rows = {row["id"]: row for row in payload["cases"]}
    assert rows[location_only.id]["information_gaps"] == []
    assert rows[coordinates_only.id]["information_gaps"] == []
    assert rows[invalid.id]["information_gaps"] == ["案发地点或合法坐标", "案情描述"]
    assert payload["summary"]["needs_information"] == 1
    assert payload["summary"]["analysis_pending"] == 3
    assert information_gaps(Case()) == ["案发时间", "案发地点或合法坐标", "案情描述"]


def test_daily_summary_pagination_and_profiles_follow_current_area_scope():
    db = _session()
    db.add_all(OperationalArea(id=i, code=f"DAILY-{i}", name=f"测试范围{i}") for i in (1, 2))
    db.commit()
    allowed = _case(db, "DAILY-ALLOWED")
    denied = _case(db, "DAILY-DENIED", description="")
    allowed.operational_area_id = 1
    denied.operational_area_id = 2
    db.commit()
    _profile(db, allowed)
    _profile(db, denied)
    client = _client(db)
    db.info["authorized_area_ids"] = (1,)
    payload = client.get("/api/workbench/daily").json()
    assert payload["summary"] == {
        "total_cases": 1, "needs_information": 0, "analysis_pending": 0, "analysis_ready": 1,
    }
    assert [row["id"] for row in payload["cases"]] == [allowed.id]
    db.info["authorized_area_ids"] = ()
    empty = client.get("/api/workbench/daily").json()
    assert empty["cases"] == []
    assert empty["summary"] == {
        "total_cases": 0, "needs_information": 0, "analysis_pending": 0, "analysis_ready": 0,
    }
    assert empty["pagination"]["total"] == 0


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_daily_rejects_invalid_pagination(query):
    assert _client(_session()).get(f"/api/workbench/daily?{query}").status_code == 422


def test_daily_requires_authentication_and_allows_read_only_accounts(monkeypatch):
    db = _session()
    _case(db, "DAILY-AUTH")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    assert _client(db, role="viewer").get("/api/workbench/daily").status_code == 200
    api = FastAPI()
    api.include_router(workbench.router, prefix="/api/workbench")

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    assert TestClient(api).get("/api/workbench/daily").status_code == 401


def test_daily_stable_id_order_for_same_creation_time_and_empty_last_page():
    db = _session()
    records = [_case(db, f"DAILY-ORDER-{index}") for index in range(3)]
    for record in records:
        record.created_at = datetime(2026, 1, 1)
    db.commit()
    client = _client(db)
    payload = client.get("/api/workbench/daily?limit=2").json()
    assert [row["id"] for row in payload["cases"]] == [records[2].id, records[1].id]
    assert payload["pagination"]["total"] == 3
    last = client.get("/api/workbench/daily?offset=3").json()
    assert last["cases"] == []
    assert last["pagination"] == {"limit": 20, "offset": 3, "returned": 0, "total": 3}


def test_daily_never_flushes_pending_changes_even_in_autoflush_session(monkeypatch):
    db = _session()
    _case(db, "DAILY-PERSISTED")
    db.autoflush = True
    pending = Case(case_number="DAILY-UNSAVED", occurred_time=datetime(2026, 1, 1))
    db.add(pending)

    def fail_flush(*_args, **_kwargs):
        raise AssertionError("daily must not flush")

    monkeypatch.setattr(db, "flush", fail_flush)
    payload = DailyWorkbenchService.daily(db)
    assert payload["summary"]["total_cases"] == 1
    assert pending in db.new
    assert pending.id is None
