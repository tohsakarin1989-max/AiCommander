from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import automation_alerts
from app.database import Base, get_db
from app.models.automation_alert import AutomationAlert
from app.models.event import Event
from app.models.case import Case
from app.services.automation_alert_service import AutomationAlertService


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_local()
    db.info['authorized_area_ids'] = None  # Explicit unrestricted synthetic fixture.
    return db


def _client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(automation_alerts.router, prefix="/api/automation-alerts")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _create_alert(client: TestClient, title: str = "人工登记参数异常") -> dict:
    response = client.post("/api/automation-alerts/", json={
        "source_system": "manual",
        "alert_type": "parameter_anomaly",
        "title": title,
        "description": "人工登记的参数异常，需核验设备状态。",
        "location": "合成测试位置",
        "ai_assessment": {"result": "资料待核验", "basis": ["人工登记参数异常"]},
    })
    assert response.status_code == 200
    assert response.json()["is_simulated"] is False
    return response.json()


def test_retired_simulation_endpoint_is_absent_without_business_writes(monkeypatch):
    db = _session()
    client = _client(db)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("retired endpoint must not generate records")

    monkeypatch.setattr(AutomationAlertService, "seed_simulated_alerts", forbidden)
    response = client.post("/api/automation-alerts/simulated")

    assert response.status_code == 404
    assert db.query(AutomationAlert).count() == 0
    assert db.query(Event).count() == 0
    assert db.query(Case).count() == 0


def test_generic_alert_creation_cannot_bypass_retired_simulation():
    db = _session()
    response = _client(db).post("/api/automation-alerts/", json={
        "alert_type": "simulation", "title": "合成测试", "is_simulated": True,
    })
    assert response.status_code == 410
    assert db.query(AutomationAlert).count() == 0


def test_existing_simulated_records_remain_readable_and_unchanged():
    db = _session()
    old = AutomationAlertService.seed_simulated_alerts(db)
    before = [(item.id, item.title, item.status) for item in old]
    client = _client(db)

    response = client.get("/api/automation-alerts/")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {item.id for item in old}
    assert client.post("/api/automation-alerts/simulated").status_code == 404
    assert [(item.id, item.title, item.status) for item in db.query(AutomationAlert).order_by(AutomationAlert.id)] == before


def test_automation_alerts_can_create_event_and_archive_false_alarm():
    db = _session()
    client = _client(db)

    alert_id = _create_alert(client)["id"]

    event_response = client.post(f"/api/automation-alerts/{alert_id}/event")
    assert event_response.status_code == 200
    event_id = event_response.json()["event_id"]
    event = db.query(Event).filter(Event.id == event_id).first()
    assert event is not None
    assert event.discovery_method == "数智自动化告警"
    assert "不自动派发巡逻任务" in event.analysis_notes

    archive_response = client.post(
        f"/api/automation-alerts/{alert_id}/false-alarm",
        json={"note": "现场复核为设备波动"},
    )
    assert archive_response.status_code == 200
    archived = archive_response.json()
    assert archived["status"] == "false_alarm"
    assert archived["risk_level"] == "low"
    db.refresh(event)
    assert event.handling_result == "已核查-误报或设备异常"


def test_automation_alert_can_convert_to_case_without_patrol_dispatch():
    db = _session()
    client = _client(db)

    alert = _create_alert(client)

    response = client.post(f"/api/automation-alerts/{alert['id']}/convert-to-case")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"]
    refreshed = db.query(AutomationAlert).filter(AutomationAlert.id == alert["id"]).first()
    assert refreshed.status == "converted_to_case"
    case = db.query(Case).filter(Case.id == payload["case_id"]).first()
    assert case is not None
    assert case.source_type == "技防预警"
    assert "AI研判" in case.description
    assert case.features is None
    from app.models.case_pipeline import OutboxEvent
    assert db.query(OutboxEvent).filter_by(event_type="case.analysis.requested", aggregate_id=str(case.id)).one().status == "pending"
    from app.models.case_pipeline import CaseAnalysisProfile
    assert db.query(CaseAnalysisProfile).filter_by(case_id=case.id).count() == 0


def test_automation_alert_terminal_states_do_not_conflict():
    db = _session()
    client = _client(db)
    first, second = _create_alert(client, "异常记录一"), _create_alert(client, "异常记录二")

    archived = client.post(f"/api/automation-alerts/{first['id']}/false-alarm", json={"note": "误报"})
    assert archived.status_code == 200
    blocked_convert = client.post(f"/api/automation-alerts/{first['id']}/convert-to-case")
    assert blocked_convert.status_code == 400

    converted = client.post(f"/api/automation-alerts/{second['id']}/convert-to-case")
    assert converted.status_code == 200
    blocked_archive = client.post(f"/api/automation-alerts/{second['id']}/false-alarm", json={"note": "已转案件后不能误报"})
    assert blocked_archive.status_code == 400


def test_automation_alert_triage_pack_links_to_case_context_after_conversion():
    db = _session()
    client = _client(db)
    alert = _create_alert(client)

    before = client.get(f"/api/automation-alerts/{alert['id']}/triage-pack")
    assert before.status_code == 200
    before_payload = before.json()
    assert before_payload["facts"]
    assert before_payload["related_case_context"] is None
    assert "不自动派发巡逻任务" in "；".join(before_payload["boundary"])

    converted = client.post(f"/api/automation-alerts/{alert['id']}/convert-to-case")
    assert converted.status_code == 200
    after = client.get(f"/api/automation-alerts/{alert['id']}/triage-pack")
    assert after.status_code == 200
    after_payload = after.json()
    assert after_payload["alert"]["related_case_id"] == converted.json()["case_id"]
    assert after_payload["related_case_context"]["facts"]
