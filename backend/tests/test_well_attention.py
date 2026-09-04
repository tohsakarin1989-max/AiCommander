import asyncio
from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.services.well_attention_service import WellAttentionService


def _well(name: str, latitude: float, longitude: float, output: float, region: str):
    return JurisdictionAsset(
        name=name,
        asset_type="well",
        latitude=latitude,
        longitude=longitude,
        source="ledger",
        status="active",
        verified=True,
        attributes={"日产量": output, "作业区": region},
    )


def test_recent_trace_can_raise_well_attention_without_historical_case(db_session):
    target = _well("北一-12井", 46.6500, 125.1000, 18.5, "萨中作业区")
    other = _well("北二-07井", 46.7100, 124.8800, 8.0, "喇嘛甸作业区")
    db_session.add_all([target, other])
    db_session.flush()
    db_session.add(Event(
        event_number="EVT20260814001",
        event_type="vehicle_trace",
        observation_type="vehicle_trace",
        occurred_time=datetime.now(timezone.utc) - timedelta(hours=12),
        title="发现新鲜陌生车辙",
        latitude=46.6501,
        longitude=125.1001,
        related_asset_id=target.id,
        severity=4,
        freshness="fresh",
        confidence_score=0.9,
        review_status="confirmed",
    ))
    db_session.commit()

    overview = WellAttentionService.build_overview(
        db_session,
        days_back=30,
        include_cached_ai=False,
    )

    assert overview["summary"]["recent_observations"] == 1
    assert overview["summary"]["attention_wells"] == 1
    assert overview["wells"][0]["asset_id"] == target.id
    assert overview["wells"][0]["attention_score"] >= 45
    assert overview["wells"][0]["score_components"]["historical_cases"] == 0
    assert overview["wells"][0]["score_components"]["defense_gaps"] == 0
    assert overview["wells"][0]["signal_types"] == ["vehicle_trace"]


def test_rejected_trace_does_not_heat_well(db_session):
    well = _well("南三-05井", 46.5000, 124.9000, 10.0, "杏树岗作业区")
    db_session.add(well)
    db_session.flush()
    db_session.add(Event(
        event_number="EVT20260814002",
        event_type="oil_trace",
        observation_type="oil_trace",
        occurred_time=datetime.now(timezone.utc),
        related_asset_id=well.id,
        severity=5,
        freshness="fresh",
        confidence_score=1.0,
        review_status="rejected",
    ))
    db_session.commit()

    overview = WellAttentionService.build_overview(
        db_session,
        days_back=30,
        include_cached_ai=False,
    )

    assert overview["summary"]["recent_observations"] == 0
    assert overview["wells"][0]["signal_count"] == 0


def test_ai_refresh_returns_explicit_data_gap_without_wells(db_session):
    overview = asyncio.run(WellAttentionService.refresh_ai_analysis(db_session))

    assert overview["summary"]["total_wells"] == 0
    assert overview["ai_analysis"]["model_status"] == "insufficient_data"
    assert "井点基础数据" in overview["ai_analysis"]["deployment_suggestions"][0]["target"]
    assert any("不是犯罪预测" in item for item in overview["boundary"])


def test_ai_output_rejects_unknown_wells_regions_and_targets(db_session):
    well = _well("北一-12井", 46.6500, 125.1000, 18.5, "萨中作业区")
    db_session.add(well)
    db_session.flush()
    overview = WellAttentionService.build_overview(
        db_session,
        include_cached_ai=False,
    )

    result = WellAttentionService._sanitize_ai_analysis({
        "attention_regions": [
            {"name": "不存在区域", "level": "high", "confidence": 1},
            {"name": "萨中作业区", "level": "unknown", "confidence": 2},
        ],
        "attention_wells": [
            {"asset_id": 9999, "name": "虚构井点", "level": "high", "confidence": 1},
            {"asset_id": well.id, "name": "被篡改井名", "level": "watch", "confidence": 0.7},
        ],
        "deployment_suggestions": [
            {"target": "虚构井点", "priority": "high", "action": "自动派发"},
            {"target": "北一-12井", "priority": "high", "action": "核验现有视频覆盖"},
        ],
    }, overview)

    assert [item["name"] for item in result["attention_regions"]] == ["萨中作业区"]
    assert [item["name"] for item in result["attention_wells"]] == ["北一-12井"]
    assert [item["target"] for item in result["deployment_suggestions"]] == ["北一-12井"]
