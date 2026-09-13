from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import workbench
from app.config import settings
from app.database import Base, get_db
from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.models.user import User
from app.models.workbench import WorkbenchTaskSession


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _ensure_user(db: Session, *, role: str, user_id: int) -> None:
    if db.get(User, user_id) is not None:
        return
    db.add(
        User(
            id=user_id,
            username=f"{role}-{user_id}",
            display_name=f"{role}-{user_id}",
            password_hash="test-only",
            role=role,
        )
    )
    db.commit()


def _client(db: Session, *, role: str = "analyst", user_id: int = 9) -> TestClient:
    _ensure_user(db, role=role, user_id=user_id)
    api = FastAPI()

    @api.middleware("http")
    async def principal(request: Request, call_next):
        request.state.principal = SimpleNamespace(
            user_id=user_id,
            id=user_id,
            role=role,
            username=f"{role}-{user_id}",
            display_name=f"{role}-{user_id}",
        )
        return await call_next(request)

    api.include_router(workbench.router, prefix="/api/workbench")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def _case(
    db: Session,
    number: str,
    *,
    latitude: float | None = 46.61,
    longitude: float | None = 125.12,
    quality_score: float | None = 88,
    description: str = "现场已完成结构化录入。",
) -> Case:
    record = Case(
        case_number=number,
        occurred_time=datetime(2026, 9, 8, 2, 20),
        location="北区井场",
        latitude=latitude,
        longitude=longitude,
        case_type="涉油盗窃",
        description=description,
        status="processing",
        quality_score=quality_score,
        quality_issues={"missing_required": []},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _asset(db: Session, case: Case, asset_type: str, status: str) -> KnowledgeAsset:
    asset = KnowledgeAsset(
        asset_type=asset_type,
        source_case_id=case.id,
        version=1,
        title=f"{asset_type}-{case.case_number}",
        content={"facts": []},
        evidence_refs=[f"case:{case.id}"],
        source_signature=f"sig-{asset_type}-{case.id}",
        source_data_version=f"data-{case.id}",
        status=status,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def test_today_workbench_routes_cases_to_one_clear_next_action():
    db = _session()
    quality_case = _case(db, "WB-QUALITY", description="")
    experience_case = _case(db, "WB-EXPERIENCE")
    report_case = _case(db, "WB-REPORT")
    done_case = _case(db, "WB-DONE")

    _asset(db, report_case, "experience_card", "confirmed")
    _asset(db, done_case, "experience_card", "confirmed")
    _asset(db, done_case, "case_report", "confirmed")

    payload = _client(db).get("/api/workbench/today").json()
    tasks_by_case = {item["source_id"]: item for item in payload["tasks"]}

    assert tasks_by_case[quality_case.id]["stage"] == "data_review"
    assert tasks_by_case[quality_case.id]["target_path"] == f"/cases?caseId={quality_case.id}"
    assert experience_case.id not in tasks_by_case
    assert report_case.id not in tasks_by_case
    assert done_case.id not in tasks_by_case
    assert payload["summary"] == {
        "total_cases": 4,
        "actionable_cases": 1,
        "data_review": 1,
        "experience_review": 0,
        "report_review": 0,
        "completed": 3,
        "pending_approvals": 0,
    }
    assert all(item["why"] and item["next_action"] for item in payload["tasks"])
    assert payload["boundary"].startswith("工作台只负责分流")


def test_draft_assets_route_to_human_review_instead_of_regeneration():
    db = _session()
    experience = _case(db, "WB-EXP-DRAFT")
    report = _case(db, "WB-REPORT-DRAFT")
    _asset(db, experience, "experience_card", "draft")
    # A requested report draft can be reviewed without first creating experience.
    _asset(db, report, "case_report", "draft")

    tasks = _client(db).get("/api/workbench/today").json()["tasks"]
    stages = {item["source_id"]: item["stage"] for item in tasks}

    assert stages[experience.id] == "experience_review"
    assert stages[report.id] == "report_review"


def test_optional_generation_is_not_a_new_required_task_but_old_sessions_remain_readable():
    db = _session()
    case = _case(db, "WB-OPTIONAL")
    client = _client(db)
    old_session = WorkbenchTaskSession(
        user_id=9, task_type="experience_generate", source_type="case", source_id=case.id,
        status="active", active_slot=1, entry_path="/case-intelligence",
        last_path="/case-intelligence", page_transitions=0,
        started_at=datetime.utcnow(), last_activity_at=datetime.utcnow(),
    )
    db.add(old_session)
    db.commit()
    assert client.get("/api/workbench/today").json()["tasks"] == []
    assert client.get("/api/workbench/sessions/active").json()["id"] == old_session.id
    stale = client.post("/api/workbench/sessions", json={
        "task_type": "report_generate", "source_type": "case", "source_id": case.id,
        "entry_path": "/case-intelligence",
    })
    assert stale.status_code == 409
    completed = client.post(f"/api/workbench/sessions/{old_session.id}/events", json={
        "event": "completed",
    })
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert db.get(Case, case.id).status == "processing"


def test_archived_assets_do_not_require_new_generation():
    db = _session()
    experience = _case(db, "WB-EXP-ARCHIVED")
    report = _case(db, "WB-REPORT-ARCHIVED")
    _asset(db, experience, "experience_card", "archived")
    _asset(db, report, "experience_card", "confirmed")
    _asset(db, report, "case_report", "archived")

    tasks = _client(db).get("/api/workbench/today").json()["tasks"]
    stages = {item["source_id"]: item["stage"] for item in tasks}

    assert experience.id not in stages
    assert report.id not in stages


def test_session_start_resumes_same_task_and_abandons_previous_active_task():
    db = _session()
    client = _client(db, user_id=12)
    first_case = _case(db, "WB-SESSION-101", description="")
    second_case = _case(db, "WB-SESSION-102")
    _asset(db, second_case, "experience_card", "draft")

    first = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "data_review",
            "source_type": "case",
            "source_id": first_case.id,
            "entry_path": f"/cases?caseId={first_case.id}",
        },
    )
    resumed = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "data_review",
            "source_type": "case",
            "source_id": first_case.id,
            "entry_path": f"/cases?caseId={first_case.id}&tab=quality",
        },
    )
    second = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "experience_review",
            "source_type": "case",
            "source_id": second_case.id,
            "entry_path": f"/case-intelligence?caseId={second_case.id}",
        },
    )

    assert first.status_code == 201
    assert resumed.status_code == 200
    assert first.json()["session"]["id"] == resumed.json()["session"]["id"]
    assert resumed.json()["created"] is False
    assert second.status_code == 201
    previous = db.get(WorkbenchTaskSession, first.json()["session"]["id"])
    current = db.get(WorkbenchTaskSession, second.json()["session"]["id"])
    assert previous.status == "abandoned"
    assert previous.active_slot is None
    assert current.active_slot == 1
    assert second.json()["session"]["entry_path"] == "/case-intelligence"


