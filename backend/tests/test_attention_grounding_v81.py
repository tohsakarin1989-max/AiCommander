"""Grounding is a full authorized read, not proximity-based risk scoring."""
from datetime import datetime, timezone
from time import monotonic

import pytest
from sqlalchemy import event

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_source import CaseLocation, CaseSourceLink
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, OperationalArea
from app.services.attention_grounding import (
    attention_recommendations, attention_sources_visible, build_attention_grounding,
)
from app.services.case_pipeline_service import CasePipelineService
from app.services.facility_dossier_content import build_dossier_content


@pytest.fixture
def db(db_session):
    db_session.add_all([OperationalArea(id=n, code=f"attention-{n}", name=f"区域{n}", status="active") for n in (1, 2)])
    db_session.flush()
    db_session.add(JurisdictionAsset(id=1, name="甲井", asset_type="well", operational_area_id=1,
        latitude=46, longitude=125, status="active", verified=True,
        attributes={"historical_methods": ["打孔盗油"]}))
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    return db_session


def add_case(db, identifier, text="夜间打孔盗油", *, area=1, profile=True):
    case = Case(id=identifier, case_number=f"ATT-{identifier}", operational_area_id=area,
        description=text, discovered_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        occurred_time=datetime(2026, 10, 6, tzinfo=timezone.utc), time_precision="exact")
    db.add(case)
    db.flush()
    if profile:
        payload = CasePipelineService.build_profile_payload(db, case)
        db.add(CaseAnalysisProfile(id=f"attention-profile-{identifier}", case_id=identifier,
            profile_version=1, source_hash=payload["source_hash"], schema_version="8.0.0",
            dictionary_version="test", quality_score=1, analysis_readiness="ready",
            is_current=True, payload=payload))
    db.commit()
    return case


def grounding(db, ids):
    return build_attention_grounding(db, 1, ids, area_name="区域1")


def refresh_profile(db, identifier):
    case = db.query(Case).filter_by(id=identifier).one()
    profile = db.query(CaseAnalysisProfile).filter_by(case_id=identifier).one()
    payload = CasePipelineService.build_profile_payload(db, case)
    profile.source_hash, profile.payload = payload["source_hash"], payload
    db.commit()


def facility(snapshot):
    return next(row for row in snapshot["items"] if row["object_key"] == "asset:1")


def test_same_source_is_one_new_record_not_a_repeated_pattern(db):
    add_case(db, 1)
    add_case(db, 2)
    db.add_all([CaseSourceLink(case_id=n, source_type="tip", source_id=10, source_snapshot={}) for n in (1, 2)])
    db.commit()
    for identifier in (1, 2):
        refresh_profile(db, identifier)
    result = grounding(db, [1, 2])
    assert result["coverage"]["independent_records"] == 1
    assert all(row["state"] == "new_information" for row in result["items"])
    conditions = facility(result)["layers"]["condition_similarity"]["items"]
    assert conditions[0]["independent_count"] == 1 and conditions[0]["raw_record_count"] == 2
    assert "仅一条新增情况" in str(attention_recommendations(result))


def test_two_independent_records_support_repetition_but_not_probability(db):
    add_case(db, 1)
    add_case(db, 2)
    result = grounding(db, [1, 2])
    assert facility(result)["state"] == "repeated_conditions"
    assert "score" not in facility(result) and "risk" not in facility(result)
    row = facility(result)["layers"]["condition_similarity"]["items"][0]
    assert row["references"][0]["reference"]["quote"]
    assert row["references"][0]["source_hash"]


@pytest.mark.parametrize("text", ["未发现打孔盗油", "可能存在打孔盗油", "现场情况待核", "打孔盗油；未发现打孔盗油"])
def test_unknown_negative_uncertain_and_conflict_do_not_support_affirmative_conditions(db, text):
    add_case(db, 1, text)
    result = grounding(db, [1])
    assert not result["items"]


