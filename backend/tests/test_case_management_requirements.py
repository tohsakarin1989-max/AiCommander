from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases, patrols
from app.database import Base, get_db
from app.models.case import CasePerson, CaseVehicle
from app.services.preprocess_service import CasePreprocessService


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
    app.include_router(patrols.router, prefix="/api/patrols")

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_case_quality_flags_required_management_fields():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "测试井场",
            "case_type": "涉油盗窃",
            "description": "现场发现车辆转运原油，抓获人员后待移交公安。",
        },
    )
    assert response.status_code == 200
    case_id = response.json()["id"]

    quality_response = client.get(f"/api/cases/{case_id}/quality")

    assert quality_response.status_code == 200
    quality = quality_response.json()
    missing_fields = {item["field"] for item in quality["missing_required"]}
    assert {"report_time", "report_unit", "source_type"}.issubset(missing_fields)
    assert quality["facts"]["has_vehicle_signal"] is True
    assert quality["facts"]["has_person_signal"] is True
    assert quality["facts"]["has_oil_signal"] is True


def test_case_update_accepts_bonus_indicator_drafts():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    created = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "测试井场",
            "case_type": "涉油盗窃",
            "description": "现场抓获1人，查扣皮卡车1台。",
        },
    )
    assert created.status_code == 200
    case_id = created.json()["id"]

    updated = client.put(
        f"/api/cases/{case_id}",
        json={
            "initial_vehicles": [
                {"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}
            ],
            "initial_persons": [
                {"name": "张某", "handling_status": "行政拘留"}
            ],
        },
    )

    assert updated.status_code == 200
    vehicles = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).all()
    persons = db.query(CasePerson).filter(CasePerson.case_id == case_id).all()
    assert [vehicle.vehicle_type for vehicle in vehicles] == ["5吨以下机动车"]
    assert [person.handling_status for person in persons] == ["行政拘留"]


def test_case_update_refreshes_existing_bonus_indicator_drafts_without_duplicates():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    created = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "测试井场",
            "case_type": "涉油盗窃",
            "description": "现场查扣车辆。",
            "initial_vehicles": [
                {"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}
            ],
        },
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    vehicle = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).one()

    updated = client.put(
        f"/api/cases/{case_id}",
        json={
            "initial_vehicles": [
                {"id": vehicle.id, "vehicle_type": "5吨以上机动车", "plate_number": "黑E12345"}
            ],
        },
    )

    assert updated.status_code == 200
    vehicles = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).all()
    assert len(vehicles) == 1
    assert vehicles[0].vehicle_type == "5吨以上机动车"


def test_case_update_can_clear_bonus_indicator_drafts_with_empty_lists():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    created = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "测试井场",
            "case_type": "涉油盗窃",
            "description": "现场查扣车辆并抓获人员。",
            "initial_vehicles": [
                {"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}
            ],
            "initial_persons": [
                {"name": "张某", "handling_status": "行政拘留"}
            ],
        },
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    assert db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).count() == 1
    assert db.query(CasePerson).filter(CasePerson.case_id == case_id).count() == 1

    updated = client.put(
        f"/api/cases/{case_id}",
        json={
            "initial_vehicles": [],
            "initial_persons": [],
        },
    )

    assert updated.status_code == 200
    assert db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).count() == 0
    assert db.query(CasePerson).filter(CasePerson.case_id == case_id).count() == 0


def test_case_update_can_clear_existing_bonus_indicator_fields():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    created = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "测试井场",
            "case_type": "涉油盗窃",
            "description": "现场查扣车辆。",
            "initial_vehicles": [
                {"vehicle_type": "5吨以下机动车", "plate_number": "黑E12345"}
            ],
        },
    )
    assert created.status_code == 200
    case_id = created.json()["id"]
    vehicle = db.query(CaseVehicle).filter(CaseVehicle.case_id == case_id).one()

    updated = client.put(
        f"/api/cases/{case_id}",
        json={
            "initial_vehicles": [
                {"id": vehicle.id, "vehicle_type": None, "plate_number": "黑E12345"}
            ],
        },
    )

    assert updated.status_code == 200
    db.refresh(vehicle)
    assert vehicle.vehicle_type is None


