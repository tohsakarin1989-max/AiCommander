"""Facility identity is source scoped; names and proximity are not identity."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, OperationalArea
from app.services.jurisdiction_service import JurisdictionService
from app.services.map_foundation_service import MapFoundationService


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


def _payload(**changes):
    return {
        "name": "同名井", "asset_type": "well", "source": "ledger",
        "external_id": "W-1", "latitude": 46.6, "longitude": 125.1,
        **changes,
    }


def test_legacy_import_different_identifiers_never_merge_by_name(db):
    first, _ = JurisdictionService._upsert_asset(db, _payload())
    second, created = JurisdictionService._upsert_asset(db, _payload(external_id="W-2"))
    db.commit()
    assert created
    assert first.id != second.id
    assert first.external_id == "W-1"
    assert db.query(JurisdictionAsset).count() == 2


def test_legacy_import_identifier_updates_only_its_source_and_area(db):
    areas = [OperationalArea(code=f"area-{i}", name=f"厂区{i}") for i in range(2)]
    db.add_all(areas)
    db.commit()
    first, _ = JurisdictionService._upsert_asset(db, _payload(operational_area_id=areas[0].id))
    other_source, _ = JurisdictionService._upsert_asset(
        db, _payload(operational_area_id=areas[0].id, source="manual"),
    )
    other_area, _ = JurisdictionService._upsert_asset(db, _payload(operational_area_id=areas[1].id))
    changed, created = JurisdictionService._upsert_asset(
        db, _payload(operational_area_id=areas[0].id, name="新井名"),
    )
    db.commit()
    assert not created and changed.id == first.id
    assert other_source.id != first.id != other_area.id
    assert other_source.name == other_area.name == "同名井"


def test_geojson_names_are_not_fabricated_external_ids_and_geometry_is_not_merged(db):
    def feature(longitude):
        return {
            "type": "Feature", "properties": {"name": "同名便道", "asset_type": "road"},
            "geometry": {"type": "LineString", "coordinates": [[longitude, 46.6], [longitude, 46.61]]},
        }
    collection = {"type": "FeatureCollection", "features": [feature(125.1), feature(125.10001)]}
    first = JurisdictionService.import_geojson(db, collection)
    second = JurisdictionService.import_geojson(db, collection)
    assert first["created"] == 2
    assert second["created"] == 0
    assert db.query(JurisdictionAsset).count() == 2
    assert all(asset.external_id is None for asset in db.query(JurisdictionAsset))
    assert all(asset.verification_state == "identity_pending" for asset in db.query(JurisdictionAsset))


def test_ambiguous_legacy_identifier_is_rejected_without_overwriting(db):
    db.add_all([JurisdictionAsset(**_payload()), JurisdictionAsset(**_payload())])
    db.commit()
    with pytest.raises(ValueError, match="ambiguous_asset_identity"):
        JurisdictionService._upsert_asset(db, _payload(name="不可覆盖"))
    assert all(asset.name == "同名井" for asset in db.query(JurisdictionAsset))


def test_manual_create_and_rename_keep_observed_versions_without_claim(db):
    asset = JurisdictionService.create_asset(db, _payload(source="manual", attributes={"aliases": ["旧称"]}))
    JurisdictionService.update_asset(db, asset.id, {"name": "新井名", "attributes": {"aliases": ["旧称", "同名井"]}})
    versions = db.query(JurisdictionAssetVersion).order_by(JurisdictionAssetVersion.version).all()
    assert [version.version for version in versions] == [1, 2]
    assert [version.snapshot["name"] for version in versions] == ["同名井", "新井名"]
    assert versions[0].snapshot["attributes"] == {"aliases": ["旧称"]}
    assert all(version.source_claim_id is None for version in versions)


def test_legacy_unversioned_asset_records_only_observed_baseline_and_new_value(db):
    asset = JurisdictionAsset(**_payload())
    db.add(asset)
    db.commit()
    JurisdictionService.update_asset(db, asset.id, {"name": "新井名"})
    versions = db.query(JurisdictionAssetVersion).order_by(JurisdictionAssetVersion.version).all()
    assert [version.change_type for version in versions] == ["baseline_observed", "manual_updated"]
    assert [version.snapshot["name"] for version in versions] == ["同名井", "新井名"]


def test_uncommitted_asset_update_versions_are_rolled_back_with_business_change(db):
    asset = JurisdictionService.create_asset(db, _payload(source="manual"))
    asset_id = asset.id
    JurisdictionService.update_asset(db, asset_id, {"name": "取消修改"}, commit=False)
    db.rollback()
    assert db.get(JurisdictionAsset, asset_id).name == "同名井"
    assert db.query(JurisdictionAssetVersion).count() == 1


def _ingest(db, source_key, row, revision="rev-1"):
    from app.models.map_foundation import MapImportTemplate, MapSource

    source = db.query(MapSource).filter_by(source_key=source_key).first()
    if source is None:
        source = MapFoundationService.create_source(db, {
            "source_key": source_key, "name": source_key, "source_type": "ledger",
        })
        template = MapFoundationService.create_template(db, {
            "source_id": source.id, "name": "模板", "coordinate_system": "wgs84",
            "field_mapping": {key: key for key in ("external_id", "name", "asset_type", "longitude", "latitude")},
        })
    else:
        template = db.query(MapImportTemplate).filter_by(source_id=source.id).one()
    return MapFoundationService.ingest(
        db, source_id=source.id, template_id=template.id, filename="wells.csv",
        content=("external_id,name,asset_type,longitude,latitude\n" + row + "\n").encode(),
        source_revision=revision, created_by=None,
    )[0]


def test_governed_source_identifier_preserves_rename_update_and_versions(db):
    _ingest(db, "ledger-a", "W-1,旧井名,well,125.1,46.6")
    first = db.query(JurisdictionAsset).one()
    stable_id = first.id
    run = _ingest(db, "ledger-a", "W-1,新井名,well,125.101,46.601", "rev-2")
    assert run.updated_assets == 1 and run.created_assets == 0
    assert db.query(JurisdictionAsset).one().id == stable_id
    versions = db.query(JurisdictionAssetVersion).order_by(JurisdictionAssetVersion.version).all()
    assert [item.snapshot["name"] for item in versions] == ["旧井名", "新井名"]
    assert all(item.source_claim_id for item in versions)


def test_same_number_in_independent_sources_does_not_merge(db):
    _ingest(db, "ledger-a", "W-1,同名井,well,125.1,46.6")
    _ingest(db, "ledger-b", "W-1,同名井,well,125.1,46.6")
    assert db.query(JurisdictionAsset).count() == 2


def test_no_identifier_keeps_exact_source_fingerprint_and_pending_state(db):
    _ingest(db, "ledger-a", ",同名井,well,125.1,46.6")
    _ingest(db, "ledger-a", ",同名井,well,125.1,46.6", "rev-2")
    assert db.query(JurisdictionAsset).count() == 1
    _ingest(db, "ledger-b", ",同名井,well,125.1,46.6")
    _ingest(db, "ledger-a", ",同名井,well,125.10001,46.60001", "rev-3")
    assert db.query(JurisdictionAsset).count() == 3
    assert all(not asset.verified and asset.verification_state == "identity_pending" for asset in db.query(JurisdictionAsset))


def test_legacy_generic_source_cannot_overwrite_registered_source_asset(db):
    _ingest(db, "ledger-a", "W-1,受管井,well,125.1,46.6")
    asset = db.query(JurisdictionAsset).one()
    with pytest.raises(ValueError, match="asset_identity_namespace_required"):
        JurisdictionService._upsert_asset(db, _payload(name="不可覆盖", operational_area_id=asset.operational_area_id))
    assert db.query(JurisdictionAsset).one().name == "受管井"


def test_source_identifiers_are_not_assumed_case_or_whitespace_equivalent(db):
    _ingest(db, "ledger-a", "W-1,同名井,well,125.1,46.6")
    _ingest(db, "ledger-a", "w-1,同名井,well,125.1,46.6", "rev-2")
    _ingest(db, "ledger-a", "W -1,同名井,well,125.1,46.6", "rev-3")
    assert db.query(JurisdictionAsset).count() == 3


@pytest.mark.parametrize("external_id", ["W-1", ""])
def test_pre_v54_canonical_key_is_adopted_only_with_exact_source_identity(db, external_id):
    _ingest(db, "ledger-a", f"{external_id},同名井,well,125.1,46.6")
    asset = db.query(JurisdictionAsset).one()
    stable_id = asset.id
    asset.canonical_key = "area:1:pre-v54-key"
    db.commit()
    _ingest(db, "ledger-a", f"{external_id},同名井,well,125.1,46.6", "rev-2")
    assert db.query(JurisdictionAsset).count() == 1
    assert db.query(JurisdictionAsset).one().id == stable_id


def test_asset_bulk_create_preserves_source_values_in_versions(db):
    result = JurisdictionService.bulk_create_assets(db, [_payload(), _payload(external_id="W-2")])
    assert result["created"] == 2
    versions = db.query(JurisdictionAssetVersion).all()
    assert len(versions) == 2
    assert {version.snapshot["external_id"] for version in versions} == {"W-1", "W-2"}


def test_unidentified_governed_import_cannot_overwrite_later_human_verification(db):
    _ingest(db, "ledger-a", ",同名井,well,125.1,46.6")
    asset = db.query(JurisdictionAsset).one()
    JurisdictionService.update_asset(db, asset.id, {"verified": True, "description": "人工核验"})
    run = _ingest(db, "ledger-a", ",同名井,well,125.1,46.6", "rev-2")
    assert run.quarantined_rows == 1 and run.updated_assets == 0
    assert db.query(JurisdictionAsset).one().verified is True
    assert db.query(JurisdictionAsset).one().description == "人工核验"


def test_unidentified_legacy_import_cannot_overwrite_later_human_verification(db):
    asset, _ = JurisdictionService._upsert_asset(db, _payload(external_id=None))
    db.commit()
    JurisdictionService.update_asset(db, asset.id, {"verified": True})
    with pytest.raises(ValueError, match="asset_identity_requires_review"):
        JurisdictionService._upsert_asset(db, _payload(external_id=None))
    assert db.query(JurisdictionAsset).one().verified is True