def test_conflicting_same_source_cannot_corroborate_itself(db):
    add_case(db, 1, "打孔盗油")
    add_case(db, 2, "未发现打孔盗油")
    db.add_all([CaseSourceLink(case_id=n, source_type="tip", source_id=5, source_snapshot={}) for n in (1, 2)])
    db.commit()
    for identifier in (1, 2):
        refresh_profile(db, identifier)
    assert grounding(db, [1, 2])["items"] == []


def test_proximity_only_is_background_even_for_typed_discovery_point(db):
    add_case(db, 1, "现场发现不明物品")
    db.add(CaseLocation(case_id=1, role="discovery", precision="exact", geometry={"type": "Point", "coordinates": [125, 46]}))
    db.commit()
    assert grounding(db, [1])["items"] == []
    dossier = build_dossier_content(db, 1)
    result = dossier["attention_grounding"]
    assert result["state"] == "background_only"
    assert result["layers"]["spatial_proximity"]["items"][0]["location_role"] == "discovery"
    assert result["layers"]["explicit_links"]["record_count"] == 0
    assert "未取得技防资料，不等于没有技防" in result["gaps"]


def test_event_link_and_proximity_are_separate_and_event_does_not_add_case(db):
    case = add_case(db, 1, "现场情况")
    case.latitude, case.longitude = 46, 125
    db.add_all([Event(event_number=f"ATT-E-{n}", operational_area_id=1, title="已登记关联",
        occurred_time=datetime(2026, 10, 6),
        event_type="oil_trace", related_case_id=1, related_asset_id=1) for n in (1, 2)])
    db.commit()
    result = facility(grounding(db, [1]))
    assert result["layers"]["explicit_links"]["record_count"] == 1
    assert result["layers"]["spatial_proximity"]["record_count"] == 1
    assert result["state"] == "new_information"


def test_full_collection_not_first_hundred_and_merged_max_three_objects(db):
    for identifier in range(1, 106):
        add_case(db, identifier, "打孔盗油" if identifier >= 104 else "资料未知", profile=identifier >= 104)
    for identifier in range(2, 6):
        db.add(JurisdictionAsset(id=identifier, name="同名井", asset_type="well", operational_area_id=1,
            status="active", verified=True, attributes={"historical_methods": ["打孔盗油"]}))
    db.commit()
    result = grounding(db, list(range(1, 106)))
    assert result["coverage"]["cases_scanned"] == 105
    assert result["coverage"]["facilities_scanned"] == 5
    assert result["coverage"]["enriched_objects"] == 3
    assert len(result["items"]) == 3
    assert len({row["object_key"] for row in result["items"]}) == 3
    assert all(row["support_record_count"] == 2 for row in result["items"])


def test_current_scope_and_source_access_are_rechecked(db):
    add_case(db, 1)
    result = grounding(db, [1])
    assert attention_sources_visible(db, result)
    db.info["authorized_area_ids"] = (2,)
    assert not attention_sources_visible(db, result)
    with pytest.raises(PermissionError):
        grounding(db, [1])
    db.info["authorized_area_ids"] = (1,)
    db.add(MapSource(id=30, source_key="attention-secret", name="秘密资料", source_type="internal_gis", operational_area_id=2))
    db.query(JurisdictionAsset).filter_by(id=1).first().attributes = {"source_id": 30, "historical_methods": ["秘密手法"]}
    db.commit()
    assert not attention_sources_visible(db, result)
    dossier = build_dossier_content(db, 1)
    assert dossier["attention_grounding"]["layers"]["production_background"]["state"] == "restricted"
    assert "秘密" not in str(dossier["attention_grounding"])


def test_read_does_not_flush_or_rebuild_profiles(db):
    add_case(db, 1)
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        db.autoflush = True
        db.add(Case(case_number="not-saved", operational_area_id=1))
        grounding(db, [1])
        build_dossier_content(db, 1)
        assert writes == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