def test_session_progress_counts_page_transitions_and_completion_is_idempotent():
    db = _session()
    client = _client(db, user_id=18)
    case = _case(db, "WB-SESSION-PROGRESS")
    _asset(db, case, "experience_card", "draft")
    created = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "experience_review",
            "source_type": "case",
            "source_id": case.id,
            "entry_path": f"/case-intelligence?caseId={case.id}",
        },
    ).json()["session"]

    same_page = client.post(
        f"/api/workbench/sessions/{created['id']}/events",
        json={"event": "page_view", "path": f"/case-intelligence?caseId={case.id}"},
    )
    next_page = client.post(
        f"/api/workbench/sessions/{created['id']}/events",
        json={"event": "page_view", "path": f"/reports?caseId={case.id}"},
    )
    completed = client.post(
        f"/api/workbench/sessions/{created['id']}/events",
        json={"event": "completed"},
    )
    repeated = client.post(
        f"/api/workbench/sessions/{created['id']}/events",
        json={"event": "completed"},
    )

    assert same_page.json()["page_transitions"] == 0
    assert next_page.json()["page_transitions"] == 1
    assert completed.json()["status"] == "completed"
    assert repeated.json()["completed_at"] == completed.json()["completed_at"]
    assert db.get(WorkbenchTaskSession, created["id"]).active_slot is None
    assert client.get("/api/workbench/sessions/active").json() is None


