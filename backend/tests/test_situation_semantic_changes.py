from datetime import datetime, timezone
from uuid import uuid4

from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_pipeline_service import CasePipelineService
from app.services.situation_change_service import case_changes, closed_window
from tests.test_case_search_page import search_db, add_case  # noqa: F401


def profile(db, case):
    payload = CasePipelineService.build_profile_payload(db, case)
    item = CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
        source_hash=payload['source_hash'], schema_version=payload['schema_version'],
        dictionary_version=payload['dictionary_version'], payload=payload, quality_score=1,
        analysis_readiness='ready', is_current=True)
    db.add(item)
    db.commit()
    return item


def test_existing_terms_count_cases_not_mentions_and_keep_negation(search_db):
    window = closed_window(datetime(2026, 9, 11, 3, tzinfo=timezone.utc), 'daily')
    previous = add_case(search_db, 'BEFORE', occurred_time=window.previous_start, description='未使用车辆转运')
    current = add_case(search_db, 'AFTER', occurred_time=window.current_start, description='车辆转运，车辆转运。河岸。')
    search_db.commit()
    profile(search_db, previous)
    profile(search_db, current)
    search_db.info['authorized_area_ids'] = (1,)
    result = case_changes(search_db, 1, window)['semantic_changes']
    assert result['state'] == 'comparable'
    values = {(row['value'], row['kind']): row for row in result['changes']}
    assert values[('车辆转运', 'stated')]['current_count'] == 1
    assert values[('车辆转运', 'negated')]['previous_count'] == 1
    assert values[('临水', 'stated')]['current_count'] == 1
    assert result['current']['terms'][0]['evidence'][0]['profile_id']
    current.description = '新的案情，等待画像更新'
    search_db.commit()
    changed = case_changes(search_db, 1, window)['semantic_changes']
    assert changed['state'] == 'incomparable' and changed['changes'] == []
    assert changed['current']['readable_case_count'] == 0


def test_rule_versions_and_missing_profiles_are_not_business_changes(search_db):
    window = closed_window(datetime(2026, 9, 11, 3, tzinfo=timezone.utc), 'daily')
    before = add_case(search_db, 'BEFORE', occurred_time=window.previous_start, description='打孔盗油')
    after = add_case(search_db, 'AFTER', occurred_time=window.current_start, description='打眼盗油')
    search_db.commit()
    profile(search_db, before)
    search_db.info['authorized_area_ids'] = (1,)
    assert case_changes(search_db, 1, window)['semantic_changes']['state'] == 'incomparable'
    current = profile(search_db, after)
    result = case_changes(search_db, 1, window)['semantic_changes']
    assert result['state'] == 'comparable'
    assert result['changes'][0]['case_count_change'] == 0
    current.payload = {**current.payload, 'semantics': {**current.payload['semantics'], 'rule_version': 'new-rule'}}
    search_db.commit()
    assert case_changes(search_db, 1, window)['semantic_changes']['state'] == 'incomparable'
