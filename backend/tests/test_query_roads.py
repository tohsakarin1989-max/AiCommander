from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from app.models.case import Case
from app.models.road_network import RoadAccessMembership
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.intelligent_query_tools import execute_tool
from app.services.intelligent_query_roads import validate_road_query_evidence
from tests.test_case_road_artifacts import artifact_input  # noqa: F401
from tests.test_road_network_service import ready  # noqa: F401
from tests.test_case_results import db_session, result_data  # noqa: F401


def route_content(content, ratio=1.5):
    result = deepcopy(content)
    result['schema_version'] = 'case-road-route-4.2.0-1'
    result['route'] = {**result.pop('matrix'), 'distance_m': 1500,
        'detour_reference': {'status': 'available', 'basis': 'route_geometry_endpoints',
            'ratio': ratio, 'road_distance_m': 1500, 'straight_distance_m': 1000},
        'shape_polyline6': 'not-exposed-to-query-model', 'alternatives': []}
    result['target'] = {'name': '合成候选井', 'asset_id': 1}
    return result


def test_query_reads_real_frozen_artifact_with_versions_and_detour(artifact_input):
    db, content = artifact_input
    saved = freeze_road_artifact(db, route_content(content))
    db.commit()
    card = execute_tool(db, 'find_road_results', {'min_detour_ratio': 1.3})
    assert card['state'] == 'ready'
    item = card['data']['items'][0]
    assert item['artifact_id'] == saved['id'] and item['artifact_sha256'] == saved['content_sha256']
    assert item['detour_reference']['ratio'] == 1.5
    assert item['graph_sha256'] == 'c' * 64 and item['policy_revision'] == 1
    assert 'shape_polyline6' not in str(card)
    assert execute_tool(db, 'find_road_results', {'min_detour_ratio': 2.0})['data']['items'] == []
    case = db.get(Case, 1)
    assert execute_tool(db, 'find_road_results', {'keyword': case.case_number})['data']['returned'] == 1
    assert execute_tool(db, 'find_road_results', {'keyword': '不存在的关键词'})['data']['items'] == []


def test_road_revocation_hides_new_and_cached_query_evidence(artifact_input):
    db, content = artifact_input
    freeze_road_artifact(db, route_content(content))
    db.commit()
    card = execute_tool(db, 'find_road_results', {})
    validate_road_query_evidence(db, {'cards': [card]})
    db.query(RoadAccessMembership).delete()
    db.commit()
    redacted = execute_tool(db, 'find_road_results', {})
    assert redacted['state'] == 'partial' and redacted['data']['items'] == []
    assert '合成候选井' not in str(redacted)
    with pytest.raises(PermissionError, match='query_road_evidence_changed'):
        validate_road_query_evidence(db, {'cards': [card]})


def test_page_limit_is_not_presented_as_total_or_no_results(artifact_input):
    db, content = artifact_input
    for ratio in (1.2, 1.4):
        freeze_road_artifact(db, route_content(content, ratio))
    db.commit()
    first = execute_tool(db, 'find_road_results', {'page_size': 1})
    second = execute_tool(db, 'find_road_results', {'page_size': 1, 'page': 2})
    assert first['state'] == 'partial' and first['data']['next_page'] == 2
    assert first['data']['items'][0]['artifact_id'] != second['data']['items'][0]['artifact_id']
    assert 'total' not in first['data']


def test_case_scope_filters_artifacts_and_arbitrary_engine_parameters_rejected(artifact_input):
    db, content = artifact_input
    freeze_road_artifact(db, route_content(content))
    db.commit()
    db.info['authorized_area_ids'] = ()
    assert execute_tool(db, 'find_road_results', {})['data']['items'] == []
    with pytest.raises(ValueError):
        execute_tool(db, 'find_road_results', {'ignore_restrictions': True})


@pytest.mark.asyncio
async def test_revocation_during_model_wait_discards_road_cards(artifact_input):
    from app.services.intelligent_query_loop import run_query
    db, content = artifact_input
    freeze_road_artifact(db, route_content(content))
    db.commit()
    class Model:
        calls = 0
        async def ainvoke(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content=json.dumps({'action': 'call', 'tool': 'find_road_results', 'arguments': {}}))
            db.query(RoadAccessMembership).delete()
            db.commit()
            return SimpleNamespace(content='{"action":"finish","reason":"completed"}')
    result = await run_query(db, '哪些路径绕行明显？', Model())
    assert result['status'] == 'cancelled'
    assert result['cards'] == [] and result['trace'] == []


def test_road_filter_cannot_be_silently_lost_in_case_count():
    from app.services.intelligent_query_context import empty_conditions, inherit, remember
    conditions = remember(empty_conditions(), 'find_road_results', {'min_detour_ratio': 1.5})
    with pytest.raises(ValueError, match='query_context_tool_cannot_preserve_filters'):
        inherit('count_cases', {}, conditions, question='这些有多少？')
