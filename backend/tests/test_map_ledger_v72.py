"""Synthetic ledger updates: no network, model, external map or business DB."""
import csv
import io
from copy import deepcopy

import pytest

from tests.test_map_foundation import db_session, _client, _create_source, _create_template
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapFieldDecision, MapIngestRun, JurisdictionAssetVersion, FacilitySourceIdentity
from app.services.map_foundation_service import MapFoundationService as Service
from app.services.facility_identity_service import FacilityIdentityService as Identity
from app.services.map_ingest_execution import retry_rows


BASE = {"井号": "A", "井名": "合成井", "类型": "well", "经度": 125.1, "纬度": 46.6}
PRODUCTION = {"含水下限": 20, "含水上限": 30, "含水单位": "%", "含水口径": "质量含水率",
              "产量": 10, "产量单位": "吨", "产量周期": "日", "产量口径": "净油"}
MAPPING = {"water_cut_min": "含水下限", "water_cut_max": "含水上限", "water_cut_unit": "含水单位",
           "water_cut_basis": "含水口径", "production_output": "产量", "production_output_unit": "产量单位",
           "production_period": "产量周期", "production_basis": "产量口径"}


def csv_bytes(rows, headers=None):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers or list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def setup(db, *, mapping=None, **options):
    client = _client(db)
    source = _create_source(client)
    base = _create_template(client, source["id"])
    data = {key: base[key] for key in ("source_id", "name", "coordinate_system", "field_mapping")}
    data["field_mapping"] = {**data["field_mapping"], **(mapping or {})}
    return source, Service.create_template(db, {**data, **options})


def preview(db, source, template, rows):
    return Service.preview(db, source_id=source["id"], filename="synthetic.csv", content=csv_bytes(rows), template_id=template.id)


def ingest(db, source, template, rows, revision="1", token=None):
    return Service.ingest(db, source_id=source["id"], template_id=template.id, filename="synthetic.csv",
                          content=csv_bytes(rows), source_revision=revision, created_by=1, plan_token=token)[0]


def test_first_change_same_value_new_revision_keeps_facility_unchanged(db_session):
    source, template = setup(db_session, mapping=MAPPING)
    row = {**BASE, **PRODUCTION}
    plan = preview(db_session, source, template, [row])
    assert plan["counts"]["new"] == 1 and not db_session.new and not db_session.dirty
    ingest(db_session, source, template, [row], token=plan["plan_token"])
    row = {**row, "产量": 12}
    plan = preview(db_session, source, template, [row])
    assert plan["counts"]["updated"] == 1
    assert {"field": "production_output", "group": "production", "old": 10.0, "new": 12.0} in plan["rows"][0]["changes"]
    ingest(db_session, source, template, [row], "2", plan["plan_token"])
    asset = db_session.query(JurisdictionAsset).one()
    before = deepcopy(Service.asset_to_dict(asset))
    count = db_session.query(JurisdictionAssetVersion).count()
    plan = preview(db_session, source, template, [row])
    assert plan["counts"]["unchanged"] == 1
    run = ingest(db_session, source, template, [row], "3", plan["plan_token"])
    assert run.updated_assets == 0
    assert db_session.query(JurisdictionAssetVersion).count() == count
    assert Service.asset_to_dict(db_session.query(JurisdictionAsset).one()) == before
    assert db_session.query(MapFeatureClaim).count() == 3
    assert db_session.query(MapFieldDecision).count() == 12


def test_plan_rechecks_source_and_actual_facility_changes(db_session):
    source, template = setup(db_session)
    plan = preview(db_session, source, template, [BASE])
    ingest(db_session, source, template, [BASE])
    with pytest.raises(ValueError, match="plan_stale"):
        ingest(db_session, source, template, [{**BASE, "井名": "改名"}], "2", plan["plan_token"])
    assert db_session.query(MapIngestRun).count() == 1


def test_structure_drift_and_declarations_are_not_silently_applied(db_session):
    source, template = setup(db_session, mapping={"coordinate_system": "坐标系"},
                             expected_structure={"headers": [*BASE, "坐标系"], "sheet_name": None, "header_row": 1})
    plan = preview(db_session, source, template, [{**BASE, "坐标系": "bd09"}])
    assert plan["counts"]["failed"] == 1
    assert plan["rows"][0]["errors"][0]["code"] == "field_declaration_drift"
    changed_headers = {**BASE, "坐标系": "wgs84", "新列": "数据"}
    plan = preview(db_session, source, template, [changed_headers])
    assert not plan['drift'] and plan['publishable']
    assert plan['structure_changes'][0]['added'] == ['新列']
    # v9 maps by confirmed column names; an unused column does not alter meaning.
    ingest(db_session, source, template, [changed_headers])
    missing = {key: value for key, value in changed_headers.items() if key != '坐标系'}
    plan = preview(db_session, source, template, [missing])
    assert plan['drift'][0]['code'] == 'mapped_column_missing'