def test_session_rejects_external_or_sensitive_paths():
    db = _session()
    client = _client(db)

    external = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "data_review",
            "source_type": "case",
            "source_id": 1,
            "entry_path": "https://evil.example/cases/1",
        },
    )
    nested = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "data_review",
            "source_type": "case",
            "source_id": 1,
            "entry_path": "//evil.example/cases/1",
        },
    )

    assert external.status_code == 422
    assert nested.status_code == 422
    assert db.query(WorkbenchTaskSession).count() == 0


def test_session_rejects_nonexistent_or_stale_workbench_tasks():
    db = _session()
    case = _case(db, "WB-SESSION-STALE")
    client = _client(db)

    missing = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "experience_generate",
            "source_type": "case",
            "source_id": 999,
            "entry_path": "/case-intelligence",
        },
    )
    stale = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "report_review",
            "source_type": "case",
            "source_id": case.id,
            "entry_path": "/case-intelligence",
        },
    )

    assert missing.status_code == 404
    assert stale.status_code == 409
    assert db.query(WorkbenchTaskSession).count() == 0


def test_viewer_can_read_workbench_but_cannot_track_sessions_or_metrics(monkeypatch):
    db = _session()
    _case(db, "WB-VIEW")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    client = _client(db, role="viewer", user_id=21)

    assert client.get("/api/workbench/today").status_code == 200
    denied = client.post(
        "/api/workbench/sessions",
        json={
            "task_type": "experience_generate",
            "source_type": "case",
            "source_id": 1,
            "entry_path": "/case-intelligence",
        },
    )
    metrics = client.get("/api/workbench/metrics")

    assert denied.status_code == 403
    assert metrics.status_code == 403


def test_metrics_are_role_scoped_and_mark_small_samples_as_unverified():
    db = _session()
    now = datetime.utcnow()
    _ensure_user(db, role="analyst", user_id=31)
    _ensure_user(db, role="analyst", user_id=32)
    db.add_all(
        [
            WorkbenchTaskSession(
                user_id=31,
                task_type="data_review",
                source_type="case",
                source_id=1,
                status="completed",
                entry_path="/cases",
                last_path="/cases",
                page_transitions=2,
                started_at=now - timedelta(minutes=10),
                last_activity_at=now,
                completed_at=now,
            ),
            WorkbenchTaskSession(
                user_id=32,
                task_type="report_review",
                source_type="case",
                source_id=2,
                status="abandoned",
                entry_path="/case-intelligence",
                last_path="/case-intelligence",
                page_transitions=1,
                started_at=now - timedelta(minutes=5),
                last_activity_at=now,
                completed_at=now,
            ),
        ]
    )
    db.commit()

    analyst = _client(db, role="analyst", user_id=31).get("/api/workbench/metrics?days=30").json()
    admin = _client(db, role="admin", user_id=99).get("/api/workbench/metrics?days=30").json()

    assert analyst["scope"] == "self"
    assert analyst["totals"]["started"] == 1
    assert analyst["totals"]["completed"] == 1
    assert analyst["totals"]["avg_duration_seconds"] == 600
    assert admin["scope"] == "team"
    assert admin["totals"]["started"] == 2
    assert admin["totals"]["completion_rate"] == 0.5
    assert admin["business_acceptance_status"] == "insufficient_sample"
    assert admin["sample_threshold"] == 20
