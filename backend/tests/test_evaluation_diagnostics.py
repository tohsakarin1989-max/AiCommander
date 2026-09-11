from types import SimpleNamespace

from app.services.evaluation_diagnostics import candidate_observations, describe_run


def candidate(asset=1, score=80):
    return {'hypothesis_type': 'possible_source', 'evidence_refs': [f'map_asset:{asset}'],
            'region': None, 'rank': 1, 'score': score}


def test_incomplete_positive_labels_do_not_make_other_candidates_false():
    labels = [{'hypothesis_type': 'possible_source', 'expected_asset_ids': [1]}]
    rows = candidate_observations([candidate(1), candidate(2)], labels, False)
    assert [row['verified_outcome'] for row in rows] == [True, None]
    assert candidate_observations([candidate(2)], [], True)[0]['verified_outcome'] is False
    assert candidate_observations([candidate(2)], [], False)[0]['verified_outcome'] is None


def test_error_groups_keep_failures_empty_and_unlabeled_separate():
    observations = candidate_observations([candidate(1), candidate(2)],
        [{'hypothesis_type': 'possible_source', 'expected_asset_ids': [1]}], False)
    records = [
        {'status': 'completed', 'label_state': 'positive', 'correct': True, 'candidate_count': 2, 'candidate_observations': observations},
        {'status': 'completed', 'label_state': 'negative', 'correct': False, 'candidate_count': 1,
         'candidate_observations': candidate_observations([candidate(2, 50)], [], True)},
        {'status': 'empty', 'label_state': 'positive', 'correct': False, 'candidate_count': 0, 'candidate_observations': []},
        {'status': 'failed', 'label_state': 'negative', 'correct': False, 'candidate_count': 0},
        {'status': 'completed', 'label_state': 'unlabeled', 'correct': None, 'candidate_count': 1},
    ]
    result = describe_run(SimpleNamespace(id='test', trace_manifest={'records': records}))
    assert result['case_count'] == 5
    assert result['problems'] == {'execution_failed': 1, 'positive_empty': 1, 'positive_top3_miss': 0,
                                 'negative_with_candidates': 1, 'unlabeled_cases': 1}
    assert result['judged_candidates'] == 2 and result['unjudged_candidates'] == 1
    assert result['legacy_cases_without_observations'] == 1
    assert result['calibration_status'] == 'diagnostic_only'
    assert result['calibrated_probability'] is None
    assert result['buckets'][-1]['observed_correct_fraction'] == 1
    assert result['buckets'][-1]['unjudged'] == 1
