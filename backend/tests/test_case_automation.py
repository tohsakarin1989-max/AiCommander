from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases
from app.config import settings
from app.database import Base, get_db


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

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_required_bonus_evidence(client: TestClient, case_id: int) -> None:
    for title in ["检斤含水单据", "原油入库处理凭证", "人员处理结果单据", "车辆移交单据", "公安受案回执"]:
        evidence_response = client.post(
            f"/api/cases/{case_id}/evidence",
            json={"title": title, "file_path": f"/tmp/{title}.pdf"},
        )
        assert evidence_response.status_code == 200


def test_bonus_assessment_requires_internal_feature_flag(monkeypatch):
    db = _session()
    client = _client(db)
    monkeypatch.setattr(settings, "ENABLE_BONUS_ACCOUNTING", False, raising=False)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": datetime.utcnow().isoformat(),
            "location": "三号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现车辆盗运原油，检斤入库。",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    blocked_get = client.get(f"/api/cases/{case_id}/bonus-assessment")
    blocked_post = client.post(f"/api/cases/{case_id}/bonus-assessment/calculate", json={})
    workbench = client.get(f"/api/cases/{case_id}/automation-workbench")

    assert blocked_get.status_code == 403
    assert blocked_post.status_code == 403
    assert workbench.status_code == 200
    assert workbench.json().get("bonus_assessment") is None


def test_structure_preview_extracts_case_fields_and_material_hints():
    db = _session()
    client = _client(db)

    response = client.post(
        "/api/cases/structure-preview",
        json={
            "text": "2026年5月6日2时30分，巡逻人员在三号井场发现辽A12345车辆盗运被盗原油1.2吨，含水率8%，抓获2人并移交公安，检斤入库。"
        },
    )

    assert response.status_code == 200
    payload = response.json()
    fields = payload["case_fields"]
    assert fields["case_type"] == "涉油盗窃"
    assert fields["location"] == "三号井场"
    assert fields["oil_type"] == "原油"
    assert fields["oil_nature"] == "被盗原油"
    assert fields["oil_volume"] == 1.2
    assert fields["water_cut"] == 8.0
    assert fields["source_type"] == "巡逻发现"
    assert fields["police_reported"] is True
    assert fields["person_handling"] == "移交公安"
    requirement_keys = {item["requirement_key"] for item in payload["suggested_evidence"]}
    assert "weigh_water_document" in requirement_keys
    assert "oil_disposition_document" in requirement_keys


def test_evidence_create_auto_classifies_bonus_material():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(hours=1)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "三号井场",
            "case_type": "涉油盗窃",
            "description": "现场查获车辆盗运原油。",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    response = client.post(
        f"/api/cases/{case_id}/evidence",
        json={
            "title": "检斤含水单据",
            "file_path": "/tmp/case/weigh_water.pdf",
        },
    )

    assert response.status_code == 200
    evidence = response.json()
    assert evidence["evidence_type"] == "document"
    assert evidence["requirement_key"] == "weigh_water_document"
    assert evidence["meta"]["auto_classification"]["label"] == "检斤含水单据"


