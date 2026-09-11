"""Describe labeled errors without treating incomplete labels as ground truth."""
import math
from types import SimpleNamespace

from app.services.governance_service import GovernanceService

SCHEMA = 'fixed-score-diagnostics-4.5-1'


def candidate_observations(candidates, positive_labels, negative):
    rows = []
    for candidate in candidates:
        matched = any(GovernanceService._hypothesis_matches_ground_truth(SimpleNamespace(**candidate), label)
                      for label in positive_labels)
        score = candidate.get('score')
        score = float(score) if type(score) in (float, int) and math.isfinite(score) else None
        rows.append({'rank': candidate.get('rank'), 'hypothesis_type': candidate.get('hypothesis_type'),
            'rule_support': score, 'verified_outcome': True if matched else False if negative else None})
    return rows


def describe_run(run):
    records = run.trace_manifest['records']
    problems = {'execution_failed': 0, 'positive_empty': 0, 'positive_top3_miss': 0,
                'negative_with_candidates': 0, 'unlabeled_cases': 0}
    buckets = [{'lower': lower, 'upper_exclusive': upper, 'verified_correct': 0, 'verified_incorrect': 0,
                'unjudged': 0} for lower, upper in ((None, 0), (0, 20), (20, 40), (40, 60), (60, 80), (80, None))]
    missing_observations = invalid_scores = judged = unjudged = 0
    for record in records:
        state, label = record['status'], record['label_state']
        problems['execution_failed'] += state == 'failed'
        problems['unlabeled_cases'] += label == 'unlabeled'
        if state != 'failed':
            problems['positive_empty'] += label == 'positive' and state == 'empty'
            problems['positive_top3_miss'] += label == 'positive' and state != 'empty' and record['correct'] is False
            problems['negative_with_candidates'] += label == 'negative' and record['candidate_count'] > 0
        observations = record.get('candidate_observations')
        if observations is None:
            missing_observations += record['candidate_count'] > 0
            continue
        for observation in observations:
            score, verdict = observation['rule_support'], observation['verified_outcome']
            judged += verdict is not None
            unjudged += verdict is None
            if type(score) not in (int, float) or not math.isfinite(score):
                invalid_scores += 1
                continue
            bucket = next(row for row in buckets if (row['lower'] is None or score >= row['lower'])
                          and (row['upper_exclusive'] is None or score < row['upper_exclusive']))
            bucket['verified_correct' if verdict is True else 'verified_incorrect' if verdict is False else 'unjudged'] += 1
    for bucket in buckets:
        count = bucket['verified_correct'] + bucket['verified_incorrect']
        bucket['observed_correct_fraction'] = bucket['verified_correct'] / count if count else None
    return {'schema': SCHEMA, 'run_id': run.id, 'case_count': len(records), 'problems': problems,
        'buckets': buckets, 'judged_candidates': judged, 'unjudged_candidates': unjudged,
        'invalid_score_candidates': invalid_scores, 'legacy_cases_without_observations': missing_observations,
        'calibration_status': 'no_verified_labels' if not judged else 'diagnostic_only',
        'calibrated_probability': None,
        'boundary': '分段比例只描述本评测已核验候选，不是预测概率。阳性样本未匹配目标不自动判错，'
                    '可能存在尚未标注目标；失败与无候选单列，不从分母中消失。尚未完成独立样本校准验证。'}
