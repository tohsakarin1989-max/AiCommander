"""Declared ledger scope uses synthetic files and never infers shutdown / deletion."""
from copy import deepcopy
import json

import pytest

from tests.test_map_foundation import db_session, _client  # noqa: F401
from tests.test_map_ledger_v72 import BASE, csv_bytes, setup, ingest
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapSource, OperationalArea
from app.services.map_foundation_service import MapFoundationService as Service
from app.services.map_ingest_execution import retry_rows
from app.services.map_ledger_completeness import parse_declaration, read_comparison


def declaration(month, **extra):
    return {"mode": "full", "scope_key": "north-wells", "scope_description": "合成北区登记井",
            "valid_from": f"2026-{month:02d}-01T00:00:00+08:00",
            "valid_to": f"2026-{month + 1:02d}-01T00:00:00+08:00", **extra}


def preview(db, source, template, rows, scope):
    return Service.preview(db, source_id=source["id"], filename="synthetic.csv", content=csv_bytes(rows),
                           template_id=template.id, ledger_declaration=scope)


def load(db, source, template, rows, scope):
    plan = preview(db, source, template, rows, scope)
    run, replay = Service.ingest(db, source_id=source["id"], template_id=template.id, filename="synthetic.csv",
        content=csv_bytes(rows), source_revision=f"synthetic-{scope['valid_from']}", created_by=1,
        plan_token=plan["plan_token"], ledger_declaration=scope)
    return run, plan, replay


def test_adjacent_complete_ledger_records_absence_but_never_changes_missing_facility(db_session):
    source, template = setup(db_session)
    first, _, _ = load(db_session, source, template, [BASE, {**BASE, "井号": "B", "井名": "合成B"}], declaration(8))
    asset = db_session.query(JurisdictionAsset).filter_by(external_id="B").one()
    before = deepcopy(Service.asset_to_dict(asset))
    second, plan, replay = load(db_session, source, template, [BASE], declaration(9))
    assert not replay and plan["ledger_comparison"]["phase"] == "preview"
    assert "ledger_comparison" not in plan["structure"]
    assert plan["ledger_comparison"]["missing_count"] == 1
    result = read_comparison(db_session, second.id)
    assert result["phase"] == "executed" and result["status"] == "comparable"
    assert result["baseline_run_id"] == first.id and result["missing"][0]["source_record_id"] == "B"
    assert result["previous_count"] == 2 and result["current_count"] == 1
    assert Service.asset_to_dict(asset) == before
    receipt = Service.run_to_dict(second)
    assert receipt["ledger_declaration"]["origin"] == "administrator_declaration"
    assert receipt["declaration_actor_id"] == 1
    assert "ledger_comparison" not in receipt["table_metadata"]
    assert receipt["ledger_declaration"]["valid_from"] == "2026-08-31T16:00:00+00:00"
    same, _, replay = load(db_session, source, template, [BASE], declaration(9))
    assert replay and same.id == second.id


@pytest.mark.parametrize("change,reason", [
    ({"mode": "incremental"}, "incremental"),
    ({"scope_key": "south-wells"}, "no_previous_comparable_ledger"),
    ({"scope_description": "改为仅重点井"}, "no_previous_comparable_ledger"),
    ({"valid_from": "2026-09-02T00:00:00+08:00"}, "period_gap"),
    ({"valid_from": "2026-08-15T00:00:00+08:00"}, "overlapping_period"),
])
def test_noncomparable_declarations_do_not_offer_missing_counts(db_session, change, reason):
    source, template = setup(db_session)
    load(db_session, source, template, [BASE, {**BASE, "井号": "B"}], declaration(8))
    run, _, _ = load(db_session, source, template, [BASE], declaration(9, **change))
    result = read_comparison(db_session, run.id)
    assert result["reason"] == reason and "missing_count" not in result


def test_first_ledger_and_unknown_legacy_import_remain_usable(db_session):
    source, template = setup(db_session)
    old = ingest(db_session, source, template, [BASE])
    assert read_comparison(db_session, old.id)["reason"] == "coverage_unknown"
    first, _, _ = load(db_session, source, template, [BASE], declaration(8))
    assert read_comparison(db_session, first.id)["reason"] == "no_previous_comparable_ledger"
    ingest(db_session, source, template, [BASE], revision="later-unknown")
    second, _, _ = load(db_session, source, template, [BASE], declaration(9))
    assert read_comparison(db_session, second.id)["reason"] == "intervening_coverage_unknown"


def test_different_source_and_current_failed_rows_cannot_create_absence(db_session):
    source, template = setup(db_session)
    load(db_session, source, template, [BASE, {**BASE, "井号": "B"}], declaration(8))
    other = Service.create_source(db_session, {"source_key": "separate-ledger", "name": "独立合成来源", "source_type": "ledger"})
    other_template = Service.create_template(db_session, {"source_id": other.id, "name": "独立模板",
        "coordinate_system": "wgs84", "field_mapping": template.field_mapping})
    different, _, _ = load(db_session, {"id": other.id}, other_template, [{**BASE, "井号": "OTHER"}], declaration(9))
    assert read_comparison(db_session, different.id)["reason"] == "no_previous_comparable_ledger"
    broken, _, _ = load(db_session, source, template, [BASE, {**BASE, "井号": "C", "经度": "错误"}], declaration(9))
    result = read_comparison(db_session, broken.id)
    assert result["reason"] == "current_rows_incomplete" and "missing_count" not in result