def test_bonus_assessment_calculates_from_case_data_and_gates_review_by_evidence():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂三号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现车辆盗运原油，抓获2人后移交公安，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=20)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 2.0,
            "water_cut": 10,
            "oil_handling": "检斤入库",
            "person_handling": "移交公安",
            "vehicle_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件一班:张三、李四"],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    client.post(
        f"/api/cases/{case_id}/vehicles",
        json={
            "vehicle_type": "5吨以下机动车",
            "plate_number": "辽A12345",
            "handling_status": "移交公安",
            "transferred_to_police": True,
            "transfer_time": datetime.utcnow().isoformat(),
            "transfer_document_no": "YJ-001",
        },
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "王某", "handling_status": "刑事拘留"},
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "李某", "handling_status": "治安拘留"},
    )

    blocked_response = client.get(f"/api/cases/{case_id}/bonus-assessment")
    assert blocked_response.status_code == 200
    blocked = blocked_response.json()
    assert blocked["material_gate"]["status"] == "blocked_by_materials"
    assert blocked["ready_for_review"] is False
    assert blocked["total_suggested_amount"] == 5250
    blocked_item_status = {item["key"]: item["status"] for item in blocked["bonus_items"]}
    assert blocked_item_status["small_vehicle_reward"] == "calculated"
    assert blocked_item_status["criminal_detention_reward"] == "calculated"
    assert blocked_item_status["other_person_reward"] == "calculated"
    blocked_item_materials = {item["key"]: item["blocked_by"] for item in blocked["bonus_items"]}
    assert blocked_item_materials["small_vehicle_reward"] == ["vehicle_transfer_document"]
    assert blocked_item_materials["criminal_detention_reward"] == ["person_disposition_document"]

    _add_required_bonus_evidence(client, case_id)

    calculated_response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert calculated_response.status_code == 200
    calculated = calculated_response.json()
    assert calculated["material_gate"]["status"] == "ready"
    assert calculated["ready_for_review"] is True
    assert calculated["rules_version"] == "2026_official_workbook"
    assert calculated["rules_configured"] is True
    assert calculated["primary_squad"] == "案件一班"
    assert calculated["bonus_counts"] == {
        "moto": 0,
        "small": 1,
        "big": 0,
        "heavy": 0,
        "boat": 0,
        "tank_sm": 0,
        "tank_lg": 0,
        "people": 2,
        "criminal": 1,
    }
    assert calculated["squad_performance"]["案件一班"] == {
        "vehicle_actual": 1,
        "vehicle_target": 3,
        "vehicle_high": False,
        "person_actual": 2,
        "person_target": 2,
        "person_high": False,
    }
    assert calculated["total_suggested_amount"] == 5250
    assert calculated["distribution"] == [
        {"squad": "案件一班", "count": 2, "amount": 5250},
    ]
    item_status = {item["key"]: item["status"] for item in calculated["bonus_items"]}
    assert item_status["small_vehicle_reward"] == "calculated"
    assert item_status["criminal_detention_reward"] == "calculated"
    assert item_status["other_person_reward"] == "calculated"


def test_bonus_assessment_blocks_whole_case_when_calculation_indicator_is_missing():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=15)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂六号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现一台5吨以下机动车盗运原油，现场抓获1人，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=10)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 8,
            "oil_handling": "检斤入库",
            "vehicle_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "security_officers": ["案件一班:张三"],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    client.post(
        f"/api/cases/{case_id}/vehicles",
        json={
            "vehicle_type": "5吨以下机动车",
            "plate_number": "辽A67890",
            "handling_status": "移交公安",
            "transfer_document_no": "YJ-006",
        },
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "王某"},
    )
    _add_required_bonus_evidence(client, case_id)

    response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["calculation_gate"]["status"] == "blocked_by_data"
    assert payload["calculation_gate"]["missing_items"] == [
        {
            "key": "person_disposition",
            "label": "人员处理类型",
            "detail": "已记录抓获人员，但缺少行政拘留、刑事拘留等处理结果，需补齐后整案测算。",
        }
    ]
    assert payload["total_suggested_amount"] == 0
    assert payload["ready_for_review"] is False
    item_status = {item["key"]: item["status"] for item in payload["bonus_items"]}
    item_amounts = {item["key"]: item["suggested_amount"] for item in payload["bonus_items"]}
    assert item_status["small_vehicle_reward"] == "blocked_by_data"
    assert item_status["other_person_reward"] == "blocked_by_data"
    assert item_amounts["small_vehicle_reward"] == 0
    assert item_amounts["other_person_reward"] == 0


def test_bonus_assessment_does_not_require_person_indicator_without_person_entry():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=15)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂六号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现一台5吨以下机动车盗运原油，现场曾提到抓获线索，车辆移交公安，检斤入库。",
            "involved_persons": {"items": []},
            "report_time": (occurred_time + timedelta(minutes=10)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 8,
            "oil_handling": "检斤入库",
            "vehicle_handling": "移交公安",
            "security_officers": ["案件一班:张三"],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    vehicle_response = client.post(
        f"/api/cases/{case_id}/vehicles",
        json={
            "vehicle_type": "5吨以下机动车",
            "plate_number": "辽A67890",
            "handling_status": "移交公安",
            "transfer_document_no": "YJ-006",
        },
    )
    assert vehicle_response.status_code == 200
    for title in ["检斤含水单据", "原油入库处理凭证", "车辆移交单据"]:
        evidence_response = client.post(
            f"/api/cases/{case_id}/evidence",
            json={"title": title, "file_path": f"/tmp/{title}.pdf"},
        )
        assert evidence_response.status_code == 200

    response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["calculation_gate"]["status"] == "ready"
    assert payload["calculation_gate"]["missing_items"] == []
    assert payload["bonus_counts"]["people"] == 0
    person_material = next(
        item for item in payload["material_checks"]
        if item["requirement_key"] == "person_disposition_document"
    )
    assert person_material["required"] is False
    item_status = {item["key"]: item["status"] for item in payload["bonus_items"]}
    assert item_status["small_vehicle_reward"] == "calculated"
    assert item_status["other_person_reward"] == "not_applicable"


def test_case_create_can_capture_bonus_calculation_indicators_upfront():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=12)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂七号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现一台5吨以下机动车盗运原油，现场抓获1人并刑事拘留，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=8)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 8,
            "oil_handling": "检斤入库",
            "vehicle_handling": "移交公安",
            "person_handling": "刑事拘留",
            "security_officers": ["案件一班:张三"],
            "initial_vehicles": [
                {
                    "vehicle_type": "5吨以下机动车",
                    "plate_number": "辽A77777",
                    "handling_status": "移交公安",
                }
            ],
            "initial_persons": [
                {
                    "name": "王某",
                    "handling_status": "刑事拘留",
                }
            ],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    vehicles = client.get(f"/api/cases/{case_id}/vehicles").json()
    persons = client.get(f"/api/cases/{case_id}/persons").json()
    _add_required_bonus_evidence(client, case_id)
    assessment = client.get(f"/api/cases/{case_id}/bonus-assessment").json()

    assert vehicles[0]["vehicle_type"] == "5吨以下机动车"
    assert persons[0]["handling_status"] == "刑事拘留"
    assert assessment["calculation_gate"]["status"] == "ready"
    assert assessment["total_suggested_amount"] == 3750


