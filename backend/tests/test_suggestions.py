import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import suggestions
from app.database import Base, get_db
from app.models.automation_alert import AutomationAlert
from app.models.case import Case, CasePerson, CaseVehicle
from app.models.conclusion import Conclusion
from app.models.event import Event
from app.models.meeting import Meeting
from app.models.patrol import AreaRiskAssessment
from app.models.report import Report
from app.services.case_automation_service import CaseAutomationService
from app.services.case_result_service import CaseResultService
from app.services.conclusion_factory_service import ConclusionFactoryService


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
        features={"intelligence": {"experience_card": {"summary": "已有待确认经验", "manual_review_status": "draft"}}},
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
    db.flush()
    db.add(Report(meeting_id="MEET-SUG-001", report_type="comprehensive", content={"summary": "已有会议报告"}))
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
        "bonus",
        "alert",
        "review",
        "experience",
        "report_quality",
        "workflow",
    }.issubset(types)
    actions = {item["action"] for item in items}
    assert "create_patrol" not in actions
    assert "preprocess_case" not in actions
    assert "generate_experience_card" not in actions
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
    assert not any(
        item["action"] in {"generate_experience_card", "preprocess_case"} and item["target_id"] == case.id
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


def test_suggestions_uses_real_bonus_calculation_gate_for_data_review():
    db = _session()
    client = _client(db)
    now = datetime.utcnow()
    case = Case(
        case_number="SUG-BONUS-GATE",
        occurred_time=now - timedelta(hours=1),
        location="萨中作业区",
        case_type="涉油盗窃",
        description="案件一班现场发现一台5吨以下机动车盗运原油，抓获1人，车辆移交公安，检斤入库。",
        report_unit="案件一班",
        oil_type="原油",
        oil_volume=1.0,
        water_cut=8,
        oil_nature="被盗原油",
        oil_handling="检斤入库",
        vehicle_handling="移交公安",
        security_officers=["案件一班:张三"],
        status="pending",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseVehicle(
            case_id=case.id,
            vehicle_type="5吨以下机动车",
            plate_number="黑A12345",
            handling_status="移交公安",
        )
    )
    db.add(CasePerson(case_id=case.id, name="王某"))
    db.commit()

    bonus = CaseAutomationService.build_bonus_assessment(db, case)

    assert bonus["calculation_gate"]["status"] == "blocked_by_data"
    assert bonus["calculation_gate"]["missing_items"] == [
        {
            "key": "person_disposition",
            "label": "人员处理类型",
            "detail": "已记录抓获人员，但缺少行政拘留、刑事拘留等处理结果，需补齐后整案测算。",
        }
    ]
    item_status = {item["key"]: item["status"] for item in bonus["bonus_items"]}
    assert item_status["small_vehicle_reward"] == "blocked_by_data"
    assert item_status["other_person_reward"] == "blocked_by_data"

    response = client.get("/api/suggestions/", params={"limit": 50})

    assert response.status_code == 200
    assert any(
        item["action"] == "review_bonus_data" and item["target_id"] == case.id
        for item in response.json()["suggestions"]
    )


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
    assert experience_item["description"] == "现有经验卡状态暂时无法读取，请稍后重试；无需重新生成。"
    assert experience_item["action"] == "review_experience_card"
    assert "experience-secret-token" not in str(experience_item)


def test_no_optional_artifacts_does_not_manufacture_daily_tasks(monkeypatch):
    db = _session()
    monkeypatch.setattr(suggestions.settings, "ENABLE_BONUS_ACCOUNTING", False)
    db.add(Case(case_number="SUG-OPTIONAL", occurred_time=datetime.utcnow(), location="合成地点",
                latitude=46.6, longitude=125.0, description="已有完整记录，但没有手工生成的经验卡或报告。",
                quality_issues={"score": 100, "missing_required": []}, status="pending"))
    db.add(Meeting(meeting_id="NO-REPORT", case_ids=[], status="completed", completed_at=datetime.utcnow()))
    db.commit()
    payload = _client(db).get("/api/suggestions/").json()
    assert payload["suggestions"] == []
    assert payload["total"] == 0
    assert payload["summary"]["total"] == 0
    assert payload["summary"]["workflow"] == {}


@pytest.mark.parametrize("review_status", ["confirmed", "approved", "archived"])
def test_finished_experience_is_not_reopened_as_daily_work(monkeypatch, review_status):
    db = _session()
    monkeypatch.setattr(suggestions.settings, "ENABLE_BONUS_ACCOUNTING", False)
    db.add(Case(case_number="SUG-CARD", occurred_time=datetime.utcnow(), location="合成地点",
                latitude=46.6, longitude=125.0, description="合成记录", status="pending",
                quality_issues={"score": 100, "missing_required": []},
                features={"intelligence": {"experience_card": {"summary": "已处理卡", "manual_review_status": review_status}}}))
    db.commit()
    payload = _client(db).get("/api/suggestions/").json()
    assert payload["suggestions"] == [] and payload["summary"]["total"] == 0


def test_summary_workflow_filter_and_pagination_share_full_queue():
    db = _session()
    now = datetime.utcnow()
    for index in range(27):
        db.add(Event(event_number=f"SUG-PAGE-{index:02}", title="独立待判断事件", event_type="manual",
                     occurred_time=now, created_at=now, risk_level="medium"))
    db.add(AutomationAlert(alert_number="SUG-PAGE-ALERT", source_system="manual", alert_type="manual",
                           title="已有告警", occurred_time=now, status="pending_review"))
    db.commit()
    client = _client(db)
    first = client.get("/api/suggestions/", params={"limit": 10}).json()
    second = client.get("/api/suggestions/", params={"limit": 10, "offset": 10}).json()
    last = client.get("/api/suggestions/", params={"limit": 10, "offset": 20}).json()
    all_ids = [item["id"] for page in (first, second, last) for item in page["suggestions"]]
    assert len(all_ids) == len(set(all_ids)) == 28
    assert first["total"] == second["total"] == last["total"] == 28
    assert first["summary"] == second["summary"] == last["summary"]
    assert first["summary"]["workflow"] == {"event_review": 27, "alert": 1}
    assert sum(first["summary"]["priority"].values()) == 28
    assert first["has_more"] and second["has_more"] and not last["has_more"]
    filtered = client.get("/api/suggestions/", params={"workflow": "event_review", "offset": 20, "limit": 10}).json()
    assert filtered["total"] == 27 and len(filtered["suggestions"]) == 7
    assert filtered["summary"] == first["summary"]
    assert all(item["workflow"] == "event_review" for item in filtered["suggestions"])
    assert not filtered["has_more"]
    closed = client.get("/api/suggestions/", params={"status": "closed"}).json()
    assert closed["total"] == closed["summary"]["total"] == 0


def test_cases_after_previous_twenty_row_cap_remain_reachable(monkeypatch):
    db = _session()
    monkeypatch.setattr(suggestions.settings, "ENABLE_BONUS_ACCOUNTING", False)
    now = datetime.utcnow()
    for index in range(23):
        db.add(Case(case_number=f"SUG-CASE-{index:02}", occurred_time=now, location="合成地点",
                    latitude=46.6, longitude=125.0, description="合成记录", status="pending",
                    quality_issues={"score": 100, "missing_required": []},
                    features={"intelligence": {"experience_card": {"summary": "已有草稿", "manual_review_status": "draft"}}}))
    db.commit()
    payload = _client(db).get("/api/suggestions/", params={"workflow": "experience", "limit": 200}).json()
    assert payload["total"] == 23
    assert len(payload["suggestions"]) == 23
    assert payload["summary"]["workflow"]["experience"] == 23


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"workflow": "preprocessing_gap"}])
def test_invalid_pagination_or_removed_workflow_is_rejected(params):
    db = _session()
    response = _client(db).get("/api/suggestions/", params=params)
    assert response.status_code == 422


