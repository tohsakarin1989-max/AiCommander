import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import situation
from app.database import Base, get_db
from app.models.case import Case, CasePerson
from app.models.jurisdiction import JurisdictionAsset
from app.services.situation_analysis_service import (
    SituationAnalysisError,
    SituationAnalysisService,
)


AS_OF = datetime(2026, 9, 10, 12, 0)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db: Session) -> TestClient:
    api = FastAPI()
    api.include_router(situation.router, prefix="/api/situation")

    def override_get_db():
        yield db

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api)


def _case(
    db: Session,
    number: str,
    occurred_at: datetime,
    *,
    latitude: float | None = 46.6,
    longitude: float | None = 125.1,
    location: str = "北区井场",
    case_type: str = "涉油盗窃",
    modus: str = "破坏阀门",
) -> Case:
    item = Case(
        case_number=number,
        occurred_time=occurred_at,
        latitude=latitude,
        longitude=longitude,
        location=location,
        case_type=case_type,
        facility_type="输油管线",
        modus_operandi=modus,
        status="processing",
    )
    db.add(item)
    db.flush()
    return item


def _seed_situation(db: Session) -> tuple[list[Case], JurisdictionAsset]:
    previous = _case(
        db,
        "SIT-PREV-001",
        datetime(2026, 8, 25, 2, 0),
        latitude=46.601,
        longitude=125.101,
    )
    current = [
        _case(db, "SIT-CUR-001", datetime(2026, 9, 7, 1, 0)),
        _case(db, "SIT-CUR-002", datetime(2026, 9, 8, 2, 0), latitude=46.602, longitude=125.102),
        _case(db, "SIT-CUR-003", datetime(2026, 9, 9, 2, 30), latitude=46.603, longitude=125.103),
    ]
    _case(
        db,
        "SIT-OTHER-001",
        datetime(2026, 9, 8, 8, 0),
        latitude=47.2,
        longitude=126.2,
        location="南区站场",
        case_type="油品运输",
        modus="异常运输",
    )
    _case(
        db,
        "SIT-FUTURE-001",
        datetime(2026, 9, 11, 8, 0),
        location="北区井场",
    )
    well = JurisdictionAsset(
        name="北区高产井-01",
        asset_type="well",
        latitude=46.604,
        longitude=125.104,
        status="active",
        verified=True,
        tags=["高产井"],
        attributes={"日产量": 18.5, "作业区": "北区"},
    )
    db.add_all(
        [
            well,
            JurisdictionAsset(
                name="北区待核验井-02",
                asset_type="well",
                latitude=46.61,
                longitude=125.11,
                status="active",
                verified=False,
                attributes={"日产量": 8.0, "作业区": "北区"},
            ),
        ]
    )
    db.flush()
    db.add(
        CasePerson(
            case_id=current[0].id,
            name="不应进入态势结果的人名",
            phone="13800000000",
            id_number="230000000000000000",
        )
    )
    db.commit()
    return [previous, *current], well


def test_situation_analysis_turns_new_cases_into_hotspots_well_attention_and_three_actions():
    db = _session()
    cases, well = _seed_situation(db)
    before = {
        "cases": db.query(Case).count(),
        "wells": db.query(JurisdictionAsset).count(),
    }

    first = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
        hotspot_radius_km=1.5,
        well_radius_km=5,
        min_cases=2,
    )
    second = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
        hotspot_radius_km=1.5,
        well_radius_km=5,
        min_cases=2,
    )

    assert first["summary"]["current_case_count"] == 3
    assert first["summary"]["previous_case_count"] == 1
    assert first["summary"]["case_delta"] == 2
    assert first["summary"]["change_direction"] == "rising"
    assert first["summary"]["geocoded_case_count"] == 3
    assert first["summary"]["data_readiness_percent"] == 100
    assert first["hotspots"][0]["case_count"] == 3
    assert first["hotspots"][0]["previous_case_count"] == 1
    assert first["hotspots"][0]["case_delta"] == 2
    assert first["well_attention"][0]["asset_id"] == well.id
    assert first["well_attention"][0]["is_high_production"] is True
    assert first["well_attention"][0]["nearby_case_count"] == 3
    assert "不能证明" in first["well_attention"][0]["boundary"]
    assert 1 <= len(first["priorities"]) <= 3
    assert all(item["evidence_refs"] for item in first["priorities"])
    assert [item["rank"] for item in first["priorities"]] == list(
        range(1, len(first["priorities"]) + 1)
    )
    assert first["source_snapshot"]["data_version"] == second["source_snapshot"]["data_version"]
    assert all(item["status"] == "completed" for item in first["pipeline"])
    assert "本期新增3起" in first["brief"]["headline"]
    assert "不自动调度" in first["boundary"]["statements"][-1]
    assert before == {
        "cases": db.query(Case).count(),
        "wells": db.query(JurisdictionAsset).count(),
    }

    serialized = json.dumps(first, ensure_ascii=False)
    for sensitive in ("不应进入态势结果的人名", "13800000000", "230000000000000000"):
        assert sensitive not in serialized
    for prohibited in ("即将作案", "必然发生", "自动派遣", "自动调度巡逻"):
        assert prohibited not in serialized


