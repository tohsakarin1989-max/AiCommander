"""Explicitly freeze a facility view; reads never compose another live dossier."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import require_area_write_access
from app.models.case import Case
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, MapSnapshot, MapFeatureClaim, JurisdictionAssetVersion
from app.models.internal_roads import InternalRoadImport
from app.models.result_material import FacilityMaterial
from app.services.facility_execution_context import freeze_facility_context
from app.services.facility_summary_service import read_dossier
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import _identity


SOURCE_MODELS = {'cases': Case, 'events': Event, 'assets': JurisdictionAsset,
                 'map_sources': MapSource, 'maps': MapSnapshot, 'road_imports': InternalRoadImport}


def _manifest(db):
    # Dossier totals and condition comparisons use the authorized collection,
    # including rows not in the displayed first page. Freeze that dependency
    # set conservatively, not just the visible examples.
    return {name: [row[0] for row in db.query(model.id).order_by(model.id)]
            for name, model in SOURCE_MODELS.items()}


def validate_sources(db, manifest):
    if 'authorized_area_ids' not in db.info or set(manifest) != set(SOURCE_MODELS):
        raise PermissionError('facility_material_sources_unavailable')
    for name, model in SOURCE_MODELS.items():
        ids = manifest[name]
        if not isinstance(ids, list):
            raise PermissionError('facility_material_sources_unavailable')
        for start in range(0, len(ids), 300):
            batch = ids[start:start + 300]
            visible = {row[0] for row in db.query(model.id).filter(model.id.in_(batch))}
            if visible != set(batch):
                raise PermissionError('facility_material_sources_unavailable')


def freeze_facility(db, asset_id, *, idempotency_key, start_date=None, end_date=None, valid_at=None, known_at=None,
                    valid_from=None, valid_to=None, knowledge_mode=None):
    user = _identity(db)
    if user.role not in {'admin', 'analyst'}:
        raise PermissionError('material_editor_required')
    asset = db.query(JurisdictionAsset).filter_by(id=asset_id).first()
    if asset is None:
        raise PermissionError('facility_material_unavailable')
    require_area_write_access(db, asset.operational_area_id)
    signature = result_hash(jsonable_encoder({'asset_id': asset_id, 'start_date': start_date,
        'end_date': end_date, 'valid_at': valid_at, 'known_at': known_at,
        **({'valid_from': valid_from, 'valid_to': valid_to, 'knowledge_mode': knowledge_mode}
           if any(value is not None for value in (valid_from, valid_to, knowledge_mode)) else {})}))
    prior = db.query(FacilityMaterial).filter_by(created_by=user.id, idempotency_key=idempotency_key).first()
    if prior is not None:
        if prior.request_sha256 != signature:
            raise ValueError('facility_material_idempotency_conflict')
        read_facility_material(db, prior.id)
        return prior, False
    context = freeze_facility_context(db, area_id=asset.operational_area_id,
                                      valid_at=valid_at, known_at=known_at, valid_from=valid_from,
                                      valid_to=valid_to, knowledge_mode=knowledge_mode)
    body = jsonable_encoder(read_dossier(db, asset_id, start_date=start_date, end_date=end_date, context=context))
    manifest = freeze_dossier_sources(db, body)
    # Capture source state, not arbitrary client payload. Context timestamp is
    # part of the material because historical effective conditions depend on it.
    body['versions']['read_mode'] = 'frozen_facility_material'
    digest = result_hash({'body': body, 'source_manifest': manifest})
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    created_id = str(uuid4())
    db.execute(insert(FacilityMaterial).values(id=created_id, asset_id=asset_id, created_by=user.id,
        title=f"设施材料 · {body['facility']['name']}", content_sha256=digest,
        idempotency_key=idempotency_key, request_sha256=signature,
        payload=body, source_manifest=manifest, created_at=datetime.now(timezone.utc))
        .on_conflict_do_nothing(index_elements=['created_by', 'idempotency_key']))
    row = db.query(FacilityMaterial).filter_by(created_by=user.id, idempotency_key=idempotency_key).first()
    if row is None or row.request_sha256 != signature:
        raise ValueError('facility_material_idempotency_conflict')
    read_facility_material(db, row.id)
    return row, row.id == created_id


def read_facility_material(db, identifier):
    row = db.query(FacilityMaterial).join(JurisdictionAsset,
        JurisdictionAsset.id == FacilityMaterial.asset_id).filter(FacilityMaterial.id == identifier).first()
    if row is None or result_hash({'body': row.payload, 'source_manifest': row.source_manifest}) != row.content_sha256:
        raise PermissionError('facility_material_unavailable')
    validate_dossier_sources(db, row.payload, row.source_manifest)
    return row, deepcopy(row.payload)


def freeze_dossier_sources(db, content):
    manifest = _manifest(db)
    content['versions']['map_manifest_hashes'] = {
        snapshot['id']: result_hash(db.query(MapSnapshot).filter_by(id=snapshot['id']).one().manifest)
        for snapshot in content['versions'].get('map_snapshots', [])}
    validate_dossier_sources(db, content, manifest)
    return manifest


def validate_dossier_sources(db, content, manifest):
    validate_sources(db, manifest)
    def validate_context(context):
        if not context or context.get('schema_version') != 'facility-temporal-7.3-1':
            return
        from app.services.facility_temporal_conditions import validate_temporal_access
        try:
            validate_temporal_access(db, context)
        except LookupError:
            raise PermissionError('facility_material_source_unavailable') from None

    validate_context(content.get('temporal_context'))
    # Check referenced immutable sources and current access without recomputing
    # the dossier. Old values remain old values after a legitimate source edit.
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_artifact_service import read_road_artifact
    from app.services.internal_road_service import read_import
    from app.models.report import Report
    from app.models.case_pipeline import CaseAnalysisProfile
    import re
    versions = content.get('versions', {})
    for identifier, digest in versions.get('map_manifest_hashes', {}).items():
        snapshot = db.query(MapSnapshot).filter_by(id=identifier).first()
        if snapshot is None or result_hash(snapshot.manifest) != digest:
            raise PermissionError('facility_material_map_changed')
    for identifier in versions.get('source_claim_ids', []):
        claim = db.query(MapFeatureClaim).filter_by(id=identifier).first()
        if claim is None or db.query(MapSource.id).filter_by(id=claim.source_id, status='active').first() is None:
            raise PermissionError('facility_material_source_unavailable')
    for identifier in versions.get('asset_version_ids', []):
        version = db.query(JurisdictionAssetVersion).filter_by(id=identifier).first()
        allowed = db.info['authorized_area_ids']
        if version is None or (allowed is not None and (version.snapshot or {}).get('operational_area_id') not in allowed):
            raise PermissionError('facility_material_source_unavailable')
    for section in content['sections'].values():
        for item in section.get('items', []):
            # Historical case conditions can depend on a different source than
            # the top-level facility view. Recheck each frozen context, not only
            # the currently selected point, without recomputing old values.
            validate_context(item.get('source_context'))
            profile_id = item.get('profile_id')
            if profile_id and db.query(CaseAnalysisProfile.id).filter_by(id=profile_id).first() is None:
                raise PermissionError('facility_material_source_unavailable')
            for ref in item.get('evidence_refs', []):
                if ref.startswith('case_result:'):
                    CaseResultService.read(db, ref.split(':', 1)[1])
                elif ref.startswith('road_artifact:'):
                    read_road_artifact(db, ref.split(':', 1)[1])
                elif ref.startswith('report:'):
                    from app.services.meeting_frozen_service import require_report_sources
                    report = db.query(Report).filter_by(id=int(ref.split(':')[1])).first()
                    if report is None:
                        raise PermissionError('facility_material_source_unavailable')
                    require_report_sources(db, report)
                elif match := re.fullmatch(r'internal_road_entrance:([^:]+):(.+)', ref):
                    read_import(db, match[1])