def test_partial_failure_retry_is_append_only_and_success_cannot_retry(db_session):
    source, template = setup(db_session)
    run = ingest(db_session, source, template, [BASE, {**BASE, "井号": "B", "经度": "错误"}])
    claims = db_session.query(MapFeatureClaim).filter_by(run_id=run.id).order_by(MapFeatureClaim.row_number).all()
    assert run.valid_rows == 1 and run.quarantined_rows == 1
    original = deepcopy(claims[1].raw_payload)
    request = {"request_id": "retry-row-B", "rows": [{"claim_id": claims[1].id, "values": {**BASE, "井号": "B"}}]}
    plan = retry_rows(db_session, run.id, request, preview=True)
    corrected, replay = retry_rows(db_session, run.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert corrected.parent_run_id == run.id and corrected.created_assets == 1
    assert corrected.file_hash == run.file_hash and corrected.original_evidence_object_id == run.original_evidence_object_id
    assert claims[1].raw_payload == original and claims[1].status == "quarantined"
    same, replay = retry_rows(db_session, run.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert replay and same.id == corrected.id
    with pytest.raises(ValueError, match="retry_successful_row_forbidden"):
        retry_rows(db_session, run.id, {"request_id": "retry-good-row", "rows": [{"claim_id": claims[0].id, "values": BASE}]}, preview=True)
    with pytest.raises(ValueError, match="retry_row_superseded"):
        retry_rows(db_session, run.id, {**request, "request_id": "retry-again"}, preview=True)


@pytest.mark.parametrize("state", ["not_provided", "unknown", "clear", "withdraw"])
def test_coupled_group_states_are_distinct_and_no_cross_field_mix(db_session, state):
    source, template = setup(db_session, mapping={**MAPPING, "water_cut_state": "含水处理"})
    row = {**BASE, **PRODUCTION, "含水处理": "set"}
    ingest(db_session, source, template, [row])
    run = ingest(db_session, source, template, [{**row, "含水处理": state}], "2")
    asset = db_session.query(JurisdictionAsset).one()
    if state == "not_provided":
        assert asset.attributes["water_cut_min"] == 20 and run.updated_assets == 0
    else:
        assert "water_cut_min" not in asset.attributes and "water_cut_max" not in asset.attributes
        assert asset.attributes["field_groups"]["water_cut"]["state"] == state
    assert asset.attributes["production_output"] == 10


def test_missing_part_of_existing_measurement_does_not_mix_or_clear(db_session):
    source, template = setup(db_session, mapping=MAPPING)
    row = {**BASE, **PRODUCTION}
    ingest(db_session, source, template, [row])
    plan = preview(db_session, source, template, [{**row, "含水下限": 40, "含水上限": "", "产量": 12}])
    assert plan["counts"]["conflict"] == 1
    ingest(db_session, source, template, [{**row, "含水下限": 40, "含水上限": "", "产量": 12}], "2")
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.attributes["water_cut_min"] == 20 and asset.attributes["water_cut_max"] == 30
    assert asset.attributes["production_output"] == 12


def test_equal_priority_conflict_is_group_local_not_whole_object(db_session):
    source, template = setup(db_session, mapping=MAPPING)
    row = {**BASE, **PRODUCTION}
    ingest(db_session, source, template, [row])
    other = Service.create_source(db_session, {"source_key": "second", "name": "第二来源", "source_type": "ledger"})
    second = Service.create_template(db_session, {"source_id": other.id, "name": "模板", "coordinate_system": "wgs84",
                                                  "field_mapping": template.field_mapping})
    ingest(db_session, {"id": other.id}, second, [{**row, "井号": "ALIAS"}])
    asset = db_session.query(JurisdictionAsset).filter_by(external_id="A").one()
    identity = db_session.query(FacilitySourceIdentity).filter_by(source_id=other.id).one()
    db_session.info["authorized_area_ids"] = None
    Identity.bind(db_session, identity.id, asset.id, actor_id=1, note="合成同设施凭据", request_key="bind-test")
    run = ingest(db_session, {"id": other.id}, second, [{**row, "井号": "ALIAS", "含水下限": 21}], "2")
    assert run.classification_counts["conflict"] == 1
    assert asset.latitude == 46.6 and asset.verified
    assert asset.attributes["production_output"] == 10
    assert "water_cut_min" not in asset.attributes
    assert asset.attributes["field_groups"]["water_cut"]["state"] == "conflict"


def test_current_source_scope_applies_to_batches_rows_templates_and_decisions(db_session):
    source, template = setup(db_session)
    run = ingest(db_session, source, template, [BASE])
    db_session.info["authorized_area_ids"] = ()
    client = _client(db_session)
    assert client.get("/api/map-ingest-runs").json()["total"] == 0
    assert client.get(f"/api/map-ingest-runs/{run.id}/claims").status_code == 404
    assert client.get("/api/map-import-templates").json() == []
    assert db_session.query(MapFieldDecision).count() == 0


def test_admin_field_contract_example_and_bounded_claims_api(db_session):
    client = _client(db_session)
    assert "water_cut_basis" in {row["key"] for row in client.get("/api/map-import-fields").json()["fields"]}
    assert "含水率测量口径" in client.get("/api/map-import-example").content.decode("utf-8-sig")
    assert _client(db_session, role="analyst").get("/api/map-import-example").status_code == 403
    source, template = setup(db_session)
    run = ingest(db_session, source, template, [BASE, {**BASE, "井号": "B"}])
    page = client.get(f"/api/map-ingest-runs/{run.id}/claims?limit=1&offset=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["source_record_id"] == "B"


def test_higher_priority_same_value_receipt_protects_from_later_lower_priority_change(db_session):
    source, template = setup(db_session, mapping=MAPPING)
    from app.models.map_foundation import MapSource
    origin = db_session.query(MapSource).filter_by(id=source["id"]).one()
    origin.trust_rank = 80
    origin.source_type = "internal_gis"
    db_session.commit()
    row = {**BASE, **PRODUCTION}
    ingest(db_session, source, template, [row])
    higher = Service.create_source(db_session, {"source_key": "higher", "name": "权威台账", "source_type": "ledger"})
    higher_template = Service.create_template(db_session, {"source_id": higher.id, "name": "模板",
        "coordinate_system": "wgs84", "field_mapping": template.field_mapping})
    ingest(db_session, {"id": higher.id}, higher_template, [{**row, "井号": "HIGH"}])
    target = db_session.query(JurisdictionAsset).filter_by(external_id="A").one()
    identity = db_session.query(FacilitySourceIdentity).filter_by(source_id=higher.id).one()
    db_session.info["authorized_area_ids"] = None
    Identity.bind(db_session, identity.id, target.id, actor_id=1, note="同设施", request_key="higher-bind")
    versions = db_session.query(JurisdictionAssetVersion).filter_by(asset_id=target.id).count()
    same = ingest(db_session, {"id": higher.id}, higher_template, [{**row, "井号": "HIGH"}], "2")
    assert same.updated_assets == 0
    assert db_session.query(JurisdictionAssetVersion).filter_by(asset_id=target.id).count() == versions
    changed = ingest(db_session, source, template, [{**row, "产量": 12}], "3")
    assert changed.classification_counts["conflict"] == 1
    assert target.attributes["production_output"] == 10


def test_unit_change_requires_one_group_decision_and_stale_decision_is_rejected(db_session):
    source, template = setup(db_session, mapping=MAPPING)
    row = {**BASE, **PRODUCTION}
    ingest(db_session, source, template, [row])
    changed = ingest(db_session, source, template, [{**row, "产量": 11, "产量单位": "立方米"}], "2")
    claim = db_session.query(MapFeatureClaim).filter_by(run_id=changed.id).one()
    assert claim.status == "conflict"
    original = deepcopy(claim.raw_payload)
    client = _client(db_session)
    read_url = f"/api/map-conflicts/{claim.id}/field-decision-preview?group=production"
    view = client.get(read_url).json()
    request = {"group": "production", "request_id": "manual-choice-1", "note": "依据新台账确认单位口径",
               "expected_asset_version": view["asset_version"], "expected_decision_id": view["decision_id"]}
    endpoint = f"/api/map-conflicts/{claim.id}/field-decision"
    response = client.post(endpoint, json=request)
    assert response.status_code == 201, response.text
    assert client.post(endpoint, json=request).status_code == 200
    assert client.post(endpoint, json={**request, "request_id": "manual-choice-2"}).status_code == 409
    assert claim.raw_payload == original
    asset = db_session.query(JurisdictionAsset).filter_by(external_id="A").one()
    assert asset.attributes["production_output_unit"] == "立方米"
    assert asset.attributes["production_output"] == 11
    assert asset.attributes["water_cut_min"] == 20
    assert asset.attributes["field_groups"]["production"]["manual_override"]
    decision = db_session.query(MapFieldDecision).order_by(MapFieldDecision.id.desc()).first()
    decision.payload = {"changed": True}
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()
    db_session.rollback()


def test_input_error_codes_are_structured_and_role_downgrade_blocks_write(db_session):
    source, template = setup(db_session)
    client = _client(db_session)
    response = client.post(f"/api/map-sources/{source['id']}/ingest?template_id={template.id}",
                           files={"file": ("test.csv", csv_bytes([BASE]))}, data={"plan_token": "0" * 64})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "plan_stale"
    from app.models.user import User
    db_session.query(User).filter_by(id=1).one().role = "viewer"
    db_session.commit()
    response = client.post(f"/api/map-sources/{source['id']}/ingest?template_id={template.id}",
                           files={"file": ("test.csv", csv_bytes([BASE]))})
    assert response.status_code == 403 and db_session.query(MapIngestRun).count() == 0


def test_explicit_pending_parent_correction_adds_identifier_to_same_facility(db_session):
    source, template = setup(db_session)
    original = {**BASE, "井号": ""}
    run = ingest(db_session, source, template, [original])
    parent = db_session.query(MapFeatureClaim).filter_by(run_id=run.id).one()
    asset_id = parent.asset_id
    request = {"request_id": "pending-correction", "rows": [{"claim_id": parent.id, "values": BASE}]}
    plan = retry_rows(db_session, run.id, request, preview=True)
    assert plan["rows"][0]["asset_id"] == asset_id
    assert any(change["field"] == "external_id" and change["old"] is None and change["new"] == "A"
               for change in plan["rows"][0]["changes"])
    child, _ = retry_rows(db_session, run.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert child.created_assets == 0 and child.updated_assets == 1
    asset = db_session.query(JurisdictionAsset).one()
    assert asset.id == asset_id and asset.external_id == "A" and asset.verified
    assert db_session.query(FacilitySourceIdentity).filter_by(native_asset_id=asset_id).count() == 2
    assert parent.raw_payload["井号"] == "" and parent.source_record_id is None
    old_again = ingest(db_session, source, template, [original], "old-file-repeat")
    assert old_again.quarantined_rows == 1 and db_session.query(JurisdictionAsset).count() == 1


def test_pending_parent_identifier_already_used_is_never_auto_merged(db_session):
    source, template = setup(db_session)
    run = ingest(db_session, source, template, [{**BASE, "井号": ""}, {**BASE, "井号": "TAKEN", "井名": "另一设施"}])
    parent = db_session.query(MapFeatureClaim).filter_by(run_id=run.id, status="identity_pending").one()
    request = {"request_id": "occupied-correction", "rows": [{"claim_id": parent.id, "values": {**BASE, "井号": "TAKEN"}}]}
    with pytest.raises(ValueError, match="retry_identifier_taken"):
        retry_rows(db_session, run.id, request, preview=True)
    assert db_session.query(JurisdictionAsset).count() == 2


def test_pending_parent_changed_after_preview_cannot_be_promoted(db_session):
    source, template = setup(db_session, mapping={"address": "地址"})
    original = {**BASE, "井号": "", "地址": "原记录"}
    run = ingest(db_session, source, template, [original])
    parent = db_session.query(MapFeatureClaim).filter_by(run_id=run.id).one()
    request = {"request_id": "stale-parent-correction", "rows": [{"claim_id": parent.id, "values": {**original, "井号": "NEW"}}]}
    plan = retry_rows(db_session, run.id, request, preview=True)
    ingest(db_session, source, template, [{**original, "地址": "后续原始资料"}], "2")
    with pytest.raises(ValueError, match="retry_parent_stale"):
        retry_rows(db_session, run.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert db_session.query(JurisdictionAsset).one().external_id is None


def test_geographic_coordinates_cannot_be_silently_interpreted_as_meters(db_session):
    with pytest.raises(ValueError, match="coordinate_unit_mismatch"):
        setup(db_session, coordinate_unit="meter")
