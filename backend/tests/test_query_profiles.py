import uuid
from copy import deepcopy

import pytest

from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_pipeline_service import CasePipelineService
from app.services.intelligent_query_tools import execute_tool
from app.services import intelligent_query_tasks as tasks
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_query_followup import model_for, call, FINISH


def profile(db, case):
    payload = CasePipelineService.build_profile_payload(db, case)
    row = CaseAnalysisProfile(id=str(uuid.uuid4()), case_id=case.id, profile_version=1,
        source_hash=payload['source_hash'], schema_version=payload['schema_version'],
        dictionary_version=payload['dictionary_version'], payload=payload,
        quality_score=50, analysis_readiness='partial', is_current=True)
    db.add(row)
    db.commit()
    return row


def test_profile_patterns_separate_negation_and_deduplicate_cases(query_db):
    profile(query_db, add_case(query_db, 'ONE', description='发现软管。携带软管。未发现油罐车。'))
    result = execute_tool(query_db, 'find_case_profiles', {})
    patterns = result['data']['batch_patterns']
    assert next(x for x in patterns if x['value'] == '软管')['case_count'] == 1
    assert next(x for x in patterns if x['value'] == '罐车')['kind'] == 'negated'
    reference = result['data']['items'][0]['assertions'][0]['reference']
    assert reference['source_sha256'] and reference['quote']


def test_missing_stale_invalid_and_hidden_profiles_are_not_facts(query_db):
    case = add_case(query_db, 'STALE', description='发现软管。')
    profile(query_db, case)
    case.description = '没有软管'
    bad = profile(query_db, add_case(query_db, 'BAD', description='发现油桶。'))
    payload = deepcopy(bad.payload)
    payload['semantics']['assertions'][0]['reference']['quote'] = '编造文本'
    bad.payload = payload
    profile(query_db, add_case(query_db, 'HIDDEN', operational_area_id=2, description='保密线索'))
    add_case(query_db, 'MISSING')
    query_db.commit()
    result = execute_tool(query_db, 'find_case_profiles', {})
    assert result['state'] == 'partial'
    assert result['data']['total'] == 3
    assert result['data']['batch_patterns'] == []
    assert all(not row['assertions'] for row in result['data']['items'])


@pytest.mark.asyncio
async def test_followup_inherits_case_filters_into_profile_tool(query_db):
    profile(query_db, add_case(query_db, 'MATCH', description='发现软管。'))
    profile(query_db, add_case(query_db, 'OTHER', description='发现油桶。'))
    parent = tasks.create_query(query_db, '查找MATCH案件')
    await tasks.execute_query(query_db, parent['id'], model=model_for(call('find_cases', {'keyword': 'MATCH'}), FINISH))
    child = tasks.create_query(query_db, '查看这些案件的手法和否定线索', parent['id'])
    await tasks.execute_query(query_db, child['id'], model=model_for(call('find_case_profiles', {}), FINISH))
    result = tasks.read_query(query_db, child['id'])['result']
    assert result['cards'][0]['data']['total'] == 1
    assert result['cards'][0]['data']['items'][0]['case_number'] == 'MATCH'
    assert result['trace'][0]['arguments']['keyword'] == 'MATCH'
    from app.services.intelligent_query_document import export_query_document
    document, data = export_query_document(query_db, child['id'], 'docx')
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        text = archive.read('word/document.xml').decode()
    assert '发现软管' in text and '本批表述分布' in text
    assert document.result_id == child['id']
