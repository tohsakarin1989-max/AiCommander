"""Whole material lifecycle with synthetic, isolated data and no model calls."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.results import router
from app.database import get_db, bind_principal_scope
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_result import CaseResultSnapshot
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset
from app.models.map_foundation import UserAreaScope
from app.models.meeting import Meeting
from app.models.report import Report
from app.models.result_material import FacilityMaterial, MeetingFrozenInput, ResultJudgment
from app.models.user import User
from app.services.case_pipeline_service import CasePipelineService, CASE_PROFILE_SCHEMA_VERSION, CASE_DICTIONARY_VERSION
from app.services.case_result_service import CaseResultService
from app.services.facility_material_service import freeze_facility, read_facility_material
from app.services.meeting_frozen_service import freeze_meeting_inputs, read_meeting_inputs
from app.services.result_catalog import catalog, read_result
from app.services.result_document import export_result
from app.services.result_judgment_service import record_judgment
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case


@pytest.fixture
def material_db(query_db):
    query_db.query(UserAreaScope).filter_by(user_id=1).update({'access_level': 'write'})
    query_db.commit()
    bind_principal_scope(query_db, SimpleNamespace(user_id=1, role='analyst'), method='GET')
    return query_db


def saved_case(db, number='合成案件', area=1):
    case = add_case(db, number, location='合成井场', description='未发现车辆。查获原油120升。', operational_area_id=area)
    source_hash = CasePipelineService.source_hash(db, case)
    profile = CaseAnalysisProfile(id=f'profile-{case.id}', case_id=case.id, profile_version=1,
        source_hash=source_hash, schema_version=CASE_PROFILE_SCHEMA_VERSION, dictionary_version=CASE_DICTIONARY_VERSION,
        payload={'source_hash': source_hash, 'standard': {'location': case.location}, 'analysis_facts': {'case_number': number}},
        quality_score=0, analysis_readiness='partial', is_current=True)
    db.add(profile)
    db.flush()
    result, _ = CaseResultService.create_current(db, case.id)
    db.commit()
    return case, result


def facility(db):
    row = JurisdictionAsset(name='测试井', asset_type='well', operational_area_id=1,
        latitude=46.6, longitude=125, verified=True, attributes={'oil_type': '原油'})
    db.add(row)
    db.commit()
    return row


def client(db, authenticated=True):
    app = FastAPI()
    @app.middleware('http')
    async def authenticate(request, call_next):
        if authenticated:
            request.state.principal = SimpleNamespace(user_id=1, role='analyst')
        return await call_next(request)
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.include_router(router, prefix='/api/results')
    return TestClient(app)


def test_reader_and_catalog_read_no_writes_and_same_case_document(material_db):
    case, result = saved_case(material_db)
    changes = []
    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith(('insert', 'update', 'delete')):
            changes.append(statement)
    event.listen(material_db.bind, 'before_cursor_execute', observe)
    try:
        output = read_result(material_db, 'case', result['id'])
        listing = catalog(material_db, query='合成井场')
        assert listing['items'][0]['content_sha256'] == result['content_sha256']
        assert output['body']['content'] == result['content']
        assert output['document']['blocks']
    finally:
        event.remove(material_db.bind, 'before_cursor_execute', observe)
    assert changes == []


def test_facility_explicit_freeze_is_immutable_and_retry_idempotent(material_db):
    asset = facility(material_db)
    row, created = freeze_facility(material_db, asset.id, idempotency_key='same-request-1')
    material_db.commit()
    old = read_result(material_db, 'facility', row.id)
    assert created
    retry, created = freeze_facility(material_db, asset.id, idempotency_key='same-request-1')
    assert retry.id == row.id and not created
    asset.name = '更名后井场'
    asset.attributes = {'oil_type': '柴油'}
    material_db.commit()
    historical = read_result(material_db, 'facility', row.id)
    assert historical['body']['facility']['name'] == '测试井'
    assert historical['content_sha256'] == old['content_sha256']
    assert material_db.query(FacilityMaterial).count() == 1
    with pytest.raises(ValueError, match='idempotency'):
        freeze_facility(material_db, asset.id, idempotency_key='same-request-1', end_date=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_facility_all_count_sources_rechecked_after_transfer(material_db):
    # A source not shown as a nearby case still contributed to profile coverage.
    case, _ = saved_case(material_db, '只参与完整度统计')
    asset = facility(material_db)
    row, _ = freeze_facility(material_db, asset.id, idempotency_key='scope-request-1')
    material_db.commit()
    case.operational_area_id = 2
    material_db.commit()
    with pytest.raises(PermissionError):
        read_result(material_db, 'facility', row.id)
    assert catalog(material_db, kind='facility')['items'] == []


def test_separate_freeze_requests_each_keep_idempotency_after_later_change(material_db):
    asset = facility(material_db)
    at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    first, _ = freeze_facility(material_db, asset.id, idempotency_key='first-explicit-freeze', valid_at=at, known_at=at)
    second, _ = freeze_facility(material_db, asset.id, idempotency_key='second-explicit-freeze', valid_at=at, known_at=at)
    material_db.commit()
    assert first.content_sha256 == second.content_sha256 and first.id != second.id
    asset.name = '后来改名'
    material_db.commit()
    replay, created = freeze_facility(material_db, asset.id, idempotency_key='second-explicit-freeze', valid_at=at, known_at=at)
    assert replay.id == second.id and not created


def test_judgment_is_append_only_exact_version_and_idempotent(material_db):
    case, result = saved_case(material_db)
    request = dict(content_sha256=result['content_sha256'], decision='retain_reference', note='保留已保存出处作参考',
                   additional_sources=[], idempotency_key='judgment-request-1')
    first, created = record_judgment(material_db, 'case', result['id'], **request)
    material_db.commit()
    second, repeated = record_judgment(material_db, 'case', result['id'], **request)
    assert created and not repeated and first.id == second.id
    with pytest.raises(ValueError, match='version_conflict'):
        record_judgment(material_db, 'case', result['id'], **{**request, 'content_sha256': '0' * 64})
    with pytest.raises(ValueError, match='idempotency_conflict'):
        record_judgment(material_db, 'case', result['id'], **{**request, 'decision': 'confirm'})
    view = read_result(material_db, 'case', result['id'])
    assert view['judgments'][0]['created_by'] == 1
    assert case.status == 'pending'
    assert material_db.query(Conclusion).count() == 0
    assert CaseResultService.read(material_db, result['id'])['content_sha256'] == result['content_sha256']


def test_new_source_version_does_not_inherit_judgment(material_db):
    _, first = saved_case(material_db)
    record_judgment(material_db, 'case', first['id'], content_sha256=first['content_sha256'], decision='confirm',
        note='只确认该版表达', additional_sources=[], idempotency_key='first-version')
    old = material_db.query(CaseResultSnapshot).filter_by(id=first['id']).one()
    content = deepcopy(old.content)
    content['information_gaps']['analysis'].append('新增信息缺口')
    from app.services.case_result_snapshot import _canonical
    from hashlib import sha256
    # New saved version uses the public snapshot hashing contract.
    new_id, _ = CaseResultService._persist(material_db, {'content': content, 'content_sha256': sha256(_canonical(content).encode()).hexdigest()})
    material_db.commit()
    assert read_result(material_db, 'case', first['id'])['judgments']
    assert read_result(material_db, 'case', new_id)['judgments'] == []


def test_viewer_cannot_freeze_or_judge(material_db):
    _, result = saved_case(material_db)
    asset = facility(material_db)
    material_db.get(User, 1).role = 'viewer'
    material_db.commit()
    with pytest.raises(PermissionError):
        freeze_facility(material_db, asset.id, idempotency_key='viewer-attempt')
    with pytest.raises(PermissionError):
        record_judgment(material_db, 'case', result['id'], content_sha256=result['content_sha256'], decision='confirm',
            note='无权', additional_sources=[], idempotency_key='viewer-attempt')
    assert material_db.query(ResultJudgment).count() == 0


def test_meeting_uses_frozen_input_and_never_current_description(material_db):
    case, result = saved_case(material_db)
    meeting = Meeting(meeting_id='synthetic-meeting', operational_area_id=1, case_ids=[case.id])
    material_db.add(meeting)
    material_db.flush()
    frozen = freeze_meeting_inputs(material_db, meeting)
    material_db.commit()
    case.description = '后续变化，不得进入旧会议输入'
    material_db.commit()
    assert read_meeting_inputs(material_db, meeting.meeting_id) == frozen
    assert frozen['sources'] == [{'kind': 'case', 'id': result['id'], 'content_sha256': result['content_sha256']}]
    assert '后续变化' not in str(frozen)


def test_historical_meeting_and_conclusion_keep_original_identity(material_db):
    case, _ = saved_case(material_db)
    meeting = Meeting(meeting_id='old-meeting', operational_area_id=1, case_ids=[case.id])
    material_db.add(meeting)
    material_db.flush()
    report = Report(meeting_id=meeting.meeting_id, report_type='comprehensive', content={'summary': '旧会议原文'})
    conclusion = Conclusion(case_id=case.id, meeting_id=meeting.meeting_id, summary='旧人工记录', evidence={}, status='published')
    material_db.add_all([report, conclusion])
    material_db.flush()
    material_db.add(ConclusionReview(conclusion_id=conclusion.id, action='approve', note='历史同意'))
    material_db.commit()
    saved = read_result(material_db, 'meeting', str(report.id))
    assert saved['body']['source_state'] == 'historical_unversioned' and saved['sources'] == []
    old = read_result(material_db, 'conclusion', str(conclusion.id))
    assert old['body']['historical_reviews'][0]['reviewer_state'] == 'legacy_not_recorded'
    assert catalog(material_db, subject_kind='meeting', subject_id=meeting.meeting_id)['items'][0]['id'] == str(report.id)
    case.operational_area_id = 2
    material_db.commit()
    for kind, identifier in [('meeting', report.id), ('conclusion', conclusion.id)]:
        with pytest.raises(PermissionError):
            read_result(material_db, kind, str(identifier))


def test_material_api_auth_read_and_failed_version(material_db):
    _, result = saved_case(material_db)
    with client(material_db, authenticated=False) as http:
        assert http.get('/api/results').status_code == 401
    with client(material_db) as http:
        response = http.get(f"/api/results/case/{result['id']}")
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        bad = http.post(f"/api/results/case/{result['id']}/judgments", json={
            'content_sha256': '0' * 64, 'decision': 'confirm', 'note': '仅合成', 'idempotency_key': 'api-test-request'})
        assert bad.status_code == 409


def test_facility_document_uses_frozen_values_actual_docx(material_db):
    asset = facility(material_db)
    row, _ = freeze_facility(material_db, asset.id, idempotency_key='docx-request-1')
    material_db.commit()
    asset.name = '后来改名不应出现在旧材料'
    material_db.commit()
    document, data = export_result(material_db, 'facility', row.id, 'docx')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read('word/document.xml').decode()
    assert '测试井' in xml and '后来改名' not in xml
    assert document.content_sha256 == row.content_sha256


def test_topic_reader_keeps_definition_not_current_title(material_db):
    from app.services import analysis_topic_service as topics
    from app.models.analysis_topic import AnalysisTopic
    from tests.test_analysis_topics import seed
    seed(material_db)
    topic = topics.create_topic(material_db, '形成时标题', {})
    topics.refresh_topic(material_db, topic['id'])
    snapshot = topics.read_topic(material_db, topic['id'])['snapshot']
    initial = read_result(material_db, 'topic', snapshot['id'])
    material_db.get(AnalysisTopic, topic['id']).title = '后改标题'
    material_db.commit()
    assert read_result(material_db, 'topic', snapshot['id']) == initial
    assert initial['title'] == '形成时标题'


def test_experience_reader_keeps_body_version_and_separate_confirmation(material_db):
    from app.services.knowledge_asset_service import KnowledgeAssetService
    case, result = saved_case(material_db)
    asset = KnowledgeAssetService.generate_experience_asset(material_db, case.id)
    before = read_result(material_db, 'experience', str(asset.id))
    assert before['sources'][0]['id'] == result['id']
    KnowledgeAssetService.review_asset(material_db, asset.id, status='confirmed', reviewed_by=1, note='合成确认')
    after = read_result(material_db, 'experience', str(asset.id))
    assert before['content_sha256'] == after['content_sha256']
    assert before['document'] == after['document']
    assert after['experience_review']['status'] == 'confirmed'
    assert before['body'] == after['body']
    assert 'experience_review' not in read_result(material_db, 'experience', str(asset.id), include_judgments=False)
    assert case.status == 'pending'


def test_period_reader_rechecks_sources_and_retains_zero_and_gaps(material_db):
    from app.models.deployment_advisor import SituationBrief
    case, _ = saved_case(material_db)
    instant = datetime(2026, 9, 1)
    brief = SituationBrief(id='synthetic-period', operational_area_id=1, period_type='daily',
        period_start=instant, period_end=datetime(2026, 9, 2), input_fingerprint='a' * 64,
        status='completed', summary='本期没有新增记录，资料未齐不代表无问题',
        comparison_snapshot={'current': {'case_ids': [case.id], 'case_count': 0}, 'previous': {'case_ids': []}},
        evidence_refs=[f'case:{case.id}'], information_gaps=['技防资料未提供'])
    material_db.add(brief)
    material_db.commit()
    saved = read_result(material_db, 'situation', brief.id)
    rendered = str(saved['document'])
    assert '技防资料未提供' in rendered and '案件数：0' in rendered
    assert saved['body']['comparison_snapshot']['current']['case_count'] == 0
    case.operational_area_id = 2
    material_db.commit()
    with pytest.raises(PermissionError):
        read_result(material_db, 'situation', brief.id)


@pytest.mark.asyncio
async def test_query_reader_reuses_actual_tool_card_and_owner_scope(material_db):
    from app.services import intelligent_query_tasks as queries
    from tests.test_query_followup import model_for, call, FINISH
    saved_case(material_db)
    created = queries.create_query(material_db, '统计案件数')
    await queries.execute_query(material_db, created['id'], model=model_for(call('count_cases', {}), FINISH))
    result = read_result(material_db, 'query', created['id'])
    assert result['body']['result']['cards'][0]['data']['count'] == 1
    assert result['document']['blocks']
    material_db.info['principal_user_id'] = 2
    with pytest.raises((PermissionError, ValueError)):
        read_result(material_db, 'query', created['id'])


def test_new_meeting_report_rechecks_frozen_source_hash_on_all_read_paths(material_db):
    from app.api.reports import get_report
    from fastapi import HTTPException
    from app.services.intelligent_query_context import result_hash
    from app.services.meeting_service import MeetingService
    case, result = saved_case(material_db)
    meeting = Meeting(meeting_id='source-bound-report', operational_area_id=1, case_ids=[case.id])
    material_db.add(meeting)
    material_db.flush()
    frozen = freeze_meeting_inputs(material_db, meeting)
    report = Report(meeting_id=meeting.meeting_id, report_type='comprehensive', content={
        'summary': '仅讨论参考', 'source_manifest': frozen['sources'], 'input_sha256': result_hash(frozen)})
    material_db.add(report)
    material_db.flush()
    meeting.final_report_id = report.id
    material_db.commit()
    assert read_result(material_db, 'meeting', str(report.id))['body']['source_state'] == 'frozen'
    assert get_report(report.id, material_db)['content']['summary'] == '仅讨论参考'
    assert MeetingService.get_meeting_report(material_db, meeting.meeting_id).id == report.id
    original_content = report.content
    report.content = {**report.content, 'input_sha256': '0' * 64}
    material_db.commit()
    assert MeetingService.get_meeting_report(material_db, meeting.meeting_id) is None
    report.content = original_content
    material_db.commit()
    row = material_db.query(CaseResultSnapshot).filter_by(id=result['id']).one()
    row.content_sha256 = '0' * 64
    material_db.commit()
    with pytest.raises(PermissionError):
        read_result(material_db, 'meeting', str(report.id))
    with pytest.raises(HTTPException) as failure:
        get_report(report.id, material_db)
    assert failure.value.status_code == 404


def test_historical_case_report_body_keeps_its_original_source(material_db):
    from app.models.knowledge_asset import KnowledgeAsset
    case, _ = saved_case(material_db)
    row = KnowledgeAsset(asset_type='case_report', source_case_id=case.id, version=1,
        title='原案件报告', content={'markdown': '旧报告专有内容，不得丢失'}, evidence_refs=[],
        source_signature='a' * 64, source_data_version='b' * 64, status='archived')
    material_db.add(row)
    material_db.commit()
    saved = read_result(material_db, 'experience', row.id)
    assert saved['body']['asset_type'] == 'case_report'
    assert '旧报告专有内容，不得丢失' in str(saved['document'])
    assert '历史案件报告边界' in str(saved['document'])
    assert saved['experience_review']['status'] == 'archived'


def test_large_topic_stays_readable_when_complete_export_exceeds_budget(material_db):
    from app.services import analysis_topic_service as topics
    from app.services.topic_document import _rows
    material_db.add_all([Case(case_number=f'大专题合成-{index}', operational_area_id=1,
        occurred_time=datetime(2026, 9, 9), description='合成资料，不是业务案件', status='pending')
        for index in range(1800)])
    material_db.commit()
    topic = topics.create_topic(material_db, '大专题资料不足', {
        'conditions': [{'category': 'method', 'value': '抽油', 'kind': 'stated'}]})
    outcome = topics.refresh_topic(material_db, topic['id'])
    for _ in range(30):
        if outcome['status'] != 'running':
            break
        outcome = topics.refresh_topic(material_db, topic['id'])
    assert outcome['status'] == 'updated'
    snapshot = topics.read_topic(material_db, topic['id'])['snapshot']
    result = read_result(material_db, 'topic', snapshot['id'])
    assert result['body']['snapshot']['aggregate']['coverage']['authorized_cases'] == 1800
    assert '阅读概览' in str(result['document'])
    assert sum(len(block['rows']) for block in result['document']['blocks']) <= 4003
    assert catalog(material_db, kind='topic')['items'][0]['id'] == snapshot['id']
    with pytest.raises(ValueError, match='topic_document_too_large'):
        export_result(material_db, 'topic', snapshot['id'], 'docx')
    labels = list(_rows({'operational_area_id': 1, 'case_id': 2, 'profiles_complete': False,
        'conditions': [{'category': 'method', 'kind': 'negated'}]}))
    assert ('辖区编号', '1') in labels and ('案件编号', '2') in labels
    assert ('画像是否全部就绪', '否') in labels
    assert ('条件组合 · 1 / 语义类别', '作案手法') in labels


def test_material_scope_cache_rechecks_mutable_scope_parent_and_other_session(material_db):
    from sqlalchemy.orm import Session
    for area in (1, 2):
        asset = JurisdictionAsset(name=f'合成辖区{area}设施', asset_type='well', operational_area_id=area)
        meeting = Meeting(meeting_id=f'scope-cache-{area}', operational_area_id=area, case_ids=[])
        material_db.add_all([asset, meeting])
        material_db.flush()
        material_db.add(FacilityMaterial(id=f'scope-material-{area}', asset_id=asset.id, created_by=1,
            title='合成范围测试', idempotency_key=f'scope-{area}', request_sha256='a' * 64,
            content_sha256='b' * 64, payload={}, source_manifest={}))
        material_db.add(MeetingFrozenInput(meeting_id=meeting.meeting_id, content_sha256='c' * 64, payload={}))
    material_db.commit()
    scope = [1]
    material_db.info['authorized_area_ids'] = scope
    def visible(db):
        return ([r.id for r in db.query(FacilityMaterial)], [r.meeting_id for r in db.query(MeetingFrozenInput)])
    assert visible(material_db) == (['scope-material-1'], ['scope-cache-1'])
    scope[:] = [2]
    assert visible(material_db) == (['scope-material-2'], ['scope-cache-2'])
    with Session(material_db.bind) as other:
        other.info['authorized_area_ids'] = [1]
        assert visible(other) == (['scope-material-1'], ['scope-cache-1'])
    assert visible(material_db) == (['scope-material-2'], ['scope-cache-2'])
    material_db.execute(Meeting.__table__.update().where(Meeting.meeting_id == 'scope-cache-2').values(operational_area_id=1))
    material_db.execute(JurisdictionAsset.__table__.update().where(JurisdictionAsset.operational_area_id == 2).values(operational_area_id=1))
    material_db.commit()
    assert visible(material_db) == ([], [])