def test_official_bonus_uses_largest_remainder_for_cross_squad_distribution():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=20)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂四号井场",
            "case_type": "涉油盗窃",
            "description": "巡逻发现小型机动车盗运原油，抓获2人，其中1人刑事拘留，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=15)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 5,
            "oil_handling": "检斤入库",
            "person_handling": "移交公安",
            "vehicle_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件一班:张三、李四", "龙虎泡保卫班:王五"],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    client.post(
        f"/api/cases/{case_id}/vehicles",
        json={"vehicle_type": "小型机动车", "plate_number": "辽A12345", "transfer_document_no": "YJ-002"},
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "王某", "handling_status": "刑事拘留"},
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "赵某", "handling_status": "行政拘留"},
    )
    _add_required_bonus_evidence(client, case_id)

    response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_suggested_amount"] == 5250
    assert payload["distribution"] == [
        {"squad": "案件一班", "count": 2, "amount": 3500},
        {"squad": "龙虎泡保卫班", "count": 1, "amount": 1750},
    ]


def test_official_bonus_switches_to_high_tier_after_target_is_exceeded():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=10)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂五号井场",
            "case_type": "涉油盗窃",
            "description": "抓获2台小型机动车盗运原油，抓获2人并刑事拘留，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=10)).isoformat(),
            "report_unit": "案件三班",
            "source_type": "巡逻发现",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.4,
            "water_cut": 6,
            "oil_handling": "检斤入库",
            "person_handling": "移交公安",
            "vehicle_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件三班:张三"],
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    for plate in ["辽A10001", "辽A10002"]:
        client.post(
            f"/api/cases/{case_id}/vehicles",
            json={"vehicle_type": "小型机动车", "plate_number": plate, "transfer_document_no": f"YJ-{plate}"},
        )
    for name in ["王某", "赵某"]:
        client.post(
            f"/api/cases/{case_id}/persons",
            json={"name": name, "handling_status": "刑事拘留"},
        )
    _add_required_bonus_evidence(client, case_id)

    response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["squad_performance"]["案件三班"]["vehicle_high"] is True
    assert payload["squad_performance"]["案件三班"]["person_high"] is True
    assert payload["total_suggested_amount"] == 11400
    item_amounts = {item["key"]: item["suggested_amount"] for item in payload["bonus_items"]}
    assert item_amounts["small_vehicle_reward"] == 2400
    assert item_amounts["criminal_detention_reward"] == 9000


