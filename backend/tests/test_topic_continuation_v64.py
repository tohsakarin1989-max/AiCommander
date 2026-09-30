"""Real SQLite persistence and lease/source fences; no models or business DB."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy

import pytest
from sqlalchemy import update

from app.models.analysis_topic import AnalysisTopic, TopicSnapshot, TopicRefreshChunk, TopicDependency
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.services import analysis_topic_service as topics
from app.services import profile_aggregate_jobs as jobs
from app.services.intelligent_query_tools import AggregateProfiles
from app.services.profile_aggregate import build_aggregate
from app.services.topic_definitions import resolve_definition
from app.services.topic_dependencies import EVENT_TYPE, consume_changes
from app.services.topic_revision_fence import current_revision
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_query_profiles import profile
from tests.test_analysis_topics import client_for
from tests.test_facility_foundation_api_v62 import recorded  # noqa: F401


def cases(db, count=5):
    result = []
    for index in range(count):
        case = add_case(db, f'V64-{index}', description='井场发现软管。')
        profile(db, case)
        result.append(case)
    return result


def complete(db, identifier):
    for _ in range(100):
        result = jobs.process_aggregate_job(db, identifier, max_pages=1)
        if result['status'] != 'running':
            return result
    raise AssertionError('continuation did not finish')


def test_chunked_scan_equals_whole_scan_and_survives_session_expiration(query_db, monkeypatch):
    cases(query_db)
    monkeypatch.setattr(jobs, 'PAGE_SIZE', 2)
    args = AggregateProfiles()
    topic = topics.create_topic(query_db, '条件有何变化', {})
    row = query_db.get(AnalysisTopic, topic['id'])
    job = jobs.create_aggregate_job(query_db, {}, topic=row)
    query_db.commit()
    first = jobs.process_aggregate_job(query_db, job['id'], max_pages=1)
    assert first['status'] == 'running' and first['scanned_cases'] == 2
    assert query_db.query(TopicRefreshChunk).count() == 1
    query_db.expire_all()  # A new worker reads only durable cursor/chunks.
    assert complete(query_db, job['id'])['status'] == 'updated'
    snapshot = query_db.query(TopicSnapshot).one()
    expected = build_aggregate(query_db, args)
    assert snapshot.payload['aggregate'] == expected
    assert jobs.process_aggregate_job(query_db, job['id'])['claimed'] is False
    assert query_db.query(TopicSnapshot).count() == 1
    assert query_db.query(TopicDependency).filter_by(kind='cases').count() == 5


def test_source_edit_same_count_invalidates_running_pages(query_db, monkeypatch):
    records = cases(query_db)
    monkeypatch.setattr(jobs, 'PAGE_SIZE', 2)
    topic = topics.create_topic(query_db, '条件变化', {})
    row = query_db.get(AnalysisTopic, topic['id'])
    job = jobs.create_aggregate_job(query_db, {}, topic=row)
    query_db.commit()
    jobs.process_aggregate_job(query_db, job['id'], max_pages=1)
    before = current_revision(query_db)
    original = records[0].description
    query_db.execute(update(Case).where(Case.id == records[0].id).values(description='更新一次'))
    query_db.execute(update(Case).where(Case.id == records[0].id).values(description=original))
    query_db.commit()
    assert current_revision(query_db) > before
    assert jobs.process_aggregate_job(query_db, job['id'])['status'] == 'superseded'
    assert query_db.query(TopicSnapshot).count() == 0
    assert topics.read_topic(query_db, topic['id'])['refresh_state'] == 'queued'


def test_definition_revision_cancels_old_job_and_keeps_old_snapshot(query_db):
    cases(query_db, 1)
    created = topics.create_topic(query_db, '手法变化', {}, question='手法条件有何变化')
    topics.refresh_topic(query_db, created['id'])
    old = topics.read_topic(query_db, created['id'], revision=1)['snapshot']
    topics.request_refresh(query_db, created['id'])
    row = query_db.get(AnalysisTopic, created['id'])
    job = jobs.create_aggregate_job(query_db, {}, topic=row)
    query_db.commit()
    with client_for(query_db) as client:
        url = f"/api/analysis-topics/{created['id']}"
        assert client.patch(url, json={'question': '油品条件', 'expected_definition_revision': 999}).status_code == 409
        response = client.patch(url, json={'question': '油品条件', 'filters': {'oil_types': ['原油']}, 'expected_definition_revision': 1})
        assert response.status_code == 200 and response.json()['definition_revision'] == 2
        assert len(client.get(url + '/definitions').json()['items']) == 2
    assert jobs.process_aggregate_job(query_db, job['id'])['status'] == 'superseded'
    assert topics.read_topic(query_db, created['id'], revision=1)['snapshot'] == old


def test_rolling_window_is_frozen_and_fixed_window_does_not_move(query_db):
    created = topics.create_topic(query_db, '近七天变化', {}, window={'mode': 'rolling', 'days': 7})
    topic = query_db.get(AnalysisTopic, created['id'])
    now = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
    first = resolve_definition(topic, now)
    later = resolve_definition(topic, now + timedelta(days=1))
    assert datetime.fromisoformat(first['resolved_filters']['end_date']) == datetime(2026, 9, 29, 16, tzinfo=timezone.utc)
    assert first['resolved_filters']['end_date'] != later['resolved_filters']['end_date']
    job = jobs.create_aggregate_job(query_db, {}, topic=topic)
    query_db.commit()
    frozen = deepcopy(query_db.get(OutboxEvent, job['id']).payload['arguments'])
    jobs.process_aggregate_job(query_db, job['id'], max_pages=1)
    assert query_db.get(OutboxEvent, job['id']).payload['arguments'] == frozen
    fixed = topics.create_topic(query_db, '固定范围', {'start_date': '2026-01-01T00:00:00Z', 'end_date': '2026-02-01T00:00:00Z'})
    row = query_db.get(AnalysisTopic, fixed['id'])
    assert resolve_definition(row, now)['resolved_filters'] == resolve_definition(row, now + timedelta(days=9))['resolved_filters']


def test_adhoc_aggregate_continuation_is_idempotent_cancelled_and_owner_scoped(query_db):
    cases(query_db, 1)
    topics._owner(query_db)
    first = jobs.create_aggregate_job(query_db, {}, query_id='same-query')
    again = jobs.create_aggregate_job(query_db, {}, query_id='same-query')
    assert first['id'] == again['id']
    query_db.commit()
    jobs.cancel_aggregate_job(query_db, first['id'])
    assert jobs.process_aggregate_job(query_db, first['id'])['status'] == 'cancelled'
    query_db.info['principal_user_id'] = 2
    with pytest.raises(ValueError, match='not_found'):
        jobs.read_aggregate_job(query_db, first['id'])


def test_source_context_rejects_scope_broadening_and_invalid_kind(query_db):
    record = cases(query_db, 1)[0]
    with client_for(query_db) as client:
        response = client.post('/api/analysis-topics/from-context', json={'title': '本案缺口',
            'source_context': {'kind': 'case', 'id': record.id}})
        assert response.status_code == 201
        value = response.json()
        assert value['question_kind'] == 'case_gaps' and value['filters']['case_id'] == record.id
        assert client.post('/api/analysis-topics/from-context', json={'title': '冲突',
            'source_context': {'kind': 'case', 'id': record.id}, 'filters': {'case_id': record.id + 10}}).status_code == 422
        assert client.post('/api/analysis-topics', json={'title': '无来源', 'question_kind': 'facility_context'}).status_code == 422
        assert client.post('/api/analysis-topics', json={'title': '无天数', 'window': {'mode': 'rolling'}}).status_code == 422
        for path in ('/api/analysis-topics', '/api/analysis-topics/from-context'):
            assert client.post(path, json={'title': '不能绕过查询条件',
                'source_context': {'kind': 'query', 'id': 'not-a-run'}}).status_code == 422
    assert complete(query_db, _job(query_db, value['id']))['status'] == 'updated'
    read = topics.read_topic(query_db, value['id'])['snapshot']
    assert read['case_context']['case']['id'] == record.id
    assert 'quality' in read['case_context']['detail_profile']['data']


def test_retry_resumes_saved_cursor_without_new_topic_generation(query_db, monkeypatch):
    cases(query_db, 5)
    monkeypatch.setattr(jobs, 'PAGE_SIZE', 2)
    topic = topics.create_topic(query_db, '可续算条件', {})
    identifier = _job(query_db, topic['id'])
    jobs.process_aggregate_job(query_db, identifier, max_pages=1)
    original = jobs._case_page

    def fail_page(*_args):
        raise ValueError('temporary_input_unavailable')

    monkeypatch.setattr(jobs, '_case_page', fail_page)
    assert jobs.process_aggregate_job(query_db, identifier, max_pages=1)['status'] == 'retry'
    row = query_db.get(AnalysisTopic, topic['id'], populate_existing=True)
    assert row.latest_job_id == identifier and row.requested_generation == 1
    event = query_db.get(OutboxEvent, identifier, populate_existing=True)
    assert event.payload['cursor'] == 2 and event.payload['scanned_cases'] == 2
    event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    query_db.commit()
    monkeypatch.setattr(jobs, '_case_page', original)
    assert complete(query_db, identifier)['status'] == 'updated'
    assert query_db.query(TopicSnapshot).one().payload['aggregate']['statistics']['denominator'] == 5


def test_same_hash_after_intermediate_edit_does_not_reuse_old_revision(query_db):
    from app.services.case_source_service import CaseSourceService
    from app.services.profile_aggregate import checked_profile
    record = add_case(query_db, 'ABA', description='原始内容软管')
    first, _ = CaseSourceService.capture_change(query_db, record)
    saved = profile(query_db, record)
    saved.source_revision_id = first.id
    query_db.commit()
    assert checked_profile(query_db, record, saved)[1] == 'ready'
    record.description = '暂时变更'
    CaseSourceService.capture_change(query_db, record)
    record.description = '原始内容软管'
    current, _ = CaseSourceService.capture_change(query_db, record)
    query_db.commit()
    assert first.id != current.id and first.source_hash == current.source_hash
    assert checked_profile(query_db, record, saved)[1] == 'stale'


def test_road_business_changes_exclude_technical_versions(query_db):
    from app.services.topic_changes import semantic_changes
    case = cases(query_db, 1)[0]
    topic = topics.create_topic(query_db, '道路条件变化', {})
    topics.refresh_topic(query_db, topic['id'])
    initial = deepcopy(query_db.query(TopicSnapshot).one().payload)
    initial['references']['roads'] = [{'id': 'r1', 'case_id': case.id,
        'business_state': {'candidates': [{'asset_id': 1, 'eligibility': 'eligible', 'rank': 1, 'conditions': []}]}}]
    next_value = deepcopy(initial)
    next_value['references']['roads'][0]['id'] = 'r2'
    assert not semantic_changes(initial, next_value)['material_changed']
    next_value['references']['roads'][0]['business_state']['candidates'][0]['eligibility'] = 'excluded'
    assert semantic_changes(initial, next_value)['meaningful_items'][0]['code'] == 'candidate_excluded'


@pytest.mark.asyncio
async def test_business_queries_preserve_case_facility_and_historical_boundaries(query_db):
    from app.models.jurisdiction import JurisdictionAsset
    from app.services import intelligent_query_tasks as queries
    from app.services.topic_query_bridge import save_query_as_topic
    case = cases(query_db, 1)[0]
    query_db.add(JurisdictionAsset(id=72, operational_area_id=1, name='合成源井',
        asset_type='well', latitude=46.5, longitude=125.1))
    query_db.commit()
    for preset, arguments, kind, source_kind in [
        ('case_process', {'case_id': case.id}, 'case_gaps', 'case'),
        ('facility_dossier', {'asset_id': 72}, 'facility_context', 'facility'),
    ]:
        run = queries.create_query(query_db, '查看已有资料', preset={'name': preset, 'arguments': arguments})
        assert (await queries.execute_query(query_db, run['id']))['status'] == 'completed'
        topic = save_query_as_topic(query_db, run['id'], '持续关注已有资料')
        assert topic['question_kind'] == kind and topic['source_context']['kind'] == source_kind
    historical = queries.create_query(query_db, '查看当时资料', preset={'name': 'facility_history', 'arguments': {
        'asset_id': 72, 'valid_at': '2026-01-01T00:00:00Z', 'known_at': '2026-02-01T00:00:00Z'}})
    await queries.execute_query(query_db, historical['id'])
    with pytest.raises(ValueError, match='topic_query_conditions_unsupported'):
        save_query_as_topic(query_db, historical['id'], '不能将历史时点转为当前资料')


def test_selected_definition_is_used_for_export_and_followup(query_db):
    from app.services.topic_document import build_topic_document
    from app.services.topic_query_bridge import query_topic
    cases(query_db, 1)
    original = topics.create_topic(query_db, '原来的问题标题', {'oil_types': ['原油']}, question='原油资料有什么变化')
    topics.refresh_topic(query_db, original['id'])
    topics.update_topic(query_db, original['id'], title='后来的柴油问题',
        filters={'oil_types': ['柴油']}, expected_definition_revision=1)
    document = build_topic_document(query_db, original['id'], 1)
    assert '原来的问题标题' in document.blocks[1].text
    assert '后来的柴油问题' not in str(document.blocks)
    followup = query_topic(query_db, original['id'], 1, '解释当时的材料')
    assert followup['initial_context']['conditions']['case_filters']['oil_types'] == ['原油']


def test_scope_moved_record_is_not_exposed_in_new_change_notice(query_db):
    from app.services.daily_workbench_service import DailyWorkbenchService
    case = cases(query_db, 1)[0]
    topic = topics.create_topic(query_db, '变化不能暴露已受限资料', {})
    topics.refresh_topic(query_db, topic['id'])
    case.operational_area_id = 2
    query_db.commit()
    topics.request_refresh(query_db, topic['id'])
    assert topics.refresh_topic(query_db, topic['id'])['status'] == 'updated'
    new = topics.read_topic(query_db, topic['id'])['snapshot']
    assert new['changes']['comparison_state'] == 'restricted'
    assert not new['changes']['meaningful_items']
    assert not DailyWorkbenchService.daily(query_db)['changes']


@pytest.mark.parametrize('change_kind', ['revoked', 'revision', 'evidence'])
def test_facility_population_uses_only_current_available_recorded_links(recorded, change_kind):
    from app.models.case_source import EvidenceObject
    from app.services.case_facility_association_service import record_association, revoke_association
    from app.services.case_service import CaseService
    from app.services.topic_definitions import source_filters
    db, asset, case, fields = recorded
    if change_kind == 'evidence':
        from app.models.case import CaseEvidence
        from app.models.case_source import SourceReference
        from app.services.case_source_service import CaseSourceService
        obj = EvidenceObject(storage_key='synthetic-topic-evidence', sha256='b' * 64,
            media_type='application/pdf', sensitivity='internal', availability='available', content=b'synthetic')
        db.add(obj); db.flush()
        reference = SourceReference(case_id=case.id, evidence_object_id=obj.id, kind='evidence', locator={'title': '合成材料'})
        db.add(reference); db.flush()
        db.add(CaseEvidence(case_id=case.id, source_reference_id=reference.id, evidence_object_id=obj.id, title='合成材料'))
        revision, _ = CaseSourceService.capture_change(db, case)
        db.commit()
        fields = {**fields, 'source_reference_id': reference.id, 'source_revision_id': revision.id}
    row, _ = record_association(db, asset_id=asset.id, **fields)
    db.commit()
    source = {'kind': 'facility', 'id': asset.id}

    def count():
        return jobs._case_query(db, {'arguments': source_filters(db, source),
            'definition': {'source_context': source}}).count()

    assert count() == 1
    if change_kind == 'revoked':
        revoke_association(db, row.id, note='合成材料经核对撤销')
        db.commit()
    elif change_kind == 'revision':
        CaseService.update_case(db, case.id, description='已不包含原有设施条件')
    else:
        obj.availability = 'revoked'
        db.commit()
    assert count() == 0


def test_unknown_record_leaving_scope_is_not_reported_as_gap_filled(query_db):
    from app.services.topic_changes import semantic_changes
    record = add_case(query_db, 'UNKNOWN-NO-PROFILE', description='发现软管')
    query_db.commit()
    args = AggregateProfiles(conditions=[{'category': 'tool', 'value': '软管', 'kind': 'stated'}])
    old = build_aggregate(query_db, args)
    empty = build_aggregate(query_db, args, case_ids=[])
    assert old['statistics']['unknown'] == 1 and empty['statistics']['unknown'] == 0
    assert not any(item['code'] == 'gaps_resolved' for item in semantic_changes(
        {'aggregate': old}, {'aggregate': empty})['meaningful_items'])
    profile(query_db, record)
    ready = build_aggregate(query_db, args)
    messages = semantic_changes({'aggregate': old}, {'aggregate': ready})['meaningful_items']
    filled = next(item for item in messages if item['code'] == 'gaps_resolved')
    assert filled['evidence_refs']


def _job(db, topic_id):
    row = db.get(AnalysisTopic, topic_id)
    job = jobs.create_aggregate_job(db, row.filters, topic=row)
    db.commit()
    return job['id']


def test_business_changes_not_refreshes_create_workbench_items(query_db):
    from app.services.daily_workbench_service import DailyWorkbenchService
    record = cases(query_db, 1)[0]
    created = topics.create_topic(query_db, '条件变化', {})
    topics.refresh_topic(query_db, created['id'])
    assert DailyWorkbenchService.daily(query_db)['changes'] == []
    topics.request_refresh(query_db, created['id'])
    assert topics.refresh_topic(query_db, created['id'])['status'] == 'unchanged'
    assert DailyWorkbenchService.daily(query_db)['changes'] == []
    record.description = '村屯发现油罐。'
    query_db.commit()
    from app.models.case_pipeline import CaseAnalysisProfile
    query_db.query(CaseAnalysisProfile).filter_by(case_id=record.id).update({'is_current': False})
    new_profile = profile(query_db, record)
    new_profile.profile_version = 2
    query_db.commit()
    topics.request_refresh(query_db, created['id'])
    assert topics.refresh_topic(query_db, created['id'])['status'] == 'updated'
    changes = DailyWorkbenchService.daily(query_db)['changes']
    assert changes and changes[0]['items'][0]['code'] == 'conditions_changed'
    assert not query_db.dirty and not query_db.new


def test_change_notifications_coalesce_and_late_events_are_not_lost(query_db):
    record = cases(query_db, 1)[0]
    created = topics.create_topic(query_db, '持续关注', {})
    topics.refresh_topic(query_db, created['id'])
    consume_changes(query_db)  # Old seed events must not requeue fresh inputs.
    row = query_db.get(AnalysisTopic, created['id'])
    generation = row.requested_generation
    for text in ('新资料一', '新资料二', '新资料三'):
        record.description = text
        query_db.commit()
    assert consume_changes(query_db) == 1
    query_db.refresh(row)
    assert row.requested_generation == generation + 1
    assert consume_changes(query_db) == 0
    assert row.refresh_state == 'queued'
    jobs.create_aggregate_job(query_db, row.filters, topic=row)
    row.refresh_state = 'running'
    query_db.commit()
    previous_job = row.latest_job_id
    record.description = '扫描中再次补充'
    query_db.commit()
    assert consume_changes(query_db) == 1
    assert query_db.get(OutboxEvent, previous_job, populate_existing=True).status == 'superseded'
    assert row.requested_generation == generation + 2


def test_revision_metadata_uses_same_transaction_without_business_scope_queries(query_db):
    from sqlalchemy import event
    record = cases(query_db, 1)[0]
    query_db.commit()
    before = current_revision(query_db)
    orm_revision_reads = []
    def observe(state):
        if state.is_select and 'topic_data_revision' in str(state.statement):
            orm_revision_reads.append(state.statement)
    event.listen(query_db, 'do_orm_execute', observe)
    try:
        record.description = '仅合成：尚未提交的来源变化'
        query_db.flush()
        after = current_revision(query_db)
        assert after > before
        assert query_db.query(OutboxEvent).filter_by(event_type=EVENT_TYPE).filter(
            OutboxEvent.payload['data_revision'].as_integer() == after).count() == 1
        assert orm_revision_reads == []
        query_db.rollback()
        assert current_revision(query_db) == before
    finally:
        event.remove(query_db, 'do_orm_execute', observe)


def test_cancel_and_expired_worker_fences_are_durable(query_db, monkeypatch):
    cases(query_db)
    monkeypatch.setattr(jobs, 'PAGE_SIZE', 2)
    created = topics.create_topic(query_db, '持续关注', {})
    identifier = _job(query_db, created['id'])
    event, claimed = jobs.OutboxClaimService.claim(query_db, identifier, expected_type=jobs.EVENT_TYPE)
    assert claimed
    assert jobs.process_aggregate_job(query_db, identifier)['claimed'] is False
    old_token = event.worker_id
    event.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    query_db.commit()
    assert jobs.process_aggregate_job(query_db, identifier, max_pages=1)['status'] == 'running'
    assert query_db.get(OutboxEvent, identifier, populate_existing=True).worker_id != old_token
    topics.cancel_refresh(query_db, created['id'])
    assert jobs.process_aggregate_job(query_db, identifier)['status'] == 'cancelled'
    assert query_db.query(TopicSnapshot).count() == 0
    assert not topics.read_topic(query_db, created['id'])['paused']


def test_revocation_hides_completed_continuation_and_workbench(query_db):
    from app.models.map_foundation import UserAreaScope
    from app.services.daily_workbench_service import DailyWorkbenchService
    cases(query_db, 1)
    jobs._authority(query_db)
    job = jobs.create_aggregate_job(query_db, {}, query_id='revocable')
    query_db.commit()
    assert complete(query_db, job['id'])['status'] == 'completed'
    assert jobs.read_aggregate_job(query_db, job['id'])['result']['total'] == 1
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    with pytest.raises(PermissionError):
        jobs.read_aggregate_job(query_db, job['id'])
    assert DailyWorkbenchService.daily(query_db)['changes'] == []


def test_case_and_facility_repeated_refresh_have_no_technical_noise(query_db):
    from app.models.jurisdiction import JurisdictionAsset
    from app.services.daily_workbench_service import DailyWorkbenchService
    from app.services.topic_changes import semantic_changes, comparable_payload
    record = cases(query_db, 1)[0]
    query_db.add(JurisdictionAsset(id=71, operational_area_id=1, name='合成关注井',
        asset_type='well', latitude=46.5, longitude=125.1))
    query_db.commit()
    for source, kind in [({'kind': 'case', 'id': record.id}, 'case_gaps'),
                         ({'kind': 'facility', 'id': 71}, 'facility_context')]:
        created = topics.create_topic(query_db, '反复读取无噪声', {}, source_context=source, question_kind=kind)
        assert complete(query_db, _job(query_db, created['id']))['status'] == 'updated'
        first = topics.read_topic(query_db, created['id'])['snapshot']
        if kind == 'facility_context':
            assert first['facility_context']['facility']['id'] == 71
            assert first['aggregate']['coverage']['authorized_cases'] == 0  # nearby is not recorded association
        topics.request_refresh(query_db, created['id'])
        assert complete(query_db, _job(query_db, created['id']))['status'] == 'unchanged'
        assert not DailyWorkbenchService.daily(query_db)['changes']
        raw = query_db.query(TopicSnapshot).filter_by(topic_id=created['id']).one().payload
        technical = deepcopy(raw)
        key = 'case_context' if kind == 'case_gaps' else 'facility_context'
        technical[key]['generated_at'] = '2099-01-01T00:00:00Z'
        if key == 'facility_context':
            technical[key]['summary'] = {'state': 'ready', 'updated_at': '2099-01-01', 'revision': 100}
            technical[key]['versions']['view_version'] = 'technical-refresh'
        assert comparable_payload(technical) == comparable_payload(raw)
        assert not semantic_changes(raw, technical)['material_changed']