def test_situation_analysis_respects_time_and_area_boundaries_and_handles_no_data():
    db = _session()
    _seed_situation(db)

    north = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
    )
    missing = SituationAnalysisService.build_overview(
        db,
        window_days=7,
        as_of=AS_OF,
        area_keyword="不存在的区域",
    )

    assert north["summary"]["current_case_count"] == 3
    assert "SIT-OTHER-001" not in {item["case_number"] for item in north["case_points"]}
    assert "SIT-FUTURE-001" not in {item["case_number"] for item in north["case_points"]}
    assert missing["summary"]["current_case_count"] == 0
    assert missing["summary"]["analysis_status"] == "no_current_data"
    assert missing["priorities"] == []
    assert missing["hotspots"] == []
    assert missing["well_attention"] == []
    assert "当前窗口没有匹配案件" in missing["brief"]["headline"]


def test_situation_analysis_exposes_pattern_shifts_without_calling_them_predictions():
    db = _session()
    _seed_situation(db)

    payload = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
    )

    modus = payload["pattern_shifts"]["modus_operandi"][0]
    assert modus["name"] == "破坏阀门"
    assert modus["current_count"] == 3
    assert modus["previous_count"] == 1
    assert modus["delta"] == 2
    assert payload["pattern_shifts"]["peak_hours"][0]["hour"] == 2
    assert all("prediction" not in item for item in payload)
    assert payload["boundary"]["historical_association_only"] is True


def test_situation_analysis_does_not_call_a_declining_hotspot_new():
    db = _session()
    for index in range(3):
        _case(
            db,
            f"SIT-PREV-DOWN-{index}",
            datetime(2026, 8, 24 + index, 2, 0),
            latitude=46.6 + index * 0.001,
            longitude=125.1 + index * 0.001,
        )
    for index in range(2):
        _case(
            db,
            f"SIT-CUR-DOWN-{index}",
            datetime(2026, 9, 8 + index, 2, 0),
            latitude=46.6 + index * 0.001,
            longitude=125.1 + index * 0.001,
        )
    db.commit()

    payload = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
        min_cases=2,
    )

    hotspot_priority = next(
        item for item in payload["priorities"] if item["type"] == "hotspot_change"
    )
    assert hotspot_priority["title"].endswith("保持历史聚集")
    assert "新增聚集" not in hotspot_priority["title"]


def test_situation_analysis_version_changes_when_relevant_source_changes():
    db = _session()
    cases, _ = _seed_situation(db)
    first = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
    )

    cases[-1].modus_operandi = "夜间破坏阀门"
    db.commit()
    changed = SituationAnalysisService.build_overview(
        db,
        window_days=14,
        as_of=AS_OF,
        area_keyword="北区",
    )

    assert changed["source_snapshot"]["data_version"] != first["source_snapshot"]["data_version"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"window_days": 6}, "invalid_window_days"),
        ({"window_days": 91}, "invalid_window_days"),
        ({"hotspot_radius_km": 0.1}, "invalid_hotspot_radius"),
        ({"well_radius_km": 30}, "invalid_well_radius"),
        ({"min_cases": 1}, "invalid_min_cases"),
        ({"area_keyword": "北" * 51}, "invalid_area_keyword"),
    ],
)
def test_situation_analysis_rejects_unsafe_scope(kwargs, message):
    db = _session()

    with pytest.raises(SituationAnalysisError, match=message):
        SituationAnalysisService.build_overview(db, as_of=AS_OF, **kwargs)


def test_situation_api_is_get_only_and_validates_scope():
    db = _session()
    _seed_situation(db)
    client = _client(db)

    response = client.get(
        "/api/situation/overview",
        params={
            "window_days": 14,
            "as_of": AS_OF.isoformat(),
            "area_keyword": "北区",
            "hotspot_radius_km": 1.5,
            "well_radius_km": 5,
            "min_cases": 2,
        },
    )
    invalid = client.get("/api/situation/overview?window_days=100")
    post = client.post("/api/situation/overview")

    assert response.status_code == 200
    assert response.json()["summary"]["current_case_count"] == 3
    assert invalid.status_code == 422
    assert post.status_code == 405
    route = next(
        route
        for route in situation.router.routes
        if getattr(route, "path", "") == "/overview"
    )
    assert route.methods == {"GET"}