def test_bonus_assessment_uses_case_quarter_for_management_targets():
    db = _session()
    client = _client(db)

    previous_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": datetime(2026, 1, 15, 9, 0).isoformat(),
            "location": "一季度井场",
            "case_type": "涉油盗窃",
            "description": "抓获1台小型机动车盗运原油，抓获1人并刑事拘留，车辆移交公安，检斤入库。",
            "report_unit": "案件三班",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 5,
            "oil_handling": "检斤入库",
            "vehicle_handling": "移交公安",
            "person_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件三班:张三"],
        },
    )
    previous_id = previous_response.json()["id"]
    client.post(
        f"/api/cases/{previous_id}/vehicles",
        json={"vehicle_type": "小型机动车", "plate_number": "辽A-Q1", "transfer_document_no": "YJ-Q1"},
    )
    client.post(
        f"/api/cases/{previous_id}/persons",
        json={"name": "王某", "handling_status": "刑事拘留"},
    )
    _add_required_bonus_evidence(client, previous_id)

    current_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": datetime(2026, 4, 6, 9, 30).isoformat(),
            "location": "二季度井场",
            "case_type": "涉油盗窃",
            "description": "抓获1台小型机动车盗运原油，抓获1人并刑事拘留，车辆移交公安，检斤入库。",
            "report_unit": "案件三班",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.0,
            "water_cut": 5,
            "oil_handling": "检斤入库",
            "vehicle_handling": "移交公安",
            "person_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件三班:李四"],
        },
    )
    case_id = current_response.json()["id"]
    client.post(
        f"/api/cases/{case_id}/vehicles",
        json={"vehicle_type": "小型机动车", "plate_number": "辽A-Q2", "transfer_document_no": "YJ-Q2"},
    )
    client.post(
        f"/api/cases/{case_id}/persons",
        json={"name": "赵某", "handling_status": "刑事拘留"},
    )
    _add_required_bonus_evidence(client, case_id)

    response = client.get(f"/api/cases/{case_id}/bonus-assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["squad_performance"]["案件三班"]["vehicle_actual"] == 1
    assert payload["squad_performance"]["案件三班"]["vehicle_high"] is False
    assert payload["squad_performance"]["案件三班"]["person_actual"] == 1
    assert payload["squad_performance"]["案件三班"]["person_high"] is False
    assert payload["total_suggested_amount"] == 3750
    management = payload["management_context"]
    assert management["period"]["quarter_label"] == "2026年Q2"
    assert management["quarter"]["case_count"] == 1
    assert management["quarter"]["vehicle_actual"] == 1
    assert management["quarter"]["vehicle_target"] == 1
    assert management["annual"]["case_count"] == 2
    assert management["annual"]["vehicle_actual"] == 2
    assert management["annual"]["vehicle_target"] == 4
    assert "单案金额进入该周期人工复核" in management["pricing_basis"]


def test_case_automation_workbench_surfaces_456_modules():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow().replace(hour=2, minute=20, second=0, microsecond=0)

    base_response = client.post(
        "/api/cases/",
        json={
            "case_number": "AUTO-456-001",
            "occurred_time": occurred_time.isoformat(),
            "location": "南区12号井场",
            "case_type": "涉油盗窃",
            "description": "凌晨巡逻发现南区12号井场附近便道有小型机动车盗运原油，现场存在监控盲区，使用软管和油泵，抓获2人，车辆移交公安，检斤入库。",
            "report_time": (occurred_time + timedelta(minutes=25)).isoformat(),
            "report_unit": "案件一班",
            "source_type": "巡逻发现",
            "facility_type": "井场",
            "security_level": "低",
            "oil_type": "原油",
            "oil_nature": "被盗原油",
            "oil_volume": 1.5,
            "water_cut": 8,
            "oil_handling": "检斤入库",
            "person_handling": "移交公安",
            "vehicle_handling": "移交公安",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
            "security_officers": ["案件一班:张三、李四"],
        },
    )
    assert base_response.status_code == 200
    base_id = base_response.json()["id"]

    similar_response = client.post(
        "/api/cases/",
        json={
            "case_number": "AUTO-456-002",
            "occurred_time": (occurred_time - timedelta(days=12)).isoformat(),
            "location": "南区13号井场",
            "case_type": "涉油盗窃",
            "description": "凌晨巡逻发现井场附近便道有小型机动车，现场监控盲区，使用软管盗运原油。",
            "report_unit": "案件二班",
            "source_type": "巡逻发现",
            "facility_type": "井场",
            "security_level": "低",
        },
    )
    assert similar_response.status_code == 200

    response = client.get(f"/api/cases/{base_id}/automation-workbench")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "automation_456_v1"
    module_keys = {item["key"] for item in payload["modules"]}
    assert {"conclusion_layering", "experience_card", "gap_closure"}.issubset(module_keys)
    assert payload["conclusion_layering"]["facts"]
    assert payload["conclusion_layering"]["inferences"]
    assert payload["conclusion_layering"]["suggestions"]
    assert payload["experience_card"]["case_id"] == base_id
    assert payload["experience_card"]["reusable_lessons"]
    assert "检斤含水单据" in payload["gap_closure"]["material_gaps"]
    assert any(item["source"] == "material" for item in payload["gap_closure"]["actions"])
    assert payload["ready_for_human_review"] is False
