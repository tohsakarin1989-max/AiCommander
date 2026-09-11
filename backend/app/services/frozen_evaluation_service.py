"""Persisted internal evaluation inputs and scorer runs; never external data."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.models.case import Case
from app.models.governance import EvaluationDataset, EvaluationRun
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, OperationalArea
from app.services.frozen_insight_inputs import capture_inputs, checksum, replay_inputs, scorer_checksum
from app.services.case_insight_service import CASE_INSIGHT_ALGORITHM_VERSION
from app.services.governance_service import GovernanceService
from app.services.evaluation_diagnostics import candidate_observations

SCHEMA = 'fixed-evaluation-4.5-1'


def authorize_inputs(db, entries):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('evaluation_scope_required')
    allowed = db.info['authorized_area_ids']
    for envelope in entries:
        payload = envelope['payload']
        area = payload['case']['operational_area_id']
        if (allowed is not None and area not in allowed) or not db.query(OperationalArea.id).filter_by(id=area, status='active').first():
            raise PermissionError('evaluation_source_unavailable')
        case_ids = set(payload['source_case_ids'])
        visible = {row[0] for row in db.query(Case.id).filter(Case.id.in_(case_ids), Case.operational_area_id == area)}
        asset_ids = set(payload['source_asset_ids']) | set(payload.get('label_asset_ids', []))
        assets = {row[0] for row in db.query(JurisdictionAsset.id).filter(
            JurisdictionAsset.id.in_(asset_ids), JurisdictionAsset.operational_area_id == area)}
        snapshot = db.query(MapSnapshot.id).filter_by(id=payload['map']['id'], operational_area_id=area).first()
        if visible != case_ids or assets != asset_ids or snapshot is None:
            raise PermissionError('evaluation_source_unavailable')


def create_dataset(db, *, name, version, inputs, ground_truth=None, negative_case_ids=(), created_by=None, origin=None):
    if not name.strip() or len(name.strip()) > 200 or not version.strip() or len(version.strip()) > 80:
        raise ValueError('invalid_dataset_identity')
    case_ids = [item['case_id'] for item in inputs]
    if not 1 <= len(inputs) <= 100 or len(set(case_ids)) != len(case_ids):
        raise ValueError('invalid_frozen_dataset_size')
    labels = GovernanceService._normalize_ground_truth(ground_truth or {}, case_ids)
    negatives = sorted(set(negative_case_ids))
    if not set(negatives) <= set(case_ids) or set(negatives) & {int(key) for key in labels}:
        raise ValueError('conflicting_or_unknown_negative_labels')
    entries = [capture_inputs(db, **item) for item in sorted(inputs, key=lambda item: item['case_id'])]
    for envelope in entries:
        payload = envelope['payload']
        payload['label_asset_ids'] = sorted({identifier
            for label in labels.get(str(payload['case']['id']), []) for identifier in label['expected_asset_ids']})
        envelope['checksum'] = checksum(payload)
    authorize_inputs(db, entries)
    manifest = {'schema': SCHEMA, 'classification': 'internal_sensitive', 'entries': entries,
                'labels': labels, 'negative_case_ids': negatives,
                'boundary': '冻结检索输入的生产评分评测，不是完整机动车路网重放；阴性标签代表人工明确标注无候选。'}
    if origin is not None:
        manifest['origin'] = deepcopy(origin)
    fingerprint = checksum(manifest)
    existing = db.query(EvaluationDataset).filter_by(name=name.strip(), version=version.strip()).first()
    if existing:
        if existing.checksum != fingerprint:
            raise ValueError('dataset_version_conflict')
        return existing
    dataset = EvaluationDataset(name=name.strip(), version=version.strip(), classification='internal_sensitive',
        case_ids=sorted(case_ids), ground_truth=deepcopy(labels), manifest=manifest, checksum=fingerprint, created_by=created_by)
    db.add(dataset)
    db.commit()
    return dataset


def create_from_result(db, *, result_id, expected_checksum, name, version, created_by=None):
    """Archive current source + archive-time retrieval, not unrecorded historic context."""
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_result_service import CaseResultService
    result = CaseResultService.read(db, result_id)
    if result['content_sha256'] != expected_checksum:
        raise ValueError('evaluation_result_changed')
    content = result['content']
    versions = content['versions']
    case = db.query(Case).filter_by(id=content['case_id']).populate_existing().one()
    profile = db.query(CaseAnalysisProfile).filter_by(id=versions['case_profile_id']).populate_existing().one()
    if (not profile.is_current or not versions['map_snapshot_id']
            or CasePipelineService.source_hash(db, case) != versions['case_source_hash']):
        raise ValueError('evaluation_result_is_not_current')
    return create_dataset(db, name=name, version=version,
        inputs=[{'case_id': case.id, 'profile_id': profile.id, 'snapshot_id': versions['map_snapshot_id']}],
        created_by=created_by, origin={'result_id': result_id, 'result_checksum': expected_checksum,
            'retrieval_context': 'archive_time', 'labels': 'unlabeled'})


def read_dataset(db, dataset_id):
    dataset = db.query(EvaluationDataset).filter_by(id=dataset_id).populate_existing().first()
    if dataset is None or dataset.manifest.get('schema') != SCHEMA:
        raise ValueError('fixed_dataset_not_found')
    manifest = dataset.manifest
    if (checksum(manifest) != dataset.checksum or dataset.ground_truth != manifest['labels']
            or sorted(dataset.case_ids) != sorted(item['payload']['case']['id'] for item in manifest['entries'])):
        raise ValueError('fixed_dataset_integrity_failure')
    authorize_inputs(db, manifest['entries'])
    return dataset


def revise_labels(db, dataset_id, *, version, ground_truth, negative_case_ids, reason, created_by=None):
    """New immutable label version, preserving captured queries without live retrieval."""
    source = read_dataset(db, dataset_id)
    if not version.strip() or len(version.strip()) > 80 or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError('invalid_label_revision')
    labels = GovernanceService._normalize_ground_truth(ground_truth, source.case_ids)
    negatives = sorted(set(negative_case_ids))
    if not set(negatives) <= set(source.case_ids) or set(negatives) & {int(key) for key in labels}:
        raise ValueError('conflicting_or_unknown_negative_labels')
    manifest = deepcopy(source.manifest)
    manifest['labels'], manifest['negative_case_ids'] = labels, negatives
    manifest['label_revision'] = {'parent_id': source.id, 'parent_checksum': source.checksum,
        'reason': reason.strip(), 'reviewer_id': created_by,
        'policy': 'explicit_replacement_unmentioned_cases_remain_unlabeled'}
    for envelope in manifest['entries']:
        payload = envelope['payload']
        payload['label_asset_ids'] = sorted({identifier for label in labels.get(str(payload['case']['id']), [])
                                             for identifier in label['expected_asset_ids']})
        envelope['checksum'] = checksum(payload)
    authorize_inputs(db, manifest['entries'])
    digest = checksum(manifest)
    existing = db.query(EvaluationDataset).filter_by(name=source.name, version=version.strip()).first()
    if existing:
        if existing.checksum != digest:
            raise ValueError('dataset_version_conflict')
        return read_dataset(db, existing.id)
    revised = EvaluationDataset(name=source.name, version=version.strip(), classification='internal_sensitive',
        case_ids=deepcopy(source.case_ids), ground_truth=deepcopy(labels), manifest=manifest,
        checksum=digest, created_by=created_by)
    db.add(revised)
    db.commit()
    return revised


def run_evaluation(db, dataset_id, *, scorer_policy='captured'):
    if scorer_policy not in ('captured', 'current_candidate'):
        raise ValueError('invalid_scorer_policy')
    dataset = read_dataset(db, dataset_id)
    manifest = dataset.manifest
    labels, negatives = manifest['labels'], set(manifest['negative_case_ids'])
    records = []
    positive_hits = negative_correct = 0
    for envelope in manifest['entries']:
        case_id = envelope['payload']['case']['id']
        try:
            result = replay_inputs(envelope) if scorer_policy == 'captured' else replay_inputs(envelope, scorer_policy=scorer_policy)
            candidates = result['candidates']
            positive = labels.get(str(case_id))
            hit = any(GovernanceService._hypothesis_matches_ground_truth(SimpleNamespace(**candidate), label)
                      for candidate in candidates for label in (positive or []))
            positive_hits += bool(hit)
            negative_correct += case_id in negatives and result['status'] == 'empty'
            record = {'case_id': case_id, 'status': result['status'], 'candidate_count': len(candidates),
                'label_state': 'positive' if positive else 'negative' if case_id in negatives else 'unlabeled',
                'correct': bool(hit) if positive else result['status'] == 'empty' if case_id in negatives else None,
                'candidate_observations': candidate_observations(candidates, positive or [], case_id in negatives),
                'candidate_checksum': checksum(candidates), 'input_checksum': envelope['checksum']}
        except (ValueError, RuntimeError, TypeError, KeyError, AttributeError):
            record = {'case_id': case_id, 'status': 'failed', 'candidate_count': 0,
                'label_state': 'positive' if str(case_id) in labels else 'negative' if case_id in negatives else 'unlabeled',
                'correct': False if str(case_id) in labels or case_id in negatives else None,
                'failure_reason': 'frozen_replay_failed', 'input_checksum': envelope['checksum']}
        records.append(record)
    failures = sum(row['status'] == 'failed' for row in records)
    positive_count, negative_count = len(labels), len(negatives)
    metrics = {'case_count': len(records), 'failed_case_count': failures,
        'empty_case_count': sum(row['status'] == 'empty' for row in records),
        'unlabeled_case_count': sum(row['label_state'] == 'unlabeled' for row in records),
        'positive_case_count': positive_count, 'negative_case_count': negative_count,
        'positive_top3_hit_rate': positive_hits / positive_count if positive_count else None,
        'negative_correct_empty_rate': negative_correct / negative_count if negative_count else None,
        'metric_basis': SCHEMA, 'score_kind': 'rule_support_not_calibrated_probability'}
    # Reauthorize before persistence; there are no source writes or execution tasks.
    authorize_inputs(db, manifest['entries'])
    trace = {'dataset_checksum': dataset.checksum, 'records': records, 'records_checksum': checksum(records)}
    versions = sorted({entry['payload']['algorithm_version'] for entry in manifest['entries']}) if scorer_policy == 'captured' else [CASE_INSIGHT_ALGORITHM_VERSION]
    implementations = []
    for version in versions:
        try:
            fingerprint = scorer_checksum(version)
        except ValueError:
            fingerprint = None
        implementations.append({'version': version, 'code_checksum': fingerprint})
    algorithm = {'scorer_checksum': checksum(implementations), 'implementations': implementations,
                 'evaluation_schema': SCHEMA, 'scorer_policy': scorer_policy}
    algorithm['result_checksum'] = checksum({'metrics': metrics, 'trace': trace, 'algorithm': deepcopy(algorithm)})
    run = EvaluationRun(id=str(uuid4()), dataset_id=dataset.id,
        algorithm_manifest=algorithm,
        scope_policy_version='current-area-source-check-4.5-1', status='partial_failure' if failures else 'completed',
        metrics=metrics, trace_manifest=trace, completed_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    return run


def _verified_run(db, run_id):
    run = db.query(EvaluationRun).filter_by(id=run_id).populate_existing().first()
    if run is None or run.algorithm_manifest.get('evaluation_schema') != SCHEMA:
        raise ValueError('fixed_run_not_found')
    dataset = read_dataset(db, run.dataset_id)
    algorithm = deepcopy(run.algorithm_manifest)
    expected = algorithm.pop('result_checksum', None)
    if (expected != checksum({'metrics': run.metrics, 'trace': run.trace_manifest, 'algorithm': algorithm})
            or run.trace_manifest['dataset_checksum'] != dataset.checksum
            or checksum(run.trace_manifest['records']) != run.trace_manifest['records_checksum']):
        raise ValueError('fixed_run_integrity_failure')
    return run, dataset


def read_run(db, run_id):
    return _verified_run(db, run_id)[0]


def compare_runs(db, baseline_id, candidate_id):
    baseline, old_dataset = _verified_run(db, baseline_id)
    candidate, new_dataset = _verified_run(db, candidate_id)
    if old_dataset.checksum != new_dataset.checksum:
        raise ValueError('evaluation_inputs_or_labels_differ')
    old = {row['case_id']: row for row in baseline.trace_manifest['records']}
    new = {row['case_id']: row for row in candidate.trace_manifest['records']}
    expected = set(old_dataset.case_ids)
    if (set(old) != expected or set(new) != expected
            or len(baseline.trace_manifest['records']) != len(expected)
            or len(candidate.trace_manifest['records']) != len(expected)):
        raise ValueError('evaluation_case_population_differs')
    rows = []
    for case_id in sorted(expected):
        left, right = old[case_id], new[case_id]
        if left['input_checksum'] != right['input_checksum'] or left['label_state'] != right['label_state']:
            raise ValueError('evaluation_case_inputs_differ')
        if left['correct'] is None:
            outcome = 'unlabeled_changed' if left.get('candidate_checksum') != right.get('candidate_checksum') else 'unlabeled_unchanged'
        elif left['correct'] and not right['correct']:
            outcome = 'regressed'
        elif not left['correct'] and right['correct']:
            outcome = 'improved'
        else:
            outcome = 'unchanged_correct' if right['correct'] else 'unchanged_incorrect'
        rows.append({'case_id': case_id, 'outcome': outcome, 'baseline_status': left['status'],
                     'candidate_status': right['status'],
                     'output_changed': left.get('candidate_checksum') != right.get('candidate_checksum')})
    counts = {key: sum(row['outcome'] == key for row in rows) for key in (
        'improved', 'regressed', 'unchanged_correct', 'unchanged_incorrect', 'unlabeled_changed', 'unlabeled_unchanged')}
    return {'baseline_run_id': baseline.id, 'candidate_run_id': candidate.id,
        'mode': 'repeatability' if baseline.algorithm_manifest['scorer_checksum'] == candidate.algorithm_manifest['scorer_checksum'] else 'algorithm_comparison',
        'dataset_checksum': old_dataset.checksum, 'counts': counts, 'cases': rows,
        'baseline_failed_cases': baseline.metrics['failed_case_count'],
        'candidate_failed_cases': candidate.metrics['failed_case_count'],
        'boundary': '同一冻结输入与标签的评分结果比较；未标注变化不计改善，失败保留在原样本中。不代表现场效果或完整路网算法评测。'}