def test_conclusion_reference_revocation_removes_item_and_summary(monkeypatch):
    from test_case_result_snapshot import inputs
    from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, OperationalArea, PublicMapBundle
    from app.models.jurisdiction import JurisdictionAsset
    from app.services.case_pipeline_service import (
        CASE_DICTIONARY_VERSION, CASE_PROFILE_SCHEMA_VERSION, CasePipelineService,
    )

    db = _session()
    monkeypatch.setattr(suggestions.settings, "ENABLE_BONUS_ACCOUNTING", False)
    db.add_all([OperationalArea(id=i, code=f"SUG-{i}", name="合成辖区") for i in (1, 2)])
    db.flush()
    db.add_all([Case(id=i, case_number=f"SUG-REF-{i}", operational_area_id=i,
                     occurred_time=datetime(2026, 9, 1), description="合成记录", location="合成地点",
                     latitude=46.6, longitude=125.0, status="pending",
                     quality_issues={"score": 100, "missing_required": []}) for i in (1, 2)])
    db.add(PublicMapBundle(id=1, bundle_id="synthetic", provider="synthetic", source_version="1",
                           license_record="test", bounds=[], manifest={}, package_hash="test"))
    db.flush()
    db.add(MapSnapshot(id="map-1", version="synthetic-1", operational_area_id=1,
                       public_bundle_id=1, manifest={}, feature_watermark="1", status="current"))
    db.add(JurisdictionAsset(id=1, operational_area_id=1, name="合成设施", asset_type="well"))
    profile, run, candidate = inputs()
    profile.quality_score = 1
    profile.analysis_readiness = "ready"
    profile.source_hash = CasePipelineService.source_hash(db, db.get(Case, 1))
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = CASE_DICTIONARY_VERSION
    profile.payload = {**profile.payload, "source_hash": profile.source_hash}
    db.add(profile)
    db.flush()
    db.add(MapSnapshotFeature(snapshot_id="map-1", asset_id=1, operational_area_id=1,
                              name="合成设施", asset_type="well", geometry_type="point", status="active", verified=True))
    db.add(run)
    db.flush()
    candidate.confidence = 0.1
    candidate.claim = "另一辖区来源的敏感候选"
    candidate.evidence_refs = ["case:2"]
    db.add(candidate)
    db.commit()
    db.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write"})
    CaseResultService.create_current(db, 1)
    db.commit()
    draft = asyncio.run(ConclusionFactoryService.generate_conclusion(db, 1))
    client = _client(db)
    before = client.get("/api/suggestions/", params={"workflow": "conclusion_review"}).json()
    assert before["total"] == 1
    assert before["suggestions"][0]["target_id"] == draft.id
    db.info["authorized_area_ids"] = (1,)
    after = client.get("/api/suggestions/").json()
    assert after["total"] == after["summary"]["total"] == 0
    assert after["suggestions"] == []
    assert "另一辖区来源的敏感候选" not in json.dumps(after, ensure_ascii=False)


def test_legacy_unscoped_area_risk_not_visible_in_partial_scope():
    db = _session()
    db.add(AreaRiskAssessment(area_name="不可分辖区的旧统计", risk_score=88))
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    payload = _client(db).get("/api/suggestions/").json()
    assert payload["summary"]["total"] == 0
    assert "不可分辖区的旧统计" not in json.dumps(payload, ensure_ascii=False)