def test_catalog_scale_only_enriches_selected_objects(db, record_property):
    for identifier in range(1, 201):
        add_case(db, identifier, "打孔盗油" if identifier > 198 else "资料未知", profile=identifier > 198)
    db.add_all([JurisdictionAsset(id=n, name=f"合成设施{n}", asset_type="well", operational_area_id=1,
        status="active", verified=True, latitude=46, longitude=125,
        attributes={"historical_methods": ["打孔盗油"]}) for n in range(2, 1001)])
    db.commit()
    reads = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    started = monotonic()
    try:
        result = grounding(db, list(range(1, 201)))
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    elapsed = monotonic() - started
    record_property("attention_fixture", "200 cases; 1000 facilities; two current profiles; SQLite memory")
    record_property("attention_query_count", len(reads))
    record_property("attention_elapsed_seconds", round(elapsed, 4))
    assert result["coverage"]["cases_scanned"] == 200
    assert result["coverage"]["facilities_scanned"] == 1000
    assert result["coverage"]["ranking_complete"] is True
    assert result["coverage"]["enriched_objects"] == 3
    assert len(reads) < 90  # Must not grow by source-history queries per facility.


def test_expired_budget_is_partial_not_a_complete_no_attention_result(db):
    add_case(db, 1)
    result = build_attention_grounding(db, 1, [1], area_name="区域1", deadline=monotonic() - 1)
    assert result["items"] == []
    assert result["coverage"]["state"] == "partial"
    assert result["coverage"]["profiles_scanned"] == 0
    assert result["coverage"]["ranking_complete"] is False
    assert result["coverage"]["information_gaps"]


def test_automatic_brief_keeps_layered_attention_and_current_rights(db):
    from app.services.deployment_advisor_service import DeploymentAdvisorService
    add_case(db, 1)
    add_case(db, 2)
    as_of = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)
    brief, reused = DeploymentAdvisorService.generate_brief(db,
        operational_area_id=1, period_type="daily", as_of=as_of)
    assert not reused
    visible = DeploymentAdvisorService.brief_to_dict(db, brief)
    assert visible["comparison_snapshot"]["time_basis"] == "discovery"
    assert visible["comparison_snapshot"]["attention"]["items"]
    assert len(visible["recommendations"]) <= 3
    assert all(row["confidence"] is None for row in visible["recommendations"])
    db.query(Case).filter_by(id=1).one().operational_area_id = 2
    db.commit()
    hidden = DeploymentAdvisorService.brief_to_dict(db, brief)
    assert hidden["status"] == "unavailable" and not hidden["recommendations"]


def test_removing_current_attribute_cannot_hide_old_snapshot_source_revocation(db):
    add_case(db, 1)
    source = MapSource(source_key="attention-original", name="旧来源", source_type="internal_gis", operational_area_id=1)
    db.add(source)
    db.flush()
    asset = db.query(JurisdictionAsset).filter_by(id=1).one()
    asset.attributes = {"source_id": source.id, "historical_methods": ["打孔盗油"]}
    db.commit()
    frozen = grounding(db, [1])
    assert attention_sources_visible(db, frozen)
    asset.attributes = {"historical_methods": ["打孔盗油"]}
    source.operational_area_id = 2
    db.commit()
    assert not attention_sources_visible(db, frozen)


def test_expired_production_condition_stays_background_not_current_attention(db):
    add_case(db, 1)
    asset = db.query(JurisdictionAsset).filter_by(id=1).one()
    asset.attributes = {"historical_methods": ["打孔盗油"],
        "production_valid_from": "2020-01-01T00:00:00Z", "production_valid_to": "2021-01-01T00:00:00Z"}
    db.commit()
    assert all(row["object_key"] != "asset:1" for row in grounding(db, [1])["items"])
    result = build_dossier_content(db, 1)["attention_grounding"]
    assert result["state"] == "background_only"
    assert result["layers"]["production_background"]["state"] == "stale"