def test_case_profile_uses_structured_vehicle_person_and_evidence():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=30)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "采油一厂某井场",
            "latitude": 39.9,
            "longitude": 116.4,
            "case_type": "涉油盗窃",
            "description": "群众举报有人驾驶白色皮卡盗运原油。",
            "report_time": (occurred_time + timedelta(minutes=20)).isoformat(),
            "report_unit": "一号保卫班",
            "source_type": "群众举报",
            "oil_nature": "被盗原油",
            "oil_volume": 1.2,
            "oil_handling": "检斤入库",
            "police_reported": True,
            "case_filed": True,
            "police_officer": "张警官",
            "police_phone": "13800000000",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    vehicle_response = client.post(
        f"/api/cases/{case_id}/vehicles",
        json={
            "vehicle_type": "皮卡",
            "color": "白色",
            "plate_number": "辽A12345",
            "handling_status": "扣押停放",
        },
    )
    assert vehicle_response.status_code == 200

    person_response = client.post(
        f"/api/cases/{case_id}/persons",
        json={
            "name": "王某",
            "id_number": "210000199001010000",
            "home_address": "测试住址",
            "handling_status": "移交公安",
        },
    )
    assert person_response.status_code == 200

    evidence_response = client.post(
        f"/api/cases/{case_id}/evidence",
        json={
            "evidence_type": "photo",
            "title": "车辆正面照片",
            "requirement_key": "vehicle_front",
        },
    )
    assert evidence_response.status_code == 200

    profile_response = client.get(f"/api/cases/{case_id}/feature-profile")

    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["management"]["source_type"] == "群众举报"
    assert profile["vehicles"][0]["plate_number"] == "辽A12345"
    assert profile["actors"]["persons"][0]["name"] == "王某"
    assert profile["quality"]["facts"]["vehicle_count"] == 1
    assert profile["analysis_readiness"]["spacetime"]["status"] == "ready"
    assert profile["analysis_readiness"]["gang"]["status"] == "ready"
    assert profile["analysis_readiness"]["patrol"]["status"] == "ready"
    assert profile["analysis_readiness"]["roundtable"]["status"] in {"ready", "partial"}


def test_case_tip_ledger_can_attach_to_case():
    db = _session()
    client = _client(db)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": datetime.utcnow().isoformat(),
            "location": "测试地点",
            "case_type": "线索核查",
            "description": "用于举报线索台账测试。",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    create_response = client.post(
        "/api/cases/tips",
        json={
            "case_id": case_id,
            "reporter_name": "举报人甲",
            "reported_at": datetime.utcnow().isoformat(),
            "location": "测试地点",
            "content": "发现可疑车辆。",
            "source_type": "群众举报",
            "verification_status": "verified",
        },
    )
    assert create_response.status_code == 200

    list_response = client.get("/api/cases/tips", params={"case_id": case_id})

    assert list_response.status_code == 200
    tips = list_response.json()
    assert len(tips) == 1
    assert tips[0]["verification_status"] == "verified"


def test_preprocess_has_deterministic_fallback_without_llm():
    db = _session()
    client = _client(db)
    occurred_time = datetime.utcnow() - timedelta(minutes=40)

    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "二号井场",
            "latitude": 39.91,
            "longitude": 116.41,
            "case_type": "涉油盗窃",
            "description": "巡逻发现蓝色厢货车转运落地原油，现场留有油迹。",
            "report_time": (occurred_time + timedelta(minutes=25)).isoformat(),
            "report_unit": "二号保卫班",
            "source_type": "巡逻发现",
            "oil_nature": "落地原油",
            "oil_volume": 0.8,
            "oil_handling": "检斤入库",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    result = CasePreprocessService.preprocess_case(db, case_id)

    assert result is not None
    assert result["preprocess_mode"] == "deterministic_fallback"
    assert result["management"]["report_quality_score"] > 0
    assert result["analysis_readiness"]["spacetime"] == "ready"
    assert result["analysis_readiness"]["area_profile"] == "ready"
    assert "gang" not in result["analysis_readiness"]
    assert result["facts"]["oil"]["oil_nature"] == "落地原油"
    assert result["scene_conditions"]["monitoring_status"] == "技防/照明/监控情况待核实"
    assert all(item["boundary"] == "仅供人工研判和防控参考" for item in result["recommendations"])
    refreshed = client.get(f"/api/cases/{case_id}").json()
    assert refreshed["features"]["basic"]["case_type"] == "涉油盗窃"
    assert refreshed["features"]["oil"]["facts"]["oil_nature"] == "落地原油"
    assert refreshed["features"]["facts"]["oil"]["oil_nature"] == "落地原油"


