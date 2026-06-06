from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import automation_alerts, case_intelligence, conclusions, reports
from app.database import Base, get_db
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.meeting import Meeting
from app.models.report import Report


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
    app.include_router(case_intelligence.router, prefix="/api/case-intelligence")
    app.include_router(automation_alerts.router, prefix="/api/automation-alerts")
    app.include_router(conclusions.router, prefix="/api/conclusions")
    app.include_router(reports.router, prefix="/api/reports")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_case(db: Session, number: str, days_ago: int, hour: int, description: str) -> Case:
    occurred = (datetime.utcnow() - timedelta(days=days_ago)).replace(
        hour=hour,
        minute=20,
        second=0,
        microsecond=0,
    )
    case = Case(
        case_number=number,
        occurred_time=occurred,
        location="南区12号井附近",
        latitude=39.9,
        longitude=116.4,
        case_type="涉油盗窃",
        description=description,
        facility_type="井口",
        oil_type="原油",
        source_type="巡逻发现",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def test_case_report_exposes_normalized_ai_output_with_review_boundary():
    db = _session()
    client = _client(db)
    selected = _add_case(
        db,
        "AI-B-001",
        1,
        2,
        "凌晨发现皮卡车靠近井场，车内有油桶和软管，现场照明不足。",
    )
    _add_case(
        db,
        "AI-B-002",
        8,
        3,
        "夜间厢货车停在井场便道旁，发现油桶和抽油泵，周边监控盲区。",
    )

    response = client.get("/api/case-intelligence/report", params={"case_id": selected.id, "days": 30})

    assert response.status_code == 200
    ai_output = response.json()["ai_output"]
    assert ai_output["output_type"] == "case_intelligence_report"
    assert ai_output["draft_status"] == "draft"
    assert ai_output["review_status"] == "pending_review"
    assert ai_output["model_status"] == "deterministic_fallback"
    assert ai_output["facts"]
    assert ai_output["inferences"]
    assert ai_output["recommendations"]
    assert ai_output["information_gaps"]
    assert ai_output["evidence_refs"]
    assert "不得把防控参考写成已执行任务" in "；".join(ai_output["boundary"])
    assert "## 事实依据" in ai_output["markdown"]
    assert "## 证据索引" in ai_output["markdown"]


def test_alert_triage_pack_uses_same_ai_output_contract_without_dispatch_language():
    db = _session()
    client = _client(db)
    alert = client.post("/api/automation-alerts/simulated").json()[0]

    response = client.get(f"/api/automation-alerts/{alert['id']}/triage-pack")

    assert response.status_code == 200
    ai_output = response.json()["ai_output"]
    assert ai_output["output_type"] == "automation_alert_triage_pack"
    assert ai_output["draft_status"] == "draft"
    assert ai_output["review_status"] == "pending_review"
    assert ai_output["model_status"] == "deterministic_fallback"
    assert ai_output["facts"]
    assert ai_output["inferences"]
    assert ai_output["recommendations"]
    assert ai_output["information_gaps"]
    assert any(ref["id"].startswith("alert:") for ref in ai_output["evidence_refs"])
    assert "## 建议与补齐事项" in ai_output["markdown"]
    assert "派发巡逻" not in ai_output["markdown"]
    assert "不得把告警建议写成已执行任务" in "；".join(ai_output["boundary"])


def test_report_api_exposes_normalized_review_draft_markdown():
    db = _session()
    client = _client(db)
    meeting = Meeting(
        meeting_id="MEET-B-001",
        case_ids=[],
        status="completed",
        moderator_model_id=1,
        analyst_model_ids=[2, 3],
    )
    db.add(meeting)
    db.flush()
    report = Report(
        meeting_id=meeting.meeting_id,
        report_type="comprehensive",
        content={
            "summary": "会议认为应复核夜间井场同类条件。",
            "conclusions": "同类案件存在时空条件相似性。",
            "recommendations": ["补齐现场照片", "人工复核相似条件"],
        },
        consensus_points=["夜间井场要重点复核"],
        disagreement_points=[],
        model_contributions={"analyst_a": "提炼事实依据"},
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    response = client.get(f"/api/reports/{report.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_status"] == "draft"
    assert payload["review_status"] == "pending_review"
    assert payload["ai_output"]["output_type"] == "meeting_report_draft"
    assert payload["ai_output"]["facts"]
    assert payload["ai_output"]["inferences"]
    assert payload["ai_output"]["recommendations"]
    assert payload["ai_output"]["evidence_refs"][0]["id"] == f"report:{report.id}"
    assert "## 事实依据" in payload["ai_output"]["markdown"]
    assert "## 证据索引" in payload["ai_output"]["markdown"]


def test_conclusion_generation_and_detail_expose_review_draft_contract():
    db = _session()
    client = _client(db)
    case = _add_case(
        db,
        "AI-B-003",
        3,
        1,
        "夜间发现可疑车辆靠近井场，缺少现场照片和车辆处置材料。",
    )

    generated = client.post("/api/conclusions/generate", json={"case_id": case.id})

    assert generated.status_code == 200
    generated_payload = generated.json()
    assert generated_payload["status"] == "needs_review"
    assert generated_payload["draft_status"] == "draft"
    assert generated_payload["review_status"] == "pending_review"
    ai_output = generated_payload["ai_output"]
    assert ai_output["output_type"] == "conclusion_draft"
    assert ai_output["facts"]
    assert ai_output["inferences"]
    assert ai_output["recommendations"]
    assert ai_output["information_gaps"]
    assert any(ref["id"].startswith("case:") for ref in ai_output["evidence_refs"])
    assert "不替代人工审核" in "；".join(ai_output["boundary"])

    detail = client.get(f"/api/conclusions/{generated_payload['id']}")

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["ai_output"]["markdown"] == ai_output["markdown"]
    assert detail_payload["review_status"] == "pending_review"

    approved = client.post(
        f"/api/conclusions/{generated_payload['id']}/review",
        json={"action": "approve"},
    )
    assert approved.status_code == 200
    approved_detail = client.get(f"/api/conclusions/{generated_payload['id']}").json()
    assert approved_detail["review_status"] == "approved"


def test_legacy_conclusion_detail_builds_fallback_ai_output_contract():
    db = _session()
    client = _client(db)
    conclusion = Conclusion(
        case_id=42,
        status="needs_review",
        confidence=0.62,
        risk_level="medium",
        summary="历史结论需要补充标准化草稿。",
        evidence={
            "key_evidence": ["夜间井场周边有异常车辆停留"],
            "recommendations": ["补充调取卡口记录"],
        },
    )
    db.add(conclusion)
    db.commit()
    db.refresh(conclusion)

    detail = client.get(f"/api/conclusions/{conclusion.id}")

    assert detail.status_code == 200
    payload = detail.json()
    ai_output = payload["ai_output"]
    assert ai_output["output_type"] == "conclusion_draft"
    assert ai_output["draft_status"] == "draft"
    assert ai_output["review_status"] == "pending_review"
    assert ai_output["model_status"] == "deterministic_fallback"
    assert ai_output["facts"] == ["夜间井场周边有异常车辆停留"]
    assert ai_output["recommendations"][0]["action"] == "补充调取卡口记录"
    assert any(ref["id"] == f"conclusion:{conclusion.id}" for ref in ai_output["evidence_refs"])
    assert "## 事实依据" in ai_output["markdown"]
    assert "## 证据索引" in ai_output["markdown"]
