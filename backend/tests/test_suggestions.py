from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import suggestions
from app.database import Base, get_db
from app.models.automation_alert import AutomationAlert
from app.models.case import Case, CaseVehicle
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.meeting import Meeting
from app.models.patrol import AreaRiskAssessment


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_local()


def _client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(suggestions.router, prefix="/api/suggestions")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_work_items(db: Session) -> Case:
    now = datetime.utcnow()
    case = Case(
        case_number="SUG-001",
        occurred_time=now - timedelta(days=1),
        location="萨中作业区",
        case_type="涉油盗窃",
        description="抓获一辆涉案车辆，现场发现原油和软管，待补坐标与核算指标。",
        oil_type="原油",
        oil_volume=1.2,
        oil_nature="被盗原油",
        oil_handling="检斤入库",
        vehicle_handling="扣押停放",
        status="pending",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseVehicle(
            case_id=case.id,
            vehicle_type="未识别车辆",
            plate_number="黑A00001",
            handling_status="扣押停放",
        )
    )
    db.add(
        Conclusion(
            case_id=case.id,
            status="needs_review",
            risk_level="high",
            summary="该结论缺少事实引用，需要人工复核。",
        )
    )
    db.add(
        Event(
            event_number="EVT-SUG-001",
            title="技防告警待转案件",
            event_type="sensor",
            risk_level="high",
            occurred_time=now - timedelta(hours=2),
        )
    )
    db.add(
        Meeting(
            meeting_id="MEET-SUG-001",
            case_ids=[case.id],
            status="completed",
            completed_at=now - timedelta(hours=1),
        )
    )
    db.add(
        AutomationAlert(
            alert_number="ALERT-SUG-001",
            source_system="radar",
            alert_type="night_motion",
            title="夜间异常停留",
            description="井场附近夜间停留，需要打开研判包核查。",
            level="high",
            risk_level="high",
            occurred_time=now - timedelta(minutes=30),
            status="pending_review",
            ai_assessment={"risk": "high"},
            suggested_actions=["核查现场视频"],
        )
    )
    db.add(
        AreaRiskAssessment(
            area_name="萨中北线",
            risk_score=86,
            risk_level="high",
            case_count_30d=4,
        )
    )
    db.commit()
    return case


def test_suggestions_unifies_real_review_work_items_without_patrol_dispatch():
    db = _session()
    client = _client(db)
    case = _seed_work_items(db)

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    payload = response.json()
    items = payload["suggestions"]
    assert payload["total"] == len(items)
    types = {item["type"] for item in items}
    assert {
        "data_quality",
        "analysis",
        "bonus",
        "alert",
        "review",
        "experience",
        "report_quality",
        "workflow",
    }.issubset(types)
    actions = {item["action"] for item in items}
    assert "create_patrol" not in actions
    assert "review_prevention_reference" in actions
    assert "open_alert_triage_pack" in actions
    assert any(item["action"] == "review_bonus_data" and item["target_id"] == case.id for item in items)
    assert not any("派发巡逻" in str(item) or "生成巡逻" in str(item) for item in items)


def test_suggestions_get_does_not_mutate_case_quality_or_experience_card():
    db = _session()
    client = _client(db)
    now = datetime.utcnow()
    case = Case(
        case_number="SUG-READ-ONLY",
        occurred_time=now - timedelta(days=1),
        location="萨中作业区",
        case_type="涉油盗窃",
        description="现场发现涉油车辆和软管，待后续人工处理。",
        status="pending",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    db.refresh(case)
    assert case.quality_issues is None
    assert case.quality_score is None
    assert case.features is None
    assert any(
        item["action"] == "generate_experience_card" and item["target_id"] == case.id
        for item in response.json()["suggestions"]
    )


def test_suggestions_derives_bonus_data_gaps_from_bonus_items_without_gate(monkeypatch):
    db = _session()
    client = _client(db)
    case = _seed_work_items(db)

    def fake_bonus_assessment(_db, _case):
        return {
            "material_gate": {"status": "ready", "missing_materials": []},
            "bonus_items": [
                {
                    "key": "small_vehicle_reward",
                    "label": "5吨以下机动车奖励",
                    "status": "blocked_by_data",
                    "blocked_by": ["vehicle_count"],
                },
                {
                    "key": "other_person_reward",
                    "label": "其他处置人员奖励",
                    "status": "blocked_by_data",
                    "blocked_by": [],
                },
            ],
        }

    monkeypatch.setattr(
        suggestions.CaseAutomationService,
        "build_bonus_assessment",
        fake_bonus_assessment,
    )

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    items = response.json()["suggestions"]
    bonus_item = next(
        item
        for item in items
        if item["action"] == "review_bonus_data" and item["target_id"] == case.id
    )
    assert bonus_item["meta"]["missing_items"] == [
        {
            "key": "small_vehicle_reward",
            "label": "5吨以下机动车奖励",
            "blocked_by": ["vehicle_count"],
        }
    ]


def test_suggestions_hides_bonus_exception_details(monkeypatch):
    db = _session()
    client = _client(db)
    case = _seed_work_items(db)

    def broken_bonus_assessment(_db, _case):
        raise RuntimeError("internal-secret-token")

    monkeypatch.setattr(
        suggestions.CaseAutomationService,
        "build_bonus_assessment",
        broken_bonus_assessment,
    )

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    bonus_item = next(
        item
        for item in response.json()["suggestions"]
        if item["id"] == f"case-bonus-error-{case.id}"
    )
    assert bonus_item["description"] == "奖金门禁检查遇到异常，请进入案件页人工复核指标和材料。"
    assert "internal-secret-token" not in str(bonus_item)


def test_suggestions_hides_experience_exception_details(monkeypatch):
    db = _session()
    client = _client(db)
    case = _seed_work_items(db)

    def broken_existing_experience_card(_case):
        raise RuntimeError("experience-secret-token")

    monkeypatch.setattr(suggestions, "_existing_experience_card", broken_existing_experience_card)

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    experience_item = next(
        item
        for item in response.json()["suggestions"]
        if item["id"] == f"case-experience-error-{case.id}"
    )
    assert experience_item["description"] == "经验卡待人工复核，请进入案件研判页重新生成或确认。"
    assert "experience-secret-token" not in str(experience_item)
