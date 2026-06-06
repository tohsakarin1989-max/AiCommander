from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import assistant, case_intelligence, cases, conclusions, knowledge, reports, suggestions
from app.database import Base, get_db
from app.models.automation_alert import AutomationAlert
from app.models.case import Case, CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
from app.models.conclusion import Conclusion
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
    app.include_router(cases.router, prefix="/api/cases")
    app.include_router(knowledge.router, prefix="/api/knowledge")
    app.include_router(assistant.router, prefix="/api/assistant")
    app.include_router(reports.router, prefix="/api/reports")
    app.include_router(conclusions.router, prefix="/api/conclusions")
    app.include_router(case_intelligence.router, prefix="/api/case-intelligence")
    app.include_router(suggestions.router, prefix="/api/suggestions")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _seed_case(db: Session, *, case_number: str = "AI-BASE-001", card_status: str = "confirmed") -> Case:
    case = Case(
        case_number=case_number,
        occurred_time=datetime(2026, 3, 8, 1, 30),
        location="萨中作业区北线井场",
        latitude=46.61,
        longitude=125.12,
        case_type="涉油盗窃",
        description="夜间在井场发现车辆停留，现场有软管、油桶和照明不足情况。",
        oil_type="原油",
        oil_volume=1.2,
        source_type="技防预警",
        report_unit="案件三班",
        oil_handling="检斤入库",
        vehicle_handling="扣押待移交",
        status="pending",
        quality_score=68,
        quality_level="medium",
        quality_issues={
            "score": 68,
            "level": "medium",
            "missing_required": [
                {"field": "police_reported", "label": "是否报案"},
                {"field": "case_filed", "label": "是否立案"},
            ],
            "warnings": [],
            "recommendations": ["补齐公安处置字段"],
            "facts": {"has_geo": True},
        },
        features={
            "preprocess_mode": "deterministic_fallback",
            "summary": "夜间井场涉油盗窃案件",
            "analysis_readiness": {"similarity": "ready"},
            "intelligence": {
                "experience_card": {
                    "source_case_id": 0,
                    "case_number": case_number,
                    "manual_review_status": card_status,
                    "summary": "夜间井场停留和软管油桶组合可作为复盘经验。",
                    "reusable_lessons": ["夜间井场异常停留应联动核查照明和视频盲区。"],
                    "evidence_basis": {"tags": [{"label": "夜间发案", "category": "time"}]},
                    "boundary": "仅作为已发生案件经验卡。",
                }
            },
        },
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    case.features["intelligence"]["experience_card"]["source_case_id"] = case.id
    db.add_all(
        [
            CaseVehicle(case_id=case.id, vehicle_type="皮卡", plate_number="黑A12345", handling_status="扣押"),
            CasePerson(case_id=case.id, name="张某", role="嫌疑人", handling_status="移交公安"),
            CaseEvidence(case_id=case.id, evidence_type="photo", title="现场照片", requirement_key="scene_photo"),
            OilRecoveryRecord(case_id=case.id, oil_nature="被盗原油", volume_tons=1.2, handling_method="检斤入库"),
            CaseTip(case_id=case.id, source_type="技防预警", content="夜间异常停留告警"),
            Conclusion(
                case_id=case.id,
                status="needs_review",
                risk_level="high",
                summary="夜间井场停留与软管油桶组合提示现场防护存在短板。",
                evidence={"key_evidence": ["现场照片", "技防告警"]},
            ),
            AutomationAlert(
                alert_number=f"ALERT-{case_number}",
                source_system="radar",
                alert_type="night_motion",
                title="夜间异常停留",
                description="井场附近车辆停留",
                level="high",
                risk_level="high",
                occurred_time=datetime(2026, 3, 8, 1, 10),
                related_case_id=case.id,
            ),
            Report(
                meeting_id=f"MEET-{case_number}",
                report_type="summary",
                content={
                    "summary": "夜间井场异常停留案件复盘",
                    "recommendations": ["补齐照明和视频盲区核查材料"],
                    "information_gaps": ["缺少公安处置结论"],
                },
                consensus_points=["现场照片和告警记录可以支撑基本事实"],
            ),
        ]
    )
    db.commit()
    db.refresh(case)
    return case


def test_case_profile_aggregates_case_foundation_without_mutating_get():
    db = _session()
    client = _client(db)
    case = _seed_case(db)
    original_features = case.features
    original_quality = case.quality_issues

    response = client.get(f"/api/cases/{case.id}/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case"]["id"] == case.id
    assert payload["quality"]["score"] == 68
    assert payload["related"]["vehicles"][0]["plate_number"] == "黑A12345"
    assert payload["related"]["evidence"][0]["title"] == "现场照片"
    assert payload["ai_summary"]["summary"] == "夜间井场涉油盗窃案件"
    assert payload["experience_card"]["manual_review_status"] == "confirmed"
    assert payload["availability"]["has_evidence"] is True
    assert payload["source_map"]["case"] == f"case:{case.id}"
    refreshed = db.query(Case).filter(Case.id == case.id).first()
    assert refreshed.features == original_features
    assert refreshed.quality_issues == original_quality


def test_ai_intake_preview_requires_confirmation_before_writing_fields():
    db = _session()
    client = _client(db)
    case = _seed_case(db)
    raw_text = "2026年3月9日凌晨1时，案件三班在萨中作业区南线井场发现原油被盗，现场有软管和油桶。"

    preview = client.post("/api/cases/structure-preview", json={"text": raw_text})

    assert preview.status_code == 200
    payload = preview.json()
    assert payload["human_confirmation_required"] is True
    assert any(item["field"] == "location" for item in payload["candidates"])
    assert payload["evidence_anchors"]
    assert payload["follow_up_questions"]
    before_location = case.location

    apply_response = client.post(
        f"/api/cases/{case.id}/ai-intake-apply",
        json={
            "confirmed_fields": [
                {"field": "location", "value": "萨中作业区南线井场"},
                {"field": "description", "value": "AI 未确认描述"},
            ],
            "confirmed_field_names": ["location"],
        },
    )

    assert apply_response.status_code == 200
    db.refresh(case)
    assert before_location != case.location
    assert case.location == "萨中作业区南线井场"
    assert case.description != "AI 未确认描述"
    assert apply_response.json()["applied_fields"] == ["location"]


def test_processing_card_groups_case_gaps_and_routes_to_human_review():
    db = _session()
    client = _client(db)
    case = _seed_case(db, card_status="pending")

    response = client.get(f"/api/cases/{case.id}/processing-card")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == case.id
    group_keys = {item["key"] for item in payload["gap_groups"]}
    assert {"quality", "bonus", "experience", "report"}.issubset(group_keys)
    assert payload["manual_review_required"] is True
    assert all(item["mutation_allowed"] is False for item in payload["suggested_actions"])


def test_confirmed_experience_cards_are_searchable_knowledge_assets_only():
    db = _session()
    client = _client(db)
    confirmed = _seed_case(db, case_number="AI-BASE-001", card_status="confirmed")
    draft = _seed_case(db, case_number="AI-BASE-002", card_status="draft")

    response = client.get("/api/knowledge/experience-cards/search", params={"q": "夜间 井场 软管"})

    assert response.status_code == 200
    payload = response.json()
    case_numbers = {item["case_number"] for item in payload["items"]}
    assert confirmed.case_number in case_numbers
    assert draft.case_number not in case_numbers
    first = payload["items"][0]
    assert first["source_type"] == "experience_card"
    assert first["applicability_reason"]
    assert first["evidence_refs"]


def test_experience_card_status_can_be_confirmed_and_archived():
    db = _session()
    client = _client(db)
    case = _seed_case(db, card_status="draft")

    before = client.get("/api/knowledge/experience-cards/search", params={"q": "夜间 井场 软管"})
    assert before.status_code == 200
    assert case.case_number not in {item["case_number"] for item in before.json()["items"]}

    confirmed = client.post(
        f"/api/knowledge/experience-cards/{case.id}/status",
        json={"status": "confirmed", "reviewer": "测试复核", "note": "事实和建议边界已确认"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["manual_review_status"] == "confirmed"
    after = client.get("/api/knowledge/experience-cards/search", params={"q": "夜间 井场 软管"})
    assert case.case_number in {item["case_number"] for item in after.json()["items"]}

    archived = client.post(
        f"/api/knowledge/experience-cards/{case.id}/status",
        json={"status": "archived", "reviewer": "测试复核"},
    )

    assert archived.status_code == 200
    archived_search = client.get("/api/knowledge/experience-cards/search", params={"q": "夜间 井场 软管"})
    assert case.case_number not in {item["case_number"] for item in archived_search.json()["items"]}


def test_processing_card_is_prioritized_in_suggestion_center():
    db = _session()
    client = _client(db)
    case = _seed_case(db, card_status="draft")

    response = client.get("/api/suggestions/", params={"limit": 20})

    assert response.status_code == 200
    items = response.json()["suggestions"]
    card_item = next(item for item in items if item["id"] == f"case-processing-card-{case.id}")
    assert card_item["type"] == "processing_card"
    assert card_item["action"] == "review_processing_card"
    assert card_item["target_id"] == case.id
    assert card_item["meta"]["gap_group_count"] >= 3
    assert "奖金" in " ".join(card_item["meta"]["gap_labels"])


def test_evidence_qa_search_citation_report_review_and_conclusion_draft_are_source_bound():
    db = _session()
    client = _client(db)
    case = _seed_case(db)
    report = db.query(Report).first()

    search = client.get("/api/knowledge/search", params={"q": "夜间 井场 软管"})
    assert search.status_code == 200
    assert search.json()["items"][0]["evidence_refs"]
    assert any(item["source_type"] == "report" for item in search.json()["items"])

    qa = client.post("/api/assistant/evidence-qa", json={"query": "这个案件有什么防护短板？", "case_id": case.id})
    assert qa.status_code == 200
    qa_payload = qa.json()
    assert qa_payload["answer"]
    assert qa_payload["citations"]
    assert qa_payload["insufficient_evidence"] is False

    citation = client.post("/api/reports/citation-assist", json={"query": "夜间井场异常停留", "case_id": case.id})
    assert citation.status_code == 200
    assert citation.json()["citations"][0]["route"] == f"/cases?caseId={case.id}"

    review = client.post(f"/api/reports/{report.id}/review")
    assert review.status_code == 200
    assert "findings" in review.json()
    assert review.json()["manual_review_required"] is True

    draft = client.post("/api/conclusions/draft", json={"case_id": case.id})
    assert draft.status_code == 200
    draft_payload = draft.json()
    assert draft_payload["status"] == "draft"
    assert draft_payload["not_published"] is True
    assert draft_payload["evidence_refs"]


def test_case_diagram_and_tag_curation_are_confirmable_outputs():
    db = _session()
    client = _client(db)
    case = _seed_case(db)

    diagram = client.get(f"/api/cases/{case.id}/diagram")

    assert diagram.status_code == 200
    payload = diagram.json()
    assert payload["case_id"] == case.id
    node_types = {node["type"] for node in payload["nodes"]}
    assert {"case", "time", "location", "vehicle", "person", "evidence", "experience"}.issubset(node_types)
    assert payload["edges"]

    tags = client.post(f"/api/case-intelligence/cases/{case.id}/tag-curation", json={"confirm": False})

    assert tags.status_code == 200
    tag_payload = tags.json()
    assert tag_payload["human_confirmation_required"] is True
    assert tag_payload["applied"] is False
    assert tag_payload["recommended_tags"]
