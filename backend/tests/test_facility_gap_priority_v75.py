"""Priority is observed blocking/unknown impact, not imagined information gain."""
from app.services.facility_conditions_v63 import rank_priority_gaps


def row(identifier, *unknowns, eligibility='retained', cited=True):
    return {'asset_id': identifier, 'name': f'合成井{identifier}', 'eligibility': eligibility,
        'conditions': [{'key': key, 'label': key, 'state': 'unknown', 'reason': f'{key}尚缺依据',
            'dependencies': [f'{key}资料'], 'evidence_refs': [f'map_asset:{identifier}@test'] if cited else []}
            for key in unknowns]}


def test_blocking_first_then_actual_affected_population_not_fixed_field_order():
    rows = [row(1, 'source'), row(2, 'road', eligibility='unresolved'),
            row(3, 'production', 'oil'), row(4, 'production'), row(5, 'production')]
    gaps = rank_priority_gaps(rows)
    assert [gap['key'] for gap in gaps] == ['road', 'production', 'oil']
    assert gaps[0]['asset_ids'] == [2]
    assert gaps[0]['priority_basis']['blocked_candidates'] == 1
    assert gaps[1]['asset_ids'] == [3, 4, 5]
    assert gaps[1]['priority_basis'] == {'affected_candidates': 3, 'blocked_candidates': 0,
        'ranked_candidates': 3, 'unresolved_candidates': 0}
    assert all(impact['evidence_refs'] for gap in gaps for impact in gap['impacts'])
    assert all('不保证' in gap['reason'] for gap in gaps)


def test_hard_exclusions_and_uncited_unknowns_do_not_fake_priority_or_coverage():
    rows = [row(1, 'production', eligibility='excluded'), row(2, 'oil', cited=False)]
    assert rank_priority_gaps(rows) == []
    rows.append(row(3, 'oil'))
    assert rank_priority_gaps(rows)[0]['asset_ids'] == [3]
    assert rank_priority_gaps([]) == []


def test_nonblocking_unknown_never_claims_it_blocks_all_analysis():
    gap = rank_priority_gaps([row(1, 'source', eligibility='unresolved')])[0]
    assert gap['priority_basis']['blocked_candidates'] == 0
    assert gap['impacts'][0]['blocks_comparison'] is False
