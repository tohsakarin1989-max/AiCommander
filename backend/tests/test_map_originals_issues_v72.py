"""Synthetic source bytes and scoped observations, no live database/files."""
from hashlib import sha256

import pytest

from app.api import jurisdiction, map_ingest_originals
from app.models.case_source import EvidenceObject
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.models.map_foundation import (
    JurisdictionAssetVersion, MapFeatureClaim, MapImportTemplate, MapIngestRun,
    MapSource, OperationalArea,
)
from app.services.map_ingest_originals import capture_original, claim_provenance, original_metadata
from app.services.map_data_issues import list_issues, record_issue
from app.services.jurisdiction_service import JurisdictionService
from test_map_foundation import db_session, _client  # noqa: F401


@pytest.fixture
def ledger(db_session):
    db = db_session
    content = '井号,井名,经度,纬度\nW-1,合成井,125.1,46.2\n'.encode()
    db.add_all([OperationalArea(id=1, code="original-area", name="合成厂区"),
                OperationalArea(id=2, code="hidden-area", name="其他厂区")])
    db.flush()
    source = MapSource(id=1, source_key="original-test", name="合成台账", source_type="ledger", operational_area_id=1)
    db.add(source)
    db.flush()
    template = MapImportTemplate(id=1, source_id=1, name="合成模板", coordinate_system="wgs84",
                                 field_mapping={"external_id": "井号", "name": "井名", "longitude": "经度", "latitude": "纬度"})
    db.add(template)
    db.flush()
    run = MapIngestRun(id="original-test", source_id=1, template_id=1, filename="合成台账.csv",
                      source_revision="sample-1", file_hash=sha256(content).hexdigest(), idempotency_key="original-test",
                      table_metadata={"sheet_name": None, "header_row": 1, "headers": ["井号", "井名", "经度", "纬度"]},
                      template_snapshot={"field_mapping": template.field_mapping})
    asset = JurisdictionAsset(id=1, operational_area_id=1, name="合成井", asset_type="well", external_id="W-1",
                              attributes={"source_id": 1}, source_claim_refs=[1])
    db.add_all([run, asset])
    db.flush()
    claim = MapFeatureClaim(id=1, run_id=run.id, source_id=1, row_number=2, source_revision="sample-1",
                            raw_payload={"井号": "W-1"}, raw_hash="sample-row", status="published", asset_id=1)
    db.add(claim)
    db.flush()
    version = JurisdictionAssetVersion(id=1, asset_id=1, version=1, source_claim_id=1, change_type="created",
                                      snapshot={"operational_area_id": 1, "attributes": {"source_id": 1}})
    db.add(version)
    db.commit()
    db.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"}, principal_user_id=1)
    return db, run, content, asset, claim


def http(db, role="admin"):
    result = _client(db, role)
    result.app.include_router(map_ingest_originals.router, prefix="/api")
    result.app.include_router(jurisdiction.router, prefix="/api/jurisdiction")
    return result


def test_original_capture_is_atomic_and_idempotent(ledger):
    db, run, content, *_ = ledger
    capture_original(db, run, content=content, filename=run.filename)
    capture_original(db, run, content=content, filename=run.filename)
    db.flush()
    assert db.query(EvidenceObject).count() == 1
    db.rollback()
    assert db.query(EvidenceObject).count() == 0
    assert db.get(MapIngestRun, run.id).original_evidence_object_id is None
    capture_original(db, run, content=content, filename=run.filename)
    db.commit()
    response = http(db).get(f"/api/map-ingest-runs/{run.id}/original")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]
    assert "attachment;" in response.headers["content-disposition"]


def test_original_missing_revoked_or_corrupted_is_not_downloaded(ledger):
    db, run, content, *_ = ledger
    client = http(db)
    assert original_metadata(db, run)["state"] == "metadata_only"
    assert client.get(f"/api/map-ingest-runs/{run.id}/original").status_code == 409
    with pytest.raises(ValueError, match="original_hash_mismatch"):
        capture_original(db, run, content=b"different", filename="different.csv")
    assert db.query(EvidenceObject).count() == 0
    capture_original(db, run, content=content, filename=run.filename)
    db.commit()
    obj = db.get(EvidenceObject, run.original_evidence_object_id)
    obj.content = b"corrupted"
    db.commit()
    assert client.get(f"/api/map-ingest-runs/{run.id}/original").status_code == 409
    obj.content, obj.availability = content, "revoked"
    db.commit()
    assert client.get(f"/api/map-ingest-runs/{run.id}/original").status_code == 409


def test_entire_ledger_requires_admin_and_current_source_scope(ledger):
    db, run, content, *_ = ledger
    capture_original(db, run, content=content, filename=run.filename)
    db.commit()
    assert http(db, "analyst").get(f"/api/map-ingest-runs/{run.id}/original").status_code == 403
    client = http(db)
    db.info["authorized_area_ids"] = (2,)
    response = client.get(f"/api/map-ingest-runs/{run.id}/original")
    assert response.status_code == 404 and "合成井" not in response.text
    db.info["authorized_area_ids"] = (1,)
    db.get(MapSource, 1).status = "inactive"
    db.commit()
    assert client.get(f"/api/map-ingest-runs/{run.id}/original").status_code == 404


