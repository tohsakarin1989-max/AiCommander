from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import knowledge
from app.config import settings
from app.database import Base, get_db
from app.models.case import Case, CaseEvidence
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset, KnowledgeReuseRecord
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_pipeline_service import CasePipelineService


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_local()
    db.info["authorized_area_ids"] = None  # Explicit unrestricted synthetic-test principal.
    return db


def _freeze_result(db: Session, case: Case) -> None:
    case.quality_issues = None
    event = CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    if event:
        CasePipelineService.process_event(db, event.id)


def _client(db: Session, *, role: str | None = None) -> TestClient:
    app = FastAPI()

    if role:
        @app.middleware("http")
        async def inject_principal(request: Request, call_next):
            request.state.principal = SimpleNamespace(user_id=None, role=role)
            return await call_next(request)

    app.include_router(knowledge.router, prefix="/api/knowledge")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.test_db = db
    return client


def _seed_case(
    db: Session,
    *,
    number: str,
    location: str = "北区偏远井场",
    description: str = "凌晨发现皮卡停留，现场遗留软管和油桶，照明覆盖不足。",
) -> Case:
    case = Case(
        case_number=number,
        occurred_time=datetime(2026, 8, 3, 2, 20),
        location=location,
        latitude=46.61,
        longitude=125.12,
        case_type="涉油盗窃",
        facility_type="管线",
        modus_operandi="软管抽油",
        source_type="技防预警",
        description=description,
        status="closed",
        quality_issues={"missing_required": []},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseEvidence(
            case_id=case.id,
            evidence_type="photo",
            title="现场照片",
            requirement_key="scene_photo",
        )
    )
    db.commit()
    _freeze_result(db, case)
    from tests.history_index_helpers import build_history_index
    build_history_index(db)
    return case


def _generate_experience(client: TestClient, case_id: int) -> dict:
    response = client.post(f"/api/knowledge/cases/{case_id}/experience-assets")
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client: TestClient, asset_id: int) -> dict:
    response = client.post(
        f"/api/knowledge/assets/{asset_id}/review",
        json={"status": "confirmed", "note": "事实、依据和适用边界已人工核验"},
    )
    assert response.status_code == 200, response.text
    from tests.history_index_helpers import build_history_index
    build_history_index(client.test_db)
    return response.json()


def test_experience_assets_are_versioned_and_unchanged_generation_is_idempotent():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-001")

    first = _generate_experience(client, case.id)
    repeated = _generate_experience(client, case.id)

    assert first["id"] == repeated["id"]
    assert first["version"] == 1
    assert first["status"] == "draft"
    assert first["evidence_refs"]

    case.description = f"{case.description} 补充核验道路通达条件。"
    db.commit()
    _freeze_result(db, case)
    changed = _generate_experience(client, case.id)

    assert changed["id"] != first["id"]
    assert changed["version"] == 2
    assert db.query(KnowledgeAsset).count() == 2


