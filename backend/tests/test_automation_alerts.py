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
    app.include_router(automation_alerts.router, prefix="/api/automation-alerts")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_simulated_automation_alerts_can_create_event_and_archive_false_alarm():
    db = _session()
    client = _client(db)

    seeded = client.post("/api/automation-alerts/simulated")
    assert seeded.status_code == 200
    alerts = seeded.json()
    assert len(alerts) == 2
    alert_id = alerts[0]["id"]

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

    alert = client.post("/api/automation-alerts/simulated").json()[1]

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
    assert case.features["preprocess_mode"] == "deterministic_fallback"
    assert case.features["analysis_readiness"]["similarity"] in {"ready", "partial"}


def test_automation_alert_terminal_states_do_not_conflict():
    db = _session()
    client = _client(db)
    first, second = client.post("/api/automation-alerts/simulated").json()

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
    alert = client.post("/api/automation-alerts/simulated").json()[0]

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
