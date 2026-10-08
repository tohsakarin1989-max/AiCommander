"""Synthetic persisted topics: exact dismissals, scope-first grouping and no read writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models.analysis_topic import AnalysisTopic, TopicSnapshot, TopicChangeDismissal
from app.services import analysis_topic_service as topics
from app.services.intelligent_query_context import result_hash
from app.services.topic_notifications import daily_changes
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_analysis_topics import client_for, seed


def snapshot(db, topic, payload, revision=1, *, material=True):
    row = TopicSnapshot(id=str(uuid4()), topic_id=topic.id, revision=revision,
        content_sha256=result_hash(payload), payload=deepcopy(payload),
        changes={'material_changed': material, 'meaningful_items':
                 [{'code': 'case_gap', 'message': '合成资料发生变化', 'evidence_refs': []}] if material else []},
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=revision))
    db.add(row)
    db.commit()
    return row


def base(db, *, source=True):
    case = seed(db)
    value = topics.create_topic(db, '资料变化', {}, **({'source_context': {'kind': 'case', 'id': case.id},
        'question_kind': 'case_gaps'} if source else {}))
    topics.refresh_topic(db, value['id'])
    topic = db.get(AnalysisTopic, value['id'])
    first = db.query(TopicSnapshot).filter_by(topic_id=topic.id).one()
    return case, topic, first


def ref(topic, row):
    return {'topic_id': topic.id, 'snapshot_id': row.id, 'revision': row.revision,
            'content_sha256': row.content_sha256}


def test_policy_independent_from_pause_and_generation_and_get_is_readonly(query_db):
    _, topic, old = base(query_db)
    snapshot(query_db, topic, old.payload, 2)
    before = (topic.definition_revision, topic.requested_generation, topic.refresh_state, topic.next_refresh_at)
    with client_for(query_db) as client:
        url = f'/api/analysis-topics/{topic.id}'
        changed = client.patch(url, json={'notification_policy': 'muted'})
        assert changed.status_code == 200 and changed.json()['notification_policy'] == 'muted'
        assert not changed.json()['paused'] and daily_changes(query_db) == []
        assert (topic.definition_revision, topic.requested_generation, topic.refresh_state, topic.next_refresh_at) == before
        assert client.patch(url, json={'paused': True}).status_code == 200
        assert client.patch(url, json={'notification_policy': 'meaningful'}).json()['paused'] is True
        assert daily_changes(query_db) == []
        assert client.patch(url, json={'paused': False}).status_code == 200
        assert client.patch(url, json={'notification_policy': 'email'}).status_code == 422
    statements = []
    def record(_c, _cu, statement, _p, _ctx, _many):
        statements.append(statement)
    event.listen(query_db.bind, 'before_cursor_execute', record)
    try:
        assert len(daily_changes(query_db)) == 1
    finally:
        event.remove(query_db.bind, 'before_cursor_execute', record)
    assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
    assert not query_db.new and not query_db.dirty


def test_exact_dismissal_is_idempotent_new_revision_still_visible_and_atomic(query_db):
    _, topic, old = base(query_db)
    second = snapshot(query_db, topic, old.payload, 2)
    exact = ref(topic, second)
    with client_for(query_db) as client:
        url = '/api/analysis-topics/change-dismissals'
        bad = {**exact, 'revision': 900}
        assert client.post(url, json={'sources': [bad]}).status_code == 409
        assert client.post(url, json={'sources': [exact, exact]}).status_code == 422
        assert query_db.query(TopicChangeDismissal).count() == 0
        for _ in range(2):
            receipt = client.post(url, json={'sources': [exact]})
            assert receipt.status_code == 200 and receipt.json() == {'sources': [exact], 'dismissed': 1}
        assert query_db.query(TopicChangeDismissal).count() == 1 and daily_changes(query_db) == []
        third = snapshot(query_db, topic, old.payload, 3)
        assert daily_changes(query_db)[0]['sources'][0]['snapshot_id'] == third.id
        invalid_other = {**exact, 'snapshot_id': str(uuid4())}
        assert client.post(url, json={'sources': [ref(topic, third), invalid_other]}).status_code == 409
        assert query_db.query(TopicChangeDismissal).count() == 1
    assert not topic.paused


def test_acl_checked_before_notice_and_exact_dismiss(query_db):
    case, topic, old = base(query_db)
    second = snapshot(query_db, topic, old.payload, 2)
    case.operational_area_id = 2
    query_db.commit()
    assert daily_changes(query_db) == []
    with client_for(query_db) as client:
        assert client.post('/api/analysis-topics/change-dismissals', json={'sources': [ref(topic, second)]}).status_code == 403
    assert query_db.query(TopicChangeDismissal).count() == 0
    with client_for(query_db, uid=2) as client:
        assert client.post('/api/analysis-topics/change-dismissals', json={'sources': [ref(topic, second)]}).status_code == 404


def test_latest_per_topic_before_grouping_retains_over_100_sources(query_db):
    _, topic, old = base(query_db)
    payload = deepcopy(old.payload)
    for index in range(104):
        row = AnalysisTopic(id=str(uuid4()), created_by=topic.created_by, title=f'同对象 {index}',
            filters=topic.filters, question_kind=topic.question_kind, source_context=topic.source_context,
            scope_version=topic.scope_version, refresh_state='idle')
        query_db.add(row)
        snapshot(query_db, row, payload)
    snapshot(query_db, topic, payload, 2)
    # A single very active topic cannot push the other topics out of the selection.
    for revision in range(3, 107):
        snapshot(query_db, topic, payload, revision)
    groups = daily_changes(query_db)
    assert len(groups) == 1 and len(groups[0]['sources']) == 105
    assert {s['revision'] for s in groups[0]['sources'] if s['topic_id'] == topic.id} == {106}
    # A later technical-only snapshot suppresses its own old notice, not others.
    snapshot(query_db, topic, payload, 107, material=False)
    assert len(daily_changes(query_db)[0]['sources']) == 104


def test_condition_topics_do_not_merge_without_a_stable_object(query_db):
    _, topic, old = base(query_db, source=False)
    snapshot(query_db, topic, old.payload, 2)
    other = topics.create_topic(query_db, '相同名称不等于相同条件', {})
    row = query_db.get(AnalysisTopic, other['id'])
    snapshot(query_db, row, old.payload)
    groups = daily_changes(query_db)
    assert len(groups) == 2
    assert all(group['object'] is None and len(group['sources']) == 1 for group in groups)


def test_interval_time_is_not_a_missing_date(query_db):
    from app.services.daily_workbench_service import DailyWorkbenchService, information_gaps
    case = seed(query_db)
    case.location = '合成地点'
    case.occurred_time = None
    case.occurred_from = datetime(2026, 9, 1)
    case.occurred_to = datetime(2026, 9, 3)
    case.time_precision = 'interval'
    query_db.commit()
    assert '案发时间' not in information_gaps(case)
    payload = DailyWorkbenchService.daily(query_db)
    assert payload['summary']['needs_information'] == 0
    assert payload['cases'][0]['occurred_from'] is not None
    case.occurred_to = case.occurred_from
    query_db.commit()
    assert '案发时间' not in information_gaps(case)
    assert DailyWorkbenchService.daily(query_db)['summary']['needs_information'] == 0
    case.occurred_to = case.occurred_from - timedelta(days=1)
    query_db.commit()
    assert '案发时间' in information_gaps(case)
    assert DailyWorkbenchService.daily(query_db)['summary']['needs_information'] == 1
    case.occurred_to = None
    query_db.commit()
    assert '案发时间' in information_gaps(case)
    assert DailyWorkbenchService.daily(query_db)['summary']['needs_information'] == 1
