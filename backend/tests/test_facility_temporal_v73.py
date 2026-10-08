"""Complete uncertainty intervals and bitemporal field groups; synthetic only."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, MapFeatureClaim, MapFieldDecision, MapIngestRun, MapImportTemplate
from app.services.facility_temporal_conditions import resolve_conditions, case_window, group_match, validate_temporal_access
from app.services.facility_production_conditions import production_comparison
from tests.test_facility_identity_v62 import db, source  # noqa: F401
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_facility_summary import asset as api_asset, client
from tests.test_result_materials_v65 import material_db  # noqa: F401
from tests.test_facility_condition_comparison import facility_db, add_profile  # noqa: F401

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1, T2, T3 = [T0 + timedelta(days=value) for value in (10, 20, 30)]


@pytest.fixture
def ledger(db):
    origin = source(db)
    asset = JurisdictionAsset(name="合成历史井", asset_type="well", operational_area_id=1, source="ledger",
                              verified=True, external_id="H1", status="active", attributes={"source_id": origin.id})
    db.add(asset)
    template = MapImportTemplate(source_id=origin.id, name="synthetic", field_mapping={}, coordinate_system="wgs84")
    db.add(template)
    db.flush()
    run = MapIngestRun(id="synthetic-history", source_id=origin.id, template_id=template.id,
                       filename="synthetic.csv", file_hash="a" * 64, idempotency_key="a" * 64)
    db.add(run)
    db.flush()
    return db, origin, asset, run


def decision(ledger, *, start=T0, end=T3, known=T0, low=20, high=40,
             group="water_cut", state="set", outcome="accepted", reason="same_source_update", origin=None, rank=None, **values):
    db, default_origin, asset, run = ledger
    origin = origin or default_origin
    count = db.query(MapFeatureClaim).count()
    claim = MapFeatureClaim(run_id=run.id, source_id=origin.id, row_number=count + 1, source_revision=str(count),
        raw_payload={}, raw_hash="b" * 64, asset_id=asset.id, status="accepted",
        normalized_payload={"asset_type": "well", "verified": True, "status": "active"})
    db.add(claim)
    db.flush()
    payload = {"water_cut_min": low, "water_cut_max": high, "water_cut_unit": "percent"} if group == "water_cut" else {}
    payload.update(values)
    row = MapFieldDecision(asset_id=asset.id, source_id=origin.id, claim_id=claim.id, group_key=group,
        state=state, outcome=outcome, payload={"new": payload, "reason": reason, "trust_rank": rank or origin.trust_rank},
        valid_from=start, valid_to=end, known_at=known)
    db.add(row)
    db.flush()
    return row


def read(ledger, **kwargs):
    return resolve_conditions(ledger[0], ledger[2].id, **kwargs)


def test_late_same_period_correction_respects_known_cutoff_and_freezes_old_value(ledger):
    decision(ledger, known=T0)
    decision(ledger, known=T2, low=60, high=80)
    old = read(ledger, valid_at=T1, known_at=T1, knowledge_mode="as_known")
    new = read(ledger, valid_at=T1, knowledge_mode="retrospective")
    assert old["groups"]["water_cut"]["segments"][0]["values"]["water_cut_min"] == 20
    assert new["groups"]["water_cut"]["segments"][0]["values"]["water_cut_min"] == 60
    assert not old["late_supplement"] and new["late_supplement"]
    assert old["groups"]["water_cut"]["segments"][0]["values"]["water_cut_min"] == 20
    assert not ledger[0].dirty


def test_interval_evaluates_every_version_and_closed_endpoint_not_midpoint(ledger):
    decision(ledger, end=T1, known=T0)
    decision(ledger, start=T1, known=T0, low=60, high=80)
    context = read(ledger, valid_from=T0, valid_to=T2)
    group = context["groups"]["water_cut"]
    assert group["coverage"] == "full" and context["snapshot"] is None
    assert context["valid_from"] is None and context["query_interval"]["from"] == T0.isoformat()
    assert {row["values"]["water_cut_min"] for row in group["segments"]} == {20, 60}
    result = production_comparison(attributes={}, verified=True, case_fields={}, case_facts={"water_cut": 30}, temporal_context=context)
    assert result["state"] == "unknown" and result["coverage"] == "partial"
    assert not result["support"]


def test_boundary_gap_partial_unknown_validity_and_equal_interval(ledger):
    decision(ledger, end=T1)
    partial = read(ledger, valid_from=T0, valid_to=T1)
    assert partial["groups"]["water_cut"]["coverage"] == "partial"  # final endpoint is excluded by source validity
    assert read(ledger, valid_from=T0, valid_to=T0)["groups"]["water_cut"]["coverage"] == "full"
    decision(ledger, start=None, end=None, known=T2)
    unknown = read(ledger, valid_at=T1)
    assert unknown["groups"]["water_cut"]["coverage"] == "unknown"
    assert read(ledger)["time_precision"] == "unknown"


@pytest.mark.parametrize("state", ["unknown", "clear", "withdraw"])
def test_explicit_unavailability_does_not_resurrect_older_fact(ledger, state):
    decision(ledger)
    decision(ledger, known=T1, state=state)
    context = read(ledger, valid_at=T2)
    assert context["groups"]["water_cut"]["state"] == "unknown"
    assert context["groups"]["water_cut"]["segments"][0]["values"] is None


def test_not_provided_lower_priority_conflict_and_other_group_are_independent(ledger):
    decision(ledger)
    decision(ledger, known=T1, state="not_provided", outcome="not_provided")
    other = source(ledger[0], key="other", rank=80)
    decision(ledger, origin=other, known=T2, outcome="conflict", reason="lower_priority", low=60)
    decision(ledger, group="production", production_output=12, production_output_unit="tonne", production_period="day")
    context = read(ledger, valid_at=T2)
    assert context["groups"]["water_cut"]["segments"][0]["values"]["water_cut_min"] == 20
    assert context["groups"]["production"]["coverage"] == "full"


def test_equal_priority_only_quarantines_disputed_group_and_manual_resolves(ledger):
    decision(ledger)
    other = source(ledger[0], key="equal")
    decision(ledger, origin=other, known=T1, outcome="conflict", reason="equal_priority", low=60)
    decision(ledger, group="production", production_output=12)
    context = read(ledger, valid_at=T2)
    assert context["groups"]["water_cut"]["state"] == "conflict"
    assert context["groups"]["production"]["coverage"] == "full"
    decision(ledger, known=T2, outcome="manual")
    assert read(ledger, valid_at=T2)["groups"]["water_cut"]["state"] == "ready"


def test_stopped_or_out_of_scope_sources_hide_values_and_segment_counts(ledger):
    decision(ledger)
    frozen = read(ledger, valid_at=T1)
    ledger[1].status = "disabled"
    ledger[0].commit()
    restricted = read(ledger, valid_at=T1)
    assert restricted["groups"]["water_cut"]["state"] == "restricted"
    assert restricted["groups"]["water_cut"]["segments"] == []
    with pytest.raises((LookupError, PermissionError)):
        validate_temporal_access(ledger[0], frozen)
    ledger[0].info["authorized_area_ids"] = (2,)
    with pytest.raises((LookupError, PermissionError)):
        read(ledger, valid_at=T1)


def test_context_modes_validate_without_guessing_unknown_time(ledger):
    with pytest.raises(ValueError, match="known_at_required"):
        read(ledger, valid_at=T1, knowledge_mode="as_known")
    with pytest.raises(ValueError, match="server_assigned"):
        read(ledger, valid_at=T1, known_at=T2, knowledge_mode="retrospective")
    with pytest.raises(ValueError, match="future_knowledge"):
        read(ledger, valid_at=T1, known_at=datetime.now(timezone.utc) + timedelta(days=1))
    with pytest.raises(ValueError, match="conflict"):
        read(ledger, valid_at=T1, valid_from=T0, valid_to=T2)
    with pytest.raises(ValueError, match="incomplete"):
        read(ledger, valid_from=T1)
    assert case_window({"time_precision": "unknown", "occurred_time": T1.isoformat()})["valid_at"] is None


def test_different_group_effective_periods_and_measurement_basis_do_not_mix(ledger):
    decision(ledger, water_cut_basis="现场取样")
    decision(ledger, group="production", start=T2, production_output=99)
    context = read(ledger, valid_from=T0, valid_to=T1)
    assert context["groups"]["water_cut"]["coverage"] == "full"
    assert context["groups"]["production"]["coverage"] == "unknown"
    result = production_comparison(attributes={}, verified=True, case_fields={}, case_facts={"water_cut": 30}, temporal_context=context)
    assert result["state"] == "unknown"
    assert production_comparison(attributes={}, verified=True, case_fields={},
        case_facts={"water_cut": 30, "water_cut_basis": "现场取样"}, temporal_context=context)["state"] == "matched"


@pytest.mark.parametrize("query", [
    "valid_from=2026-01-01T00:00:00Z",
    "valid_at=2026-01-01T00:00:00Z&valid_from=2026-01-01T00:00:00Z&valid_to=2026-01-02T00:00:00Z",
    "knowledge_mode=as_known",
    "knowledge_mode=retrospective&known_at=2026-01-01T00:00:00Z",
    "known_at=2099-01-01T00:00:00Z",
    "valid_at=2026-01-01T00:00:00Z&valid_at=2026-01-02T00:00:00Z",
])
def test_dossier_rejects_ambiguous_temporal_parameters(query_db, query):
    value = api_asset(query_db)
    with client(query_db) as http:
        response = http.get(f"/api/facility-analysis/assets/{value.id}?{query}")
    assert response.status_code == 422


def test_dossier_interval_does_not_change_old_version_period_fields(query_db):
    value = api_asset(query_db)
    with client(query_db) as http:
        response = http.get(f"/api/facility-analysis/assets/{value.id}", params={
            "valid_from": T0.isoformat(), "valid_to": T1.isoformat(), "knowledge_mode": "retrospective"})
    assert response.status_code == 200, response.text
    temporal = response.json()["temporal_context"]
    assert temporal["query_interval"] == {"from": T0.isoformat(), "to": T1.isoformat()}
    assert temporal["valid_at"] is None and temporal["valid_from"] is None and temporal["snapshot"] is None
    assert response.json()["computability"]["checks"] == []


def test_query_history_tool_uses_identical_field_group_resolver(query_db):
    from app.services.intelligent_query_business import execute_business_tool, ReadFacilityAt
    value = api_asset(query_db)
    query_db.add(JurisdictionAssetVersion(asset_id=value.id, version=1, change_type="manual", temporal_status="declared",
        valid_from=T0, valid_to=T3, known_at=T0, snapshot={"operational_area_id": 1,
        "asset_type": "well", "verified": True, "status": "active", "attributes": {"oil_type": "原油"}}))
    query_db.commit()
    result = execute_business_tool(query_db, "read_facility_at", ReadFacilityAt(asset_id=value.id, valid_at=T1, known_at=T1))
    assert result["historical"] == resolve_conditions(query_db, value.id, valid_at=T1, known_at=T1)
    assert result["historical"]["groups"]["details"]["coverage"] == "full"


def test_interval_material_keeps_frozen_knowledge_and_exports_it(material_db):
    import json
    from app.services.facility_material_service import freeze_facility, read_facility_material
    from app.services.result_catalog import read_result
    value = api_asset(material_db)
    material_db.add(JurisdictionAssetVersion(asset_id=value.id, version=1, change_type="manual", temporal_status="declared",
        valid_from=T0, valid_to=T3, known_at=T0, snapshot={"operational_area_id": 1,
        "asset_type": "well", "verified": True, "status": "active", "attributes": {"oil_type": "原油"}}))
    material_db.commit()
    row, _ = freeze_facility(material_db, value.id, idempotency_key="temporal-interval-material",
        valid_from=T0, valid_to=T1, known_at=T1, knowledge_mode="as_known")
    material_db.commit()
    _, original = read_facility_material(material_db, row.id)
    material_db.add(JurisdictionAssetVersion(asset_id=value.id, version=2, change_type="manual", temporal_status="declared",
        valid_from=T0, valid_to=T3, known_at=T2, snapshot={"operational_area_id": 1,
        "asset_type": "well", "verified": True, "status": "active", "attributes": {"oil_type": "柴油"}}))
    material_db.commit()
    assert read_facility_material(material_db, row.id)[1] == original
    document = read_result(material_db, "facility", row.id)["document"]
    assert "完整业务时间区间" in json.dumps(document, ensure_ascii=False)
    assert "当时已知" in json.dumps(document, ensure_ascii=False)


def test_old_manual_version_does_not_imply_explicit_override_of_production_ledger(ledger):
    database, _, value, _ = ledger
    database.add(JurisdictionAssetVersion(asset_id=value.id, version=1, change_type="manual", temporal_status="declared",
        valid_from=T0, valid_to=T3, known_at=T0, snapshot={"operational_area_id": 1,
        "asset_type": "well", "verified": True, "status": "active", "attributes": {
            "water_cut_min": 60, "water_cut_max": 80, "water_cut_unit": "percent",
            "production_valid_from": T0.isoformat(), "production_valid_to": T3.isoformat()}}))
    decision(ledger, known=T1, low=20, high=40)
    value = read(ledger, valid_at=T2)
    assert value["groups"]["water_cut"]["segments"][0]["values"]["water_cut_min"] == 20


def test_dossier_time_window_preserves_overlapping_interval_cases(facility_db):
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.facility_dossier_content import build_dossier_content
    case = facility_db.get(Case, 1)
    case.occurred_time, case.time_precision = None, "interval"
    case.occurred_from, case.occurred_to = T0, T2
    facility_db.query(CaseAnalysisProfile).filter_by(case_id=case.id).delete()
    facility_db.flush()
    add_profile(facility_db, case)
    facility_db.commit()
    dossier = build_dossier_content(facility_db, 1, start_date=T1, end_date=T3)
    assert any(row["case_id"] == case.id for row in dossier["sections"]["history_conditions"]["items"])


def test_frozen_material_rechecks_source_used_only_by_historical_case_condition(material_db):
    from app.services.facility_material_service import freeze_facility, read_facility_material
    from app.services.result_catalog import read_result
    from app.services.result_document import export_result
    from tests.test_case_search_page import add_case

    old_source = source(material_db, key="historical-only-source")
    current_source = source(material_db, key="current-source")
    value = api_asset(material_db)
    value.attributes = {"source_id": current_source.id, "oil_type": "柴油"}
    for number, origin, oil, start, end in (
            (1, old_source, "原油", T0, T2), (2, current_source, "柴油", T2, None)):
        material_db.add(JurisdictionAssetVersion(asset_id=value.id, version=number,
            change_type="manual", temporal_status="declared", valid_from=start, valid_to=end,
            known_at=start, snapshot={"operational_area_id": 1, "name": value.name,
                "asset_type": "well", "verified": True, "status": "active",
                "attributes": {"source_id": origin.id, "oil_type": oil}}))
    case = add_case(material_db, "historical-source-case", occurred_time=T1,
                    description="井口发现原油，打孔盗油。", facility_type="井口", oil_type="原油")
    add_profile(material_db, case)
    material_db.commit()
    row, _ = freeze_facility(material_db, value.id, idempotency_key="historical-source-material")
    material_db.commit()
    _, body = read_facility_material(material_db, row.id)
    top_sources = {source_id for group in body["temporal_context"]["groups"].values()
                   for segment in group["segments"] for source_id in segment["source_ids"]}
    assert old_source.id not in top_sources and current_source.id in top_sources
    historical = body["sections"]["history_conditions"]["items"][0]["source_context"]
    assert historical["groups"]["details"]["segments"][0]["values"]["oil_type"] == "原油"

    old_source.status = "disabled"
    material_db.commit()
    for read_saved in (
            lambda: read_facility_material(material_db, row.id),
            lambda: read_result(material_db, "facility", row.id),
            lambda: export_result(material_db, "facility", row.id, "docx")):
        with pytest.raises(PermissionError):
            read_saved()


@pytest.mark.parametrize("record_kind", ["asset_version", "field_decision", "inherited_group"])
def test_same_source_bound_identities_remain_independent_history_lanes(db, monkeypatch, record_kind):
    from app.models.map_foundation import FacilitySourceIdentity
    from app.services.facility_identity_service import FacilityIdentityService as Identity

    origin = source(db)
    if record_kind != "asset_version":
        template = MapImportTemplate(source_id=origin.id, name="bound-history", field_mapping={}, coordinate_system="wgs84")
        db.add(template)
        db.flush()
        run = MapIngestRun(id="bound-history", source_id=origin.id, template_id=template.id,
            filename="synthetic.csv", file_hash="c" * 64, idempotency_key="c" * 64)
        db.add(run)
        db.flush()
    assets, identities, claims = [], [], []
    for number, oil in ((1, "原油"), (2, "柴油")):
        value = JurisdictionAsset(name="合成历史井", asset_type="well", operational_area_id=1,
            source="ledger", verified=True, external_id=f"BOUND-{number}", status="active",
            attributes={"source_id": origin.id, "oil_type": oil})
        db.add(value)
        db.flush()
        identity = FacilitySourceIdentity(source_id=origin.id, operational_area_id=1,
            native_asset_id=value.id, identity_key=f"well:BOUND-{number}", source_record_id=f"BOUND-{number}",
            asset_type="well", identity_kind="exact_id", created_at=T0)
        db.add(identity)
        db.flush()
        snapshot = {"operational_area_id": 1, "name": value.name,
                    "asset_type": "well", "verified": True, "status": "active",
                    "attributes": {"source_id": origin.id, "oil_type": oil}}
        if record_kind == "asset_version":
            db.add(JurisdictionAssetVersion(asset_id=value.id, version=1, source_identity_id=identity.id,
                change_type="manual", temporal_status="declared", valid_from=T0, valid_to=T3,
                known_at=T0, snapshot=snapshot))
        else:
            claim = MapFeatureClaim(run_id=run.id, source_id=origin.id, row_number=number,
                source_revision="1", raw_payload={}, raw_hash="d" * 64, asset_id=value.id,
                source_identity_id=identity.id, status="accepted", normalized_payload=snapshot)
            db.add(claim)
            db.flush()
            claims.append(claim)
            db.add(MapFieldDecision(asset_id=value.id, source_id=origin.id, claim_id=claim.id,
                group_key="details", state="set", outcome="accepted", valid_from=T0, valid_to=T3,
                known_at=T0, payload={"new": {"name": value.name, "oil_type": oil}, "trust_rank": 100}))
        assets.append(value)
        identities.append(identity)
    if record_kind == "inherited_group":
        # A newer version on identity 2 carries identity 1's adopted details;
        # it must not replace identity 2's independent oil evidence lane.
        db.add(JurisdictionAssetVersion(asset_id=assets[1].id, version=1,
            source_identity_id=identities[1].id, change_type="updated", temporal_status="declared",
            valid_from=T0, valid_to=T3, known_at=T2, snapshot={"operational_area_id": 1,
                "name": assets[1].name, "asset_type": "well", "verified": True, "status": "active",
                "attributes": {"source_id": origin.id, "oil_type": "原油", "field_groups": {
                    "details": {"claim_id": claims[0].id, "source_id": origin.id, "trust_rank": 100,
                                "valid_from": T0.isoformat(), "valid_to": T3.isoformat(), "state": "set"}}}}))
    monkeypatch.setattr("app.services.facility_identity_service._now", lambda: T2)
    Identity.bind(db, identities[1].id, assets[0].id, actor_id=1,
                  note="人工编号对照绑定", request_key="same-source-identity-bind")
    db.commit()
    before = resolve_conditions(db, assets[0].id, valid_at=T1, known_at=T1)
    assert before["groups"]["details"]["state"] == "ready"
    assert before["groups"]["details"]["segments"][0]["values"]["oil_type"] == "原油"
    if record_kind == "asset_version":
        assert Identity.get_asset_at(db, assets[0].id, valid_at=T1, known_at=T3)["state"] == "conflict"
    current = resolve_conditions(db, assets[0].id, valid_from=T0, valid_to=T1, known_at=T3)
    assert current["groups"]["details"]["state"] == "conflict"
    assert all(segment["values"] is None for segment in current["groups"]["details"]["segments"])
    if record_kind == "asset_version":
        assert current["groups"]["geometry"]["state"] == "ready"