def test_preprocess_overwrites_existing_features_with_new_top_level_keys():
    db = _session()
    occurred_time = datetime.utcnow() - timedelta(minutes=20)
    client = _client(db)
    case_response = client.post(
        "/api/cases/",
        json={
            "occurred_time": occurred_time.isoformat(),
            "location": "旧画像测试井场",
            "case_type": "涉油盗窃",
            "description": "用于测试已有 features 被重新写入。",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["id"]

    stored = db.query(app.models.Case).filter(app.models.Case.id == case_id).first()
    assert stored is not None
    stored.features = {"legacy": True}
    db.commit()
    db.refresh(stored)

    CasePreprocessService._write_features(
        db,
        stored,
        {"preprocess_mode": "llm", "confidence": 0.88},
    )

    refreshed = client.get(f"/api/cases/{case_id}").json()
    assert refreshed["features"]["legacy"] is True
    assert refreshed["features"]["preprocess_mode"] == "llm"
    assert refreshed["features"]["confidence"] == 0.88


def test_batch_preprocess_all_cases_writes_features_and_jobs():
    db = _session()
    client = _client(db)

    for idx in range(2):
        response = client.post(
            "/api/cases/",
            json={
                "occurred_time": datetime.utcnow().isoformat(),
                "location": f"测试井场{idx}",
                "latitude": 39.9 + idx * 0.01,
                "longitude": 116.4 + idx * 0.01,
                "case_type": "涉油盗窃",
                "description": f"测试案件{idx}，发现车辆转运原油，现场留有油迹。",
                "report_unit": "测试保卫班",
                "source_type": "巡逻发现",
                "oil_nature": "落地原油",
            },
        )
        assert response.status_code == 200

    batch_response = client.post(
        "/api/cases/preprocess/batch",
        json={"only_missing": False, "use_llm": False},
    )

    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload["total_candidates"] == 2
    assert payload["processed"] == 2
    assert payload["success"] == 2
    assert payload["failed"] == 0
    assert payload["llm_enabled"] is False
    assert payload["mode_counts"]["deterministic_fallback"] == 2

    cases_response = client.get("/api/cases/", params={"limit": 10})
    assert cases_response.status_code == 200
    assert all(case["features"]["basic"]["case_type"] == "涉油盗窃" for case in cases_response.json())

    status_response = client.get("/api/cases/preprocess/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["success"] == 2
    assert status["failed"] == 0

    skipped_response = client.post("/api/cases/preprocess/batch", json={"only_missing": True})

    assert skipped_response.status_code == 200
    skipped = skipped_response.json()
    assert skipped["processed"] == 0
    assert skipped["skipped"] == 2


def test_case_driven_patrol_plan_uses_quality_and_case_fields():
    db = _session()
    client = _client(db)
    base_time = datetime.utcnow() - timedelta(days=2)

    create_payloads = [
        {
            "occurred_time": base_time.replace(hour=23).isoformat(),
            "location": "三号井场东侧",
            "latitude": 39.92,
            "longitude": 116.42,
            "case_type": "涉油盗窃",
            "description": "群众举报夜间有车辆盗运被盗原油。",
            "report_time": (base_time.replace(hour=23) + timedelta(minutes=30)).isoformat(),
            "report_unit": "三号保卫班",
            "source_type": "群众举报",
            "oil_nature": "被盗原油",
            "oil_volume": 1.5,
            "oil_handling": "检斤入库",
            "vehicle_info": {"plate_number": "辽B12345", "vehicle_type": "厢货"},
            "vehicle_handling": "扣押停放",
        },
        {
            "occurred_time": (base_time + timedelta(days=1)).replace(hour=1).isoformat(),
            "location": "三号井场东侧",
            "latitude": 39.921,
            "longitude": 116.421,
            "case_type": "涉油盗窃",
            "description": "技防预警发现疑似车辆靠近井场。",
            "report_time": ((base_time + timedelta(days=1)).replace(hour=1) + timedelta(minutes=20)).isoformat(),
            "report_unit": "三号保卫班",
            "source_type": "技防预警",
            "oil_nature": "被盗原油",
            "oil_volume": 0.6,
            "oil_handling": "暂存",
        },
    ]

    for payload in create_payloads:
        response = client.post("/api/cases/", json=payload)
        assert response.status_code == 200

    response = client.get("/api/patrols/case-driven-plan", params={"days": 30})

    assert response.status_code == 200
    plan = response.json()
    assert plan["area_count"] >= 1
    top_area = plan["areas"][0]
    assert top_area["area_name"] == "三号井场东侧"
    assert top_area["case_count"] == 2
    assert "被盗原油" in top_area["oil_natures"]
    assert top_area["recommended_windows"]
    assert top_area["patrol_focus"]
    assert plan["data_quality"]["missing_geo_case_count"] == 0