@pytest.mark.parametrize("previous_mode,broken,reason", [
    ("full", True, "previous_rows_incomplete"), ("incremental", False, "previous_not_full"),
])
def test_partial_failure_or_incremental_cannot_become_complete_baseline(db_session, previous_mode, broken, reason):
    source, template = setup(db_session)
    rows = [BASE, {**BASE, "井号": "B", "经度": "错误" if broken else 125.1}]
    first, _, _ = load(db_session, source, template, rows, declaration(8, mode=previous_mode))
    second, _, _ = load(db_session, source, template, [BASE], declaration(9))
    assert read_comparison(db_session, second.id)["reason"] == reason
    if broken:
        bad = db_session.query(MapFeatureClaim).filter_by(run_id=first.id, status="quarantined").one()
        request = {"request_id": "repair-only-subset", "rows": [{"claim_id": bad.id, "values": {**BASE, "井号": "B"}}]}
        plan = retry_rows(db_session, first.id, request, preview=True)
        child, _ = retry_rows(db_session, first.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
        assert "ledger_declaration" not in child.table_metadata
        assert read_comparison(db_session, child.id)["reason"] == "correction_subset"
        assert read_comparison(db_session, second.id)["reason"] == "previous_rows_incomplete"


def test_scope_snapshot_and_current_permission_are_checked_without_count_leak(db_session):
    source, template = setup(db_session)
    load(db_session, source, template, [BASE, {**BASE, "井号": "B"}], declaration(8))
    second, _, _ = load(db_session, source, template, [BASE], declaration(9))
    assert _client(db_session, role="analyst").get(f"/api/map-ingest-runs/{second.id}/ledger-comparison").status_code == 403
    other = OperationalArea(code="other", name="其他范围", is_default=False, status="active")
    db_session.add(other); db_session.flush()
    db_session.query(JurisdictionAsset).filter_by(external_id="B").one().operational_area_id = other.id
    db_session.commit()
    db_session.info["authorized_area_ids"] = [source["operational_area"]["id"]]
    hidden = read_comparison(db_session, second.id)
    assert hidden["reason"] == "data_restricted_or_unavailable" and "missing_count" not in hidden and "missing" not in hidden
    db_session.info["authorized_area_ids"] = []
    with pytest.raises(ValueError, match="not_found"):
        read_comparison(db_session, second.id)
    db_session.info.pop("authorized_area_ids")
    db_session.query(MapSource).filter_by(id=source["id"]).one().status = "inactive"
    db_session.commit()
    with pytest.raises(ValueError, match="source_not_found"):
        read_comparison(db_session, second.id)


def test_declaration_is_bound_to_preview_and_idempotency(db_session):
    source, template = setup(db_session)
    scope = declaration(8)
    plan = preview(db_session, source, template, [BASE], scope)
    with pytest.raises(ValueError, match="plan_stale"):
        Service.ingest(db_session, source_id=source["id"], template_id=template.id, filename="synthetic.csv", content=csv_bytes([BASE]),
            source_revision="1", created_by=1, plan_token=plan["plan_token"], ledger_declaration={**scope, "scope_key": "different"})
    assert db_session.query(MapFeatureClaim).count() == 0
    client = _client(db_session)
    response = client.post(f"/api/map-sources/{source['id']}/preview", params={"template_id": template.id},
        files={"file": ("synthetic.csv", csv_bytes([BASE]), "text/csv")}, data={"ledger_declaration": json.dumps(scope)})
    assert response.status_code == 200 and response.json()["ledger_declaration"]["mode"] == "full"
    written = client.post(f"/api/map-sources/{source['id']}/ingest", params={"template_id": template.id, "source_revision": "API-synthetic"},
        files={"file": ("synthetic.csv", csv_bytes([BASE]), "text/csv")},
        data={"ledger_declaration": json.dumps(scope), "plan_token": response.json()["plan_token"]})
    assert written.status_code == 201 and written.json()["ledger_declaration"]["mode"] == "full"
    assert client.get(f"/api/map-ingest-runs/{written.json()['id']}/ledger-comparison").status_code == 200
    bad = client.post(f"/api/map-sources/{source['id']}/preview", params={"template_id": template.id},
        files={"file": ("synthetic.csv", csv_bytes([BASE]), "text/csv")}, data={"ledger_declaration": '{"mode":"full"}'})
    assert bad.status_code == 422


@pytest.mark.parametrize("change", [
    {"valid_from": "2026-08-01T00:00:00"}, {"valid_to": "2026-07-01T00:00:00+08:00"},
    {"scope_key": " "}, {"operational_area_id": 99}, {"mode": "inferred_full"},
])
def test_invalid_or_inferred_scope_is_rejected(change):
    with pytest.raises(ValueError, match="invalid_ledger_declaration"):
        parse_declaration(declaration(8, **change))
