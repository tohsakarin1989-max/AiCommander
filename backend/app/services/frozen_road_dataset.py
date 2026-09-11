"""Internal immutable road evaluation datasets, reusing governance storage.

Capture only existing authorized artifacts. No client supplied graph, coordinates,
file paths or calculated results are accepted. The caller owns the transaction.
"""
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.governance import EvaluationDataset
from app.services.frozen_insight_inputs import checksum
from app.services.frozen_road_inputs import capture_road_inputs, validate_road_inputs

SCHEMA = 'fixed-road-evaluation-4.5-1'


def read_dataset(db, dataset_id):
    dataset = db.query(EvaluationDataset).filter_by(id=dataset_id).populate_existing().first()
    if dataset is None or dataset.manifest.get('schema') != SCHEMA:
        raise ValueError('fixed_road_dataset_not_found')
    manifest = dataset.manifest
    if checksum(manifest) != dataset.checksum or dataset.ground_truth != {}:
        raise ValueError('fixed_road_dataset_integrity_failure')
    case_ids = set()
    for envelope in manifest['entries']:
        validate_road_inputs(db, envelope)
        artifact = db.get(CaseRoadArtifact, envelope['payload']['artifact_id'], populate_existing=True)
        if artifact is None:
            raise PermissionError('fixed_road_source_unavailable')
        case_ids.add(artifact.case_id)
    if sorted(case_ids) != sorted(dataset.case_ids):
        raise ValueError('fixed_road_dataset_case_binding_changed')
    return dataset


def create_dataset(db, *, name, version, artifact_ids, artifact_root, verify_files=True):
    if not name.strip() or len(name.strip()) > 200 or not version.strip() or len(version.strip()) > 80:
        raise ValueError('invalid_dataset_identity')
    if not 1 <= len(artifact_ids) <= 10 or len(set(artifact_ids)) != len(artifact_ids):
        raise ValueError('invalid_road_dataset_size')
    entries = [capture_road_inputs(db, identifier, artifact_root=artifact_root, verify_files=verify_files)
               for identifier in sorted(artifact_ids)]
    manifest = {'schema': SCHEMA, 'classification': 'internal_sensitive', 'entries': entries,
                'boundary': '固定参考路径与矩阵输入；未标注正确性，不计准确率，不代表实际行驶轨迹。'}
    digest = checksum(manifest)
    existing = db.query(EvaluationDataset).filter_by(name=name.strip(), version=version.strip()).first()
    if existing:
        # Recheck authorization before even returning an idempotent existing row.
        if existing.manifest.get('schema') != SCHEMA or existing.checksum != digest:
            raise ValueError('dataset_version_conflict')
        return read_dataset(db, existing.id)
    case_ids = sorted({db.get(CaseRoadArtifact, identifier).case_id for identifier in artifact_ids})
    row = EvaluationDataset(name=name.strip(), version=version.strip(), classification='internal_sensitive',
        case_ids=case_ids, ground_truth={}, manifest=manifest, checksum=digest,
        created_by=db.info.get('principal_user_id'))
    db.add(row)
    db.flush()
    return read_dataset(db, row.id)
