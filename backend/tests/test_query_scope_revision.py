import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.case import Case
from app.models.query_scope_revision import QueryScopeRevision
from app.services import intelligent_query_tasks as tasks
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case


def count_model():
    steps = iter([{'action': 'call', 'tool': 'count_cases', 'arguments': {}},
                  {'action': 'finish', 'reason': 'completed'}])
    class Model:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content=json.dumps(next(steps)))
    return Model()


@pytest.mark.asyncio
async def test_new_case_does_not_invalidate_history_or_followup(query_db):
    add_case(query_db, 'CASE-A')
    query_db.commit()
    first = tasks.create_query(query_db, '统计案件')
    await tasks.execute_query(query_db, first['id'], model=count_model())
    add_case(query_db, 'CASE-B')
    query_db.commit()
    assert tasks.read_query(query_db, first['id'])['result']['cards'][0]['data']['count'] == 1
    child = tasks.create_query(query_db, '现在再统计一次', first['id'])
    await tasks.execute_query(query_db, child['id'], model=count_model())
    assert tasks.read_query(query_db, child['id'])['result']['cards'][0]['data']['count'] == 2


def test_direct_sql_scope_move_and_rollback_are_transactional(query_db):
    case = add_case(query_db, 'MOVE')
    query_db.commit()
    run = tasks.create_query(query_db, '统计')
    revision = query_db.scalar(select(QueryScopeRevision.revision))
    query_db.execute(text('UPDATE cases SET operational_area_id=2 WHERE id=:id'), {'id': case.id})
    assert query_db.scalar(select(QueryScopeRevision.revision)) == revision + 1
    with pytest.raises(PermissionError, match='query_scope_changed'):
        tasks.read_query(query_db, run['id'])
    query_db.rollback()
    assert query_db.scalar(select(QueryScopeRevision.revision)) == revision
    assert tasks.read_query(query_db, run['id'])['status'] == 'queued'


def test_content_edit_keeps_history_but_deletion_invalidates(query_db):
    case = add_case(query_db, 'EDIT')
    query_db.commit()
    run = tasks.create_query(query_db, '统计')
    query_db.execute(text('UPDATE cases SET description=:description WHERE id=:id'),
                     {'description': '新描述', 'id': case.id})
    query_db.commit()
    assert tasks.read_query(query_db, run['id'])['status'] == 'queued'
    query_db.execute(text('DELETE FROM cases WHERE id=:id'), {'id': case.id})
    query_db.commit()
    with pytest.raises(PermissionError, match='query_scope_changed'):
        tasks.claim_query(query_db, run['id'])


@pytest.mark.asyncio
async def test_new_then_moved_case_during_model_wait_cancels(query_db):
    run = tasks.create_query(query_db, '统计案件')
    added = add_case(query_db, 'ARRIVED-AFTER-CREATE')
    query_db.commit()
    class Model:
        calls = 0
        async def ainvoke(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content='{"action":"call","tool":"count_cases","arguments":{}}')
            query_db.execute(Case.__table__.update().where(Case.id == added.id).values(operational_area_id=2))
            query_db.commit()
            return SimpleNamespace(content='{"action":"finish","reason":"completed"}')
    result = await tasks.execute_query(query_db, run['id'], model=Model())
    assert result['status'] == 'cancelled'
    from app.models.agent_run import AgentRun
    assert query_db.get(AgentRun, run['id']).result_summary == {}
