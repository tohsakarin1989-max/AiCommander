from copy import deepcopy
from collections import Counter
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import case_intelligence, cases
from app.database import Base, get_db
from app.models.case import Case, CaseVehicle
from app.models.jurisdiction import JurisdictionAsset
from app.services.case_intelligence_service import CaseIntelligenceService, _WorkbenchInputs


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_local()
    db.info["authorized_area_ids"] = None  # Explicit full scope for this isolated fixture.
    return db


def _client(db_session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(case_intelligence.router, prefix="/api/case-intelligence")
    app.include_router(cases.router, prefix="/api/cases")

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
    # Explicit background preparation; reading the workbench must not build an index.
    from tests.history_index_helpers import build_history_index
    build_history_index(db)
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
    assert {"凌晨时段", "邻近已登记道路", "油桶装载痕迹", "抽油泵工具"}.issubset(labels)
    assert payload["similar_cases"]["items"][0]["case"]["case_number"] == "INT-002"
    assert payload["scene_analysis"]["reusable_rules"]
    assert payload["area_profiles"]["state"] == "retired"
    assert payload["area_profiles"]["items"] == []
    assert payload["area_profiles"]["profile_count"] is None
    assert payload["prevention_suggestions"]["items"]
    assert "不自动创建执行任务" in payload["prevention_suggestions"]["boundary"]
    assert "不做犯罪预测" in payload["report"]["markdown"]
    section_types = {section["type"] for section in payload["report"]["sections"]}
    assert {"facts", "patterns", "gaps", "prevention_reference"}.issubset(section_types)
    assert payload["context_pack"]["scope"] == payload["scope"]
    assert payload["context_pack"]["selected_case"] == payload["selected_case"]


def _without_generation_times(value):
    if isinstance(value, dict):
        return {key: _without_generation_times(item) for key, item in value.items()
                if key not in {"generated_at", "start_date"}}
    if isinstance(value, list):
        return [_without_generation_times(item) for item in value]
    return value


@pytest.mark.parametrize("days,limit,radius,similar_count,area_count", [
    (365, 8, 1.5, 1, 1),
    (60, 5, 2.0, 3, 2),
])
def test_workbench_reuses_only_equal_inputs_without_changing_analysis(
    monkeypatch, days, limit, radius, similar_count, area_count,
):
    db = _session()
    case = _seed(db)
    calls = Counter()

    def observe(name):
        original = getattr(CaseIntelligenceService, name)

        def spy(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(CaseIntelligenceService, name, staticmethod(spy))

    for name in ("find_similar_cases", "analyze_spatiotemporal_patterns", "build_area_risk_profiles"):
        observe(name)

    reused = CaseIntelligenceService.build_workbench(
        db, case.id, days=days, limit=limit, radius_km=radius,
    )
    assert calls == {
        "find_similar_cases": similar_count,
        "analyze_spatiotemporal_patterns": 1,
        "build_area_risk_profiles": area_count,
    }

    # Execute the same calculations afresh, as the previous nested call tree did.
    # Window, display count and radius differences must survive the optimization.
    def uncached(self, name, **parameters):
        method = getattr(CaseIntelligenceService, name)
        nested = {"_inputs": self} if name in self._NESTED else {}
        return method(self.db, **parameters, **nested)

    monkeypatch.setattr(_WorkbenchInputs, "call", uncached)
    calls.clear()
    uncached_result = CaseIntelligenceService.build_workbench(
        db, case.id, days=days, limit=limit, radius_km=radius,
    )
    assert calls == {
        "find_similar_cases": 8,
        "analyze_spatiotemporal_patterns": 4,
        "build_area_risk_profiles": 2,
    }
    assert _without_generation_times(reused) == _without_generation_times(uncached_result)


def test_workbench_reuse_does_not_survive_the_call_or_authorization_change():
    db = _session()
    case = _seed(db)
    first = CaseIntelligenceService.build_workbench(db, case.id)
    case.location = "更新后的合成地点"
    db.commit()
    second = CaseIntelligenceService.build_workbench(db, case.id)
    assert first["selected_case"]["location"] != second["selected_case"]["location"]
    assert second["context_pack"]["selected_case"]["location"] == "更新后的合成地点"

    db.info["authorized_area_ids"] = ()
    with pytest.raises(ValueError, match="case_not_found"):
        CaseIntelligenceService.build_workbench(db, case.id)


def test_global_report_does_not_add_its_area_notes_to_shared_statistics():
    db = _session()
    _seed(db)
    expected = CaseIntelligenceService.analyze_spatiotemporal_patterns(db, days=60)
    workbench = CaseIntelligenceService.build_workbench(db, days=60)
    assert workbench["spatiotemporal"] == expected
    patterns = next(section["items"] for section in workbench["report"]["sections"]
                    if section["type"] == "patterns")
    assert not any(item.startswith("重点关注区域：") for item in patterns)
    gaps = next(section["items"] for section in workbench["report"]["sections"] if section["type"] == "gaps")
    assert any("旧区域风险评分已停用" in item for item in gaps)
    assert not any(item.startswith("重点关注区域：") for item in expected["insights"])


def test_context_compatibility_route_formats_workbench_once(monkeypatch):
    db = _session()
    client = _client(db)
    base = _seed(db)
    original = CaseIntelligenceService._build_llm_context_from_workbench
    formatted = []

    def observe(workbench):
        formatted.append(workbench["scope"])
        return original(workbench)

    monkeypatch.setattr(CaseIntelligenceService, "_build_llm_context_from_workbench", observe)
    parameters = {"case_id": base.id, "days": 60, "limit": 5}
    response = client.get("/api/case-intelligence/workbench", params=parameters)
    assert response.status_code == 200
    assert len(formatted) == 1
    formatted.clear()
    compatibility = client.get("/api/case-intelligence/llm-context", params=parameters)
    assert compatibility.status_code == 200
    assert len(formatted) == 1
    assert _without_generation_times(response.json()["context_pack"]) == _without_generation_times(compatibility.json())


def test_prevention_suggestions_accept_legacy_string_quality_gaps():
    db = _session()
    case = _add_case(
        db,
        "INT-LEGACY-GAPS",
        days_ago=1,
        hour=2,
        latitude=39.9,
        longitude=116.4,
        description="脱敏的旧版案件质量字段兼容样本。",
    )
    case.quality_issues = {
        "missing_required": ["坐标信息", {"label": "报送单位"}],
    }
    db.commit()

    payload = CaseIntelligenceService.build_prevention_suggestions(
        db,
        case_id=case.id,
        days=30,
    )
    completion = next(item for item in payload["items"] if item["id"] == "data_completion")

    assert completion["evidence"] == ["坐标信息", "报送单位"]


def test_similarity_uses_conditions_not_same_vehicle_or_person_as_core_anchor():
    db = _session()
    base = _seed(db)

    similar = CaseIntelligenceService.find_similar_cases(db, base.id, days=60, limit=5)

    assert similar["items"]
    top = similar["items"][0]
    assert top["case"]["case_number"] == "INT-002"
    assert top["reasons"] and top["versions"] and top["evidence_refs"]
    assert top["components"] == {} and top["distance_km"] is None
    assert top["duplicate_warnings"] == []
    assert "检索支持度不是概率" in similar["principle"]
    assert similar["coverage"]["complete"] is True


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
    assert profiles.status_code == 404


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


@pytest.mark.parametrize("stored_card", [False, True])
@pytest.mark.parametrize("path", [
    "/api/case-intelligence/workbench?case_id={case_id}",
    "/api/case-intelligence/llm-context?case_id={case_id}",
    "/api/case-intelligence/report?case_id={case_id}",
    "/api/case-intelligence/prevention-suggestions?case_id={case_id}",
    "/api/case-intelligence/cases/{case_id}/experience-card",
    "/api/cases/{case_id}/automation-workbench",
    "/api/cases/{case_id}/quality",
    "/api/cases/{case_id}/feature-profile",
])
def test_case_analysis_reads_preserve_quality_and_confirmed_experience(path, stored_card):
    db = _session()
    client = _client(db)
    case = _seed(db)
    if stored_card:
        case.features = {
            "intelligence": {
                "experience_card": {
                    "manual_review_status": "confirmed",
                    "generated_at": "2026-01-01T00:00:00",
                    "reviewer": "合成人工复核员",
                    "summary": "已经人工确认的固定内容",
                },
            },
        }
        db.commit()
    fields = ("features", "quality_issues", "quality_score", "updated_at")
    before = {field: deepcopy(getattr(case, field)) for field in fields}

    response = client.get(path.format(case_id=case.id))

    assert response.status_code == 200
    db.refresh(case)
    assert {field: getattr(case, field) for field in fields} == before
