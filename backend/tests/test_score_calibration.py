from copy import deepcopy
from types import SimpleNamespace

from app.services.score_calibration import calibrate, partition


def synthetic_run():
    records = []
    for identifier in range(1, 101):
        verdict = identifier % 2 == 0
        records.append({'case_id': identifier, 'status': 'completed', 'candidate_count': 1,
            'candidate_observations': [{'hypothesis_type': 'possible_source',
                'rule_support': 85 if verdict else 10, 'verified_outcome': verdict}]})
    return SimpleNamespace(id='synthetic-calibration', trace_manifest={'records': records},
        algorithm_manifest={'implementations': [{'version': 'test', 'code_checksum': 'a' * 64}]})


def test_training_validation_are_disjoint_and_improvement_does_not_promote():
    run = synthetic_run()
    result = calibrate(run)
    assert result == calibrate(run)
    assert result['status'] == 'heldout_improved_requires_review'
    assert set(result['split']['train_case_ids']).isdisjoint(result['split']['validation_case_ids'])
    assert result['validation']['calibrated'] < result['validation']['baseline']
    assert result['production_promotion_allowed'] is False
    assert result['validation']['tuned_on_validation'] is False


def test_holdout_labels_do_not_influence_fit_and_can_expose_regression():
    run = synthetic_run()
    original = calibrate(run)
    changed = deepcopy(run)
    for row in changed.trace_manifest['records']:
        if partition(row['case_id']) == 'validation':
            row['candidate_observations'][0]['verified_outcome'] = not row['candidate_observations'][0]['verified_outcome']
    result = calibrate(changed)
    assert result['models'] == original['models']
    assert result['status'] == 'no_heldout_improvement'
    assert result['validation']['improvement'] < 0


def test_sparse_unknown_and_failed_inputs_never_claim_complete_calibration():
    sparse = synthetic_run()
    sparse.trace_manifest['records'] = sparse.trace_manifest['records'][:3]
    assert calibrate(sparse)['status'] == 'insufficient_labels'
    assert calibrate(sparse)['models'] is None
    run = synthetic_run()
    run.trace_manifest['records'][0]['candidate_observations'][0]['verified_outcome'] = None
    run.trace_manifest['records'][1]['status'] = 'failed'
    result = calibrate(run)
    assert result['status'] == 'incomplete_label_coverage'
    assert result['excluded']['unjudged_candidates'] == 1
    assert result['excluded']['failed_cases'] == 1
    assert result['case_count'] == 100
    run.algorithm_manifest['implementations'] = []
    assert calibrate(run)['status'] == 'algorithm_version_not_unique'