def test_review_rejects_stale_asset_and_confirm_is_idempotent():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-002")
    asset = _generate_experience(client, case.id)

    case.location = "南区井场"
    db.commit()
    stale = client.post(
        f"/api/knowledge/assets/{asset['id']}/review",
        json={"status": "confirmed", "note": "尝试确认旧版本"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "源案件已变化，请重新生成后复核"

    _freeze_result(db, case)
    current = _generate_experience(client, case.id)
    confirmed = _confirm(client, current["id"])
    repeated = _confirm(client, current["id"])

    assert confirmed["status"] == "confirmed"
    assert repeated["status"] == "confirmed"
    assert repeated["id"] == confirmed["id"]


def test_archived_experience_can_be_regenerated_as_a_new_draft_version():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-ARCHIVE-REGENERATE")
    first = _generate_experience(client, case.id)
    archived = client.post(
        f"/api/knowledge/assets/{first['id']}/review",
        json={"status": "archived", "note": "当前版本不再采用"},
    )

    regenerated = _generate_experience(client, case.id)

    assert archived.status_code == 200
    assert regenerated["id"] != first["id"]
    assert regenerated["version"] == 2
    assert regenerated["status"] == "draft"


def test_review_rejects_asset_when_evidence_changed_after_generation():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-EVIDENCE-STALE")
    asset = _generate_experience(client, case.id)

    evidence = (
        db.query(CaseEvidence)
        .filter(CaseEvidence.case_id == case.id)
        .first()
    )
    evidence.title = "补充核验后的现场照片"
    db.commit()

    stale = client.post(
        f"/api/knowledge/assets/{asset['id']}/review",
        json={"status": "confirmed", "note": "证据变化后不能确认旧版本"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "源案件已变化，请重新生成后复核"


def test_frozen_experience_does_not_recompute_unrelated_map_after_generation():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-MAP-STALE")
    asset = _generate_experience(client, case.id)

    db.add(
        JurisdictionAsset(
            name="新核验重点井",
            asset_type="well",
            latitude=46.611,
            longitude=125.121,
            status="active",
            verified=True,
        )
    )
    db.commit()

    stale = client.post(
        f"/api/knowledge/assets/{asset['id']}/review",
        json={"status": "confirmed", "note": "地图底座变化后不能确认旧版本"},
    )

    assert stale.status_code == 200
    assert stale.json()['status'] == 'confirmed'


def test_generation_reuses_frozen_quality_without_mutating_case():
    db = _session()
    client = _client(db)
    experience_case = _seed_case(db, number="KA-QUALITY-EXPERIENCE")
    experience_case.quality_issues = None
    report_case = _seed_case(db, number="KA-QUALITY-REPORT")
    report_case.quality_issues = None
    db.commit()

    experience = _generate_experience(client, experience_case.id)
    assert experience_case.quality_issues is None
    assert _confirm(client, experience["id"])["status"] == "confirmed"

    _freeze_result(db, report_case)
    report = client.post(
        f"/api/knowledge/cases/{report_case.id}/report-snapshots",
        json={"experience_asset_ids": [], "days": 365},
    ).json()

    assert _confirm(client, report["id"])["status"] == "confirmed"


def test_generated_experience_card_does_not_feed_back_into_source_tags():
    db = _session()
    case = _seed_case(db, number="KA-NO-FEEDBACK")

    before = {
        item["key"]
        for item in CaseIntelligenceService.build_case_tags(db, case)["tags"]
    }
    CaseIntelligenceService.build_experience_card(db, case.id)
    db.refresh(case)
    after = {
        item["key"]
        for item in CaseIntelligenceService.build_case_tags(db, case)["tags"]
    }

    assert after == before


def test_recommendations_only_return_confirmed_historical_experience():
    db = _session()
    client = _client(db)
    target = _seed_case(db, number="KA-TARGET")
    confirmed_case = _seed_case(db, number="KA-CONFIRMED")
    draft_case = _seed_case(db, number="KA-DRAFT", location="北区偏远井场二号点")
    confirmed_asset = _generate_experience(client, confirmed_case.id)
    _confirm(client, confirmed_asset["id"])
    _generate_experience(client, draft_case.id)

    response = client.get(f"/api/knowledge/cases/{target.id}/reuse-recommendations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["target_case_id"] == target.id
    assert payload["manual_selection_required"] is True
    assert payload["boundary"]
    source_numbers = {item["source_case_number"] for item in payload["items"]}
    assert confirmed_case.case_number in source_numbers
    assert draft_case.case_number not in source_numbers
    item = next(item for item in payload["items"] if item["source_case_number"] == confirmed_case.case_number)
    assert item["asset_id"] == confirmed_asset["id"]
    assert item["similarity_score"] > 0  # RRF rank support is not an old percentage threshold.
    assert item["applicability_reasons"]
    assert item["evidence_refs"]


def test_report_snapshot_reuses_only_selected_confirmed_assets_and_records_trace():
    db = _session()
    client = _client(db)
    target = _seed_case(db, number="KA-REPORT")
    source = _seed_case(db, number="KA-SOURCE")
    source_asset = _generate_experience(client, source.id)

    rejected = client.post(
        f"/api/knowledge/cases/{target.id}/report-snapshots",
        json={"experience_asset_ids": [source_asset["id"]], "days": 365},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "只能引用已确认且未归档的经验资产"

    _confirm(client, source_asset["id"])
    _freeze_result(db, target)
    response = client.post(
        f"/api/knowledge/cases/{target.id}/report-snapshots",
        json={"experience_asset_ids": [source_asset["id"]], "days": 365},
    )

    assert response.status_code == 201, response.text
    report = response.json()
    assert report["asset_type"] == "case_report"
    assert report["status"] == "draft"
    assert report["content"]["reused_experience"][0]["asset_id"] == source_asset["id"]
    assert f"knowledge_asset:{source_asset['id']}" in {
        item["id"] for item in report["evidence_refs"]
    }
    assert source.case_number in report["content"]["report"]["ai_output"]["markdown"]
    assert db.query(KnowledgeReuseRecord).count() == 1
    trace = db.query(KnowledgeReuseRecord).first()
    assert trace.source_asset_id == source_asset["id"]
    assert trace.target_case_id == target.id
    assert trace.target_asset_id == report["id"]
    assert trace.decision == "referenced"

    repeated = client.post(
        f"/api/knowledge/cases/{target.id}/report-snapshots",
        json={"experience_asset_ids": [source_asset["id"]], "days": 365},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == report["id"]
    assert db.query(KnowledgeReuseRecord).count() == 1
    confirmed_report = _confirm(client, report["id"])
    assert confirmed_report["status"] == "confirmed"


def test_reuse_decision_is_audited_without_mutating_target_case():
    db = _session()
    client = _client(db)
    target = _seed_case(db, number="KA-AUDIT")
    source = _seed_case(db, number="KA-AUDIT-SOURCE")
    source_asset = _generate_experience(client, source.id)
    _confirm(client, source_asset["id"])
    before_description = target.description

    accepted = client.post(
        "/api/knowledge/reuse-decisions",
        json={
            "source_asset_id": source_asset["id"],
            "target_case_id": target.id,
            "decision": "accepted",
            "purpose": "作为本案报告参考",
            "note": "现场条件相近，仍需逐项核验证据",
        },
    )
    repeated = client.post(
        "/api/knowledge/reuse-decisions",
        json={
            "source_asset_id": source_asset["id"],
            "target_case_id": target.id,
            "decision": "accepted",
            "purpose": "作为本案报告参考",
            "note": "重复提交不应重复记录",
        },
    )

    assert accepted.status_code == 201
    assert repeated.status_code == 200
    assert accepted.json()["id"] == repeated.json()["id"]
    db.refresh(target)
    assert target.description == before_description
    assert db.query(KnowledgeReuseRecord).count() == 1

    history = client.get(
        "/api/knowledge/reuse-records",
        params={"target_case_id": target.id},
    )
    assert history.status_code == 200
    assert history.json()["items"][0]["decision"] == "accepted"

    blank_purpose = client.post(
        "/api/knowledge/reuse-decisions",
        json={
            "source_asset_id": source_asset["id"],
            "target_case_id": target.id,
            "decision": "accepted",
            "purpose": "   ",
        },
    )
    assert blank_purpose.status_code == 422


def test_viewer_cannot_generate_review_or_record_reuse(monkeypatch):
    db = _session()
    case = _seed_case(db, number="KA-VIEWER")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    client = _client(db, role="viewer")

    generate = client.post(f"/api/knowledge/cases/{case.id}/experience-assets")
    reuse = client.post(
        "/api/knowledge/reuse-decisions",
        json={
            "source_asset_id": 1,
            "target_case_id": case.id,
            "decision": "accepted",
            "purpose": "无权限测试",
        },
    )
    legacy_status = client.post(
        f"/api/knowledge/experience-cards/{case.id}/status",
        json={"status": "confirmed"},
    )

    assert generate.status_code == 403
    assert reuse.status_code == 403
    assert legacy_status.status_code == 403
    assert db.query(KnowledgeAsset).count() == 0


def test_confirmed_version_is_searchable_while_new_draft_stays_hidden():
    db = _session()
    client = _client(db)
    case = _seed_case(db, number="KA-SEARCH")
    confirmed = _generate_experience(client, case.id)
    _confirm(client, confirmed["id"])

    first_search = client.get(
        "/api/knowledge/experience-cards/search",
        params={"q": "凌晨 软管"},
    )
    assert first_search.status_code == 200
    assert first_search.json()["items"][0]["asset_id"] == confirmed["id"]

    case.description = f"{case.description} 新增尚未复核的围栏缺口。"
    db.commit()
    _freeze_result(db, case)
    draft = _generate_experience(client, case.id)
    assert draft["version"] == 2

    second_search = client.get(
        "/api/knowledge/experience-cards/search",
        params={"q": "凌晨 软管"},
    )
    assert second_search.status_code == 200
    assert second_search.json()["items"][0]["asset_id"] == confirmed["id"]
    assert draft["id"] not in {item["asset_id"] for item in second_search.json()["items"]}


def test_frozen_report_confirmation_does_not_recompute_unrelated_scope():
    db = _session()
    client = _client(db)
    target = _seed_case(db, number="KA-SCOPE")
    _freeze_result(db, target)
    report = client.post(
        f"/api/knowledge/cases/{target.id}/report-snapshots",
        json={"experience_asset_ids": [], "days": 365},
    ).json()

    _seed_case(db, number="KA-SCOPE-NEW")
    stale = client.post(
        f"/api/knowledge/assets/{report['id']}/review",
        json={"status": "confirmed", "note": "统计范围变化后不能确认旧报告"},
    )

    assert stale.status_code == 200
    assert stale.json()["status"] == "confirmed"