def test_original_locator_uses_frozen_template_not_current_guess(ledger):
    db, run, _, _, claim = ledger
    trace = claim_provenance(db, claim)
    assert trace["locator_state"] == "recorded"
    assert trace["columns"][2] == {"field": "longitude", "column": "经度", "column_number": 3, "cell": None}
    template = db.get(MapImportTemplate, 1)
    template.field_mapping = {"longitude": "错误新列"}
    db.commit()
    assert claim_provenance(db, claim)["columns"] == trace["columns"]
    run.table_metadata = None
    db.commit()
    assert claim_provenance(db, claim)["locator_state"] == "legacy_unrecorded"


def issue_payload(**overrides):
    return {"asset_id": 1, "feedback_type": "data_issue", "notes": "合成原件中单位列需核对",
            "source_reference": {"field_group": "production", "source_claim_id": 1, "asset_version_id": 1},
            **overrides}


def test_employee_issue_records_source_without_changing_facility_or_scores(ledger):
    db, _, _, asset, claim = ledger
    before = dict(asset.attributes), claim.status, db.query(JurisdictionAssetVersion).count()
    response = http(db, "analyst").post("/api/jurisdiction/feedback", json=issue_payload(
        adopted=True, result="不得作为事实", extra={"actor_id": 999, "state": "verified"},
    ))
    assert response.status_code == 200, response.text
    value = response.json()
    assert not value["adopted"] and value["result"] is None
    assert value["extra"]["actor_id"] == 1 and value["extra"]["state"] == "reported"
    assert (asset.attributes, claim.status, db.query(JurisdictionAssetVersion).count()) == before
    assert JurisdictionService.summarize_effectiveness(db)["total_feedback"] == 0
    listing = http(db).get("/api/jurisdiction/data-issues?asset_id=1&page_size=1")
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert listing.headers["cache-control"] == "no-store"


def test_issue_foreign_or_unknown_reference_rejected_and_input_can_be_corrected(ledger):
    db, *_ = ledger
    client = http(db, "analyst")
    missing = client.post("/api/jurisdiction/feedback", json=issue_payload(source_reference={"field_group": "production"}))
    assert missing.status_code == 422
    foreign = client.post("/api/jurisdiction/feedback", json=issue_payload(
        source_reference={"field_group": "production", "source_claim_id": 999},
    ))
    assert foreign.status_code == 404
    assert db.query(JurisdictionFeedback).count() == 0
    db.info["area_access_levels"] = {1: "read"}
    with pytest.raises(PermissionError):
        record_issue(db, issue_payload())
    assert db.query(JurisdictionFeedback).count() == 0


def test_source_revocation_hides_issue_notes_and_count_before_pagination(ledger):
    db, *_ = ledger
    record_issue(db, issue_payload())
    assert list_issues(db, 1, page=1, page_size=1)["total"] == 1
    db.get(MapSource, 1).status = "inactive"
    db.commit()
    value = list_issues(db, 1, page=1, page_size=1)
    assert value["total"] == 0 and value["items"] == []
    assert "合成原件" not in str(value)


@pytest.mark.parametrize("change", ["inactive", "other_area"])
@pytest.mark.parametrize("reference_kind", ["version", "claim"])
def test_mixed_group_source_revocation_hides_version_issue_and_production(ledger, change, reference_kind):
    from app.services.facility_dossier_content import _production
    db, _, _, asset, claim = ledger
    source = MapSource(id=2, source_key="mixed-group", name="独立测量来源", source_type="ledger", operational_area_id=1)
    db.add(source)
    asset.attributes = {"source_id": 1, "water_cut_min": 42,
                        "field_groups": {"water_cut": {"source_id": 2, "state": "set"}}}
    version = db.get(JurisdictionAssetVersion, 1)
    # Synthetic fixture arrangement, never an application update of a version.
    db.execute(JurisdictionAssetVersion.__table__.update().where(JurisdictionAssetVersion.id == 1).values(
        snapshot={"operational_area_id": 1, "attributes": asset.attributes},
    ))
    db.commit()
    db.expire(version)
    claim.normalized_payload = {"attributes": asset.attributes}
    db.commit()
    reference = {"asset_version_id": 1} if reference_kind == "version" else {"source_claim_id": 1}
    record_issue(db, issue_payload(source_reference={"field_group": "water_cut", **reference}))
    assert list_issues(db, 1, page=1, page_size=1)["total"] == 1
    if change == "inactive":
        source.status = "inactive"
    else:
        source.operational_area_id = 2
    db.commit()
    response = list_issues(db, 1, page=1, page_size=1)
    assert response["total"] == 0 and response["items"] == []
    production, versions = _production(db, asset)
    assert production["state"] == "restricted" and "items" not in production and "total" not in production
    assert not versions
