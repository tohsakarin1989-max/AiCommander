from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import case_intelligence
from app.database import Base, get_db
from app.models.case import Case, CaseVehicle
from app.models.jurisdiction import JurisdictionAsset
from app.services.assistant_service import AssistantService
from app.services.case_intelligence_service import CaseIntelligenceService


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

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _add_case(
    db: Session,
    number: str,
    *,
    days_ago: int,
    hour: int,
    latitude: float,
    longitude: float,
    description: str,
    vehicle_type: str = "皮卡",
    source_type: str = "巡逻发现",
) -> Case:
    occurred = (datetime.utcnow() - timedelta(days=days_ago)).replace(
        hour=hour,
        minute=10,
        second=0,
        microsecond=0,
    )
    case = Case(
        case_number=number,
        occurred_time=occurred,
        location="南区12号井附近",
        latitude=latitude,
        longitude=longitude,
        case_type="涉油盗窃",
        description=description,
        facility_type="井口",
        oil_type="原油",
        oil_nature="被盗原油",
        oil_volume=1.1,
        source_type=source_type,
        report_time=occurred + timedelta(minutes=30),
        report_unit="南区保卫班",
        oil_handling="检斤入库",
        vehicle_handling="扣押停放",
        status="closed",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.add(
        CaseVehicle(
            case_id=case.id,
            vehicle_type=vehicle_type,
            plate_number=f"辽A{case.id:05d}",
            handling_status="扣押停放",
        )
    )
    db.commit()
    db.refresh(case)
    return case


def _add_asset(
    db: Session,
    name: str,
    asset_type: str,
    latitude: float,
    longitude: float,
    *,
    verified: bool = True,
) -> JurisdictionAsset:
    asset = JurisdictionAsset(
        name=name,
        asset_type=asset_type,
        geometry_type="point",
        latitude=latitude,
        longitude=longitude,
        status="active",
        source="test",
        risk_level=2,
        verified=verified,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _seed(db: Session) -> Case:
    base = _add_case(
        db,
        "INT-001",
        days_ago=2,
        hour=2,
        latitude=39.9000,
        longitude=116.4000,
        description="凌晨发现皮卡车靠近偏远井场，车内有油桶、软管和抽油泵，现场无照明。",
    )
    _add_case(
        db,
        "INT-002",
        days_ago=8,
        hour=3,
        latitude=39.9010,
        longitude=116.4010,
        description="夜间厢货车停在井场便道旁，发现油桶和软管，周边监控盲区。",
        vehicle_type="厢货",
    )
    _add_case(
        db,
        "INT-003",
        days_ago=15,
        hour=14,
        latitude=40.2000,
        longitude=116.9000,
        description="白天站库周边普通纠纷，无明显盗油工具。",
        vehicle_type="轿车",
        source_type="其他",
    )
    _add_asset(db, "南区12号井", "well", 39.9005, 116.4005)
    _add_asset(db, "南区便道", "road", 39.9007, 116.4001)
    _add_asset(db, "东湾村", "village", 39.9100, 116.4070)
    _add_asset(db, "远端监控点", "camera", 39.9300, 116.4300)
    return base


def test_case_intelligence_workbench_builds_full_explainable_chain():
    db = _session()
    client = _client(db)
    base = _seed(db)

    response = client.get(
        "/api/case-intelligence/workbench",
        params={"case_id": base.id, "days": 60, "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_case"]["case_number"] == "INT-001"
    assert payload["feature_tags"]["tags"]
    labels = {tag["label"] for tag in payload["feature_tags"]["tags"]}
    assert {"凌晨时段", "道路通达", "油桶装载痕迹", "抽油泵工具"}.issubset(labels)
    assert payload["similar_cases"]["items"][0]["case"]["case_number"] == "INT-002"
    assert payload["scene_analysis"]["reusable_rules"]
    assert payload["area_profiles"]["items"]
    assert payload["prevention_suggestions"]["items"]
    assert "不自动派发巡逻任务" in payload["prevention_suggestions"]["boundary"]
    assert "不做犯罪预测" in payload["report"]["markdown"]
    section_types = {section["type"] for section in payload["report"]["sections"]}
    assert {"facts", "patterns", "gaps", "prevention_reference"}.issubset(section_types)


def test_similarity_uses_conditions_not_same_vehicle_or_person_as_core_anchor():
    db = _session()
    base = _seed(db)

    similar = CaseIntelligenceService.find_similar_cases(db, base.id, days=60, limit=5)

    assert similar["items"]
    top = similar["items"][0]
    assert top["case"]["case_number"] == "INT-002"
    assert any("空间环境" in reason or "车辆类型" in reason or "工具" in reason for reason in top["reasons"])
    assert top["duplicate_warnings"] == []
    assert "不把同人同车重复出现作为核心依据" in similar["principle"]


def test_manual_tag_overrides_are_persisted_in_case_features():
    db = _session()
    client = _client(db)
    base = _seed(db)

    response = client.put(
        f"/api/case-intelligence/cases/{base.id}/tag-overrides",
        json={
            "added": [
                {
                    "key": "manual_boundary_area",
                    "label": "边界区域",
                    "category": "space",
                    "confidence": 1,
                    "basis": ["人工复核确认"],
                }
            ],
            "removed_keys": ["defense_unknown_tech"],
        },
    )

    assert response.status_code == 200
    labels = {tag["label"] for tag in response.json()["tags"]}
    assert "边界区域" in labels
    refreshed = db.query(Case).filter(Case.id == base.id).first()
    assert refreshed.features["intelligence"]["tag_overrides"]["removed_keys"] == ["defense_unknown_tech"]


def test_global_spatiotemporal_and_area_profiles_work_without_selected_case():
    db = _session()
    client = _client(db)
    _seed(db)

    workbench = client.get("/api/case-intelligence/workbench", params={"days": 60})
    profiles = client.get("/api/case-intelligence/area-profiles", params={"days": 60})

    assert workbench.status_code == 200
    assert workbench.json()["scope"]["mode"] == "global"
    assert workbench.json()["spatiotemporal"]["case_count"] == 3
    assert profiles.status_code == 200
    assert profiles.json()["items"][0]["case_count"] >= 1


def test_llm_context_pack_separates_facts_inferences_suggestions_and_gaps():
    db = _session()
    client = _client(db)
    base = _seed(db)

    response = client.get(
        "/api/case-intelligence/llm-context",
        params={"case_id": base.id, "days": 60, "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_case"]["case_number"] == "INT-001"
    assert any("案件编号" in item for item in payload["facts"])
    assert payload["pattern_inferences"]
    assert payload["prevention_references"]
    assert payload["evidence_index"]
    assert "不得把防控参考写成已执行任务" in "；".join(payload["system_boundary"])
    assert "事实依据" in payload["llm_prompt"]


def test_assistant_context_uses_case_intelligence_workbench():
    db = _session()
    base = _seed(db)

    context = AssistantService._gather_context(db, f"请分析 {base.case_number} 的相似条件")

    intelligence = context["case_intelligence"]
    assert intelligence["selected_case"]["case_number"] == base.case_number
    assert intelligence["top_tags"]
    assert intelligence["similar_cases"][0]["case_number"] == "INT-002"
    assert intelligence["similar_cases"][0]["score"] > 0
    assert intelligence["suggestions"][0]["basis"]
    assert "不自动派发巡逻任务" in intelligence["boundary"]
