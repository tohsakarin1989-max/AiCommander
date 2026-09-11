"""Deterministic held-out calibration experiment; never promotes production rules."""
import hashlib
import math

SCHEMA = 'case-grouped-bin-calibration-4.5-1'
MIN_TRAIN_CASES = 10
MIN_VALIDATION_CASES = 5
MIN_TRAIN_OBSERVATIONS = 20
MIN_VALIDATION_OBSERVATIONS = 10
BUCKET_RANGES = ((None, 0), (0, 20), (20, 40), (40, 60), (60, 80), (80, None))


def partition(case_id):
    value = hashlib.sha256(f'{SCHEMA}:{case_id}'.encode()).hexdigest()
    return 'validation' if int(value[:8], 16) % 10 < 3 else 'train'


def _bucket(score):
    return next(index for index, (lower, upper) in enumerate(BUCKET_RANGES)
                if (lower is None or score >= lower) and (upper is None or score < upper))


def _brier(rows, predict):
    return sum((predict(row) - row['outcome']) ** 2 for row in rows) / len(rows)


def calibrate(run):
    records = run.trace_manifest['records']
    groups = {'train': [], 'validation': []}
    excluded = {'failed_cases': 0, 'empty_cases': 0, 'legacy_cases': 0,
                'unjudged_candidates': 0, 'invalid_score_candidates': 0}
    for record in sorted(records, key=lambda row: row['case_id']):
        if record['status'] == 'failed':
            excluded['failed_cases'] += 1
            continue
        if record['candidate_count'] == 0:
            excluded['empty_cases'] += 1
            continue
        observations = record.get('candidate_observations')
        if observations is None or len(observations) != record['candidate_count']:
            excluded['legacy_cases'] += 1
            continue
        for item in observations:
            if type(item.get('verified_outcome')) is not bool:
                excluded['unjudged_candidates'] += 1
                continue
            score = item.get('rule_support')
            if type(score) not in (int, float) or not math.isfinite(score):
                excluded['invalid_score_candidates'] += 1
                continue
            groups[partition(record['case_id'])].append({'case_id': record['case_id'],
                'type': item['hypothesis_type'], 'bucket': _bucket(score), 'outcome': int(item['verified_outcome'])})
    train, validation = groups['train'], groups['validation']
    train_cases = sorted({row['case_id'] for row in train})
    validation_cases = sorted({row['case_id'] for row in validation})
    result = {'schema': SCHEMA, 'source_run_id': run.id, 'case_count': len(records), 'excluded': excluded,
        'split': {'train_case_ids': train_cases, 'validation_case_ids': validation_cases,
                  'train_observations': len(train), 'validation_observations': len(validation)},
        'requirements': {'train_cases': MIN_TRAIN_CASES, 'validation_cases': MIN_VALIDATION_CASES,
            'train_observations': MIN_TRAIN_OBSERVATIONS, 'validation_observations': MIN_VALIDATION_OBSERVATIONS,
            'both_outcomes_in_each_split': True},
        'status': 'insufficient_labels', 'models': None, 'validation': None,
        'bucket_ranges': [{'lower': lower, 'upper_exclusive': upper} for lower, upper in BUCKET_RANGES],
        'production_promotion_allowed': False,
        'boundary': '仅验证本固定评测集内已核验候选。按案件分组留出，不保证跨地域或跨时间独立；'
                    '不覆盖无候选或执行失败的案件，不自动替换生产评分或赋予案件事实概率。'}
    implementations = run.algorithm_manifest.get('implementations', [])
    if len(implementations) != 1 or not implementations[0].get('code_checksum'):
        result['status'] = 'algorithm_version_not_unique'
        return result
    if (len(train_cases) < MIN_TRAIN_CASES or len(validation_cases) < MIN_VALIDATION_CASES
            or len(train) < MIN_TRAIN_OBSERVATIONS or len(validation) < MIN_VALIDATION_OBSERVATIONS
            or {row['outcome'] for row in train} != {0, 1} or {row['outcome'] for row in validation} != {0, 1}):
        return result
    models = {}
    for kind in sorted({row['type'] for row in train}):
        samples = [row for row in train if row['type'] == kind]
        prior = (sum(row['outcome'] for row in samples) + 1) / (len(samples) + 2)
        buckets = []
        for index in range(6):
            values = [row['outcome'] for row in samples if row['bucket'] == index]
            buckets.append({'index': index, 'observations': len(values),
                'estimate': (sum(values) + 1) / (len(values) + 2) if len(values) >= 5 else prior,
                'method': 'laplace_bin' if len(values) >= 5 else 'training_type_prior'})
        models[kind] = {'training_observations': len(samples), 'prior': prior, 'buckets': buckets}
    result['models'] = models
    if any(row['type'] not in models for row in validation):
        result['status'] = 'validation_type_not_in_training'
        return result
    baseline = _brier(validation, lambda row: models[row['type']]['prior'])
    calibrated = _brier(validation, lambda row: models[row['type']]['buckets'][row['bucket']]['estimate'])
    result['validation'] = {'metric': 'brier_lower_is_better', 'baseline': baseline,
        'calibrated': calibrated, 'improvement': baseline - calibrated,
        'baseline_kind': 'training_type_prior', 'tuned_on_validation': False}
    incomplete = any(excluded[key] for key in ('failed_cases', 'legacy_cases', 'unjudged_candidates', 'invalid_score_candidates'))
    result['status'] = ('incomplete_label_coverage' if incomplete else
        'heldout_improved_requires_review' if calibrated < baseline - 1e-12 else 'no_heldout_improvement')
    return result
