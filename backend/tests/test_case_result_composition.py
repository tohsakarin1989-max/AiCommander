"""Isolated SQLite composition contracts; route responses remain synthetic."""
from copy import deepcopy

import pytest

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.models.road_network import RoadAccessMembership, RoadAccessGroup
from app.services.case_facility_comparison import compare_case_facilities
from app.services.case_pipeline_service import CASE_PROFILE_SCHEMA_VERSION
from app.services.case_local_semantic_model import resolve_model_plan
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.case_result_document import build_case_result_document, load_case_result_document
from app.services.case_result_composition import COMPOSITION_SCHEMA_VERSION, resolve_result_components
from app.services.intelligent_query_results import result_content
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def composed(prepared):
    db, _, calls = prepared
    profile = db.get(CaseAnalysisProfile, 'profile-1')
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = resolve_model_plan(db).version
    db.commit()
    base, _ = CaseResultService.create_current(db, 1)
    db.commit()
    road = compare_case_facilities(db, result_id=base['id'], network_id='graph-1',
        analysis_at=AT, vehicle=VEHICLE, artifact_root=None)
    artifact = freeze_road_artifact(db, road)
    db.commit()
    return db, base, artifact, road, calls


def test_immutable_dag_idempotency_and_no_road_task_loop(composed):
    db, base, artifact, road, calls = composed
    old = deepcopy(base)
    result = CaseResultService.latest(db, 1)
    assert result['content']['schema_version'] == COMPOSITION_SCHEMA_VERSION
    assert result['composition_status'] == 'ready'
    assert result['content']['composition']['base_result_id'] == base['id']
    assert result['content']['composition']['road_artifact_id'] == artifact['id']
    assert result['content']['candidates'][0]['asset_id'] == 13
    assert all(item['title'] != '测试候选' for item in result['content']['candidates'])
    count = db.query(CaseResultSnapshot).count()
    jobs = db.query(OutboxEvent).count()
    duplicate = freeze_road_artifact(db, road)
    db.commit()
    assert not duplicate['created']
    assert CaseResultService.latest(db, 1)['id'] == result['id']
    assert db.query(CaseResultSnapshot).count() == count
    assert db.query(OutboxEvent).count() == jobs
    assert CaseResultService.read(db, base['id']) == old
    assert CaseResultService.latest_base(db, 1)['id'] == base['id']
    assert len(calls) == 2  # GET and duplicate freeze perform no routing.


def test_document_map_query_share_composition_identity(composed, result_data):
    from app.services.case_result_map import frozen_result_map_input
    db, base, artifact, _, _ = composed
    result = CaseResultService.latest(db, 1)
    pure = build_case_result_document(result)
    document = load_case_result_document(db, result['id'])
    assert pure == document and document.result_id == result['id']
    assert document.road_artifact_id == artifact['id']
    assert '合成设施13' in '\n'.join(block.text for block in document.blocks)
    assert not any('测试候选' in block.text for block in document.blocks)
    assert frozen_result_map_input(result['content'])['reference_points'][0]['id'] == '13'
    answer = result_content(db, result_data[1])
    assert answer['result_id'] == result['id']
    assert answer['hypotheses'][0]['asset_id'] == 13
    _, resolved, parent = resolve_result_components(db, result['id'])
    assert resolved['id'] == base['id'] and parent['id'] == artifact['id']
    with pytest.raises(ValueError, match='attachment_mismatch'):
        resolve_result_components(db, result['id'], 'unrelated')


@pytest.mark.parametrize('change', ['scope', 'principal', 'policy', 'membership', 'case_source'])
def test_stale_or_other_branch_never_becomes_current(composed, change):
    db, base, _, _, _ = composed
    current = CaseResultService.latest(db, 1)
    if change == 'scope':
        db.info['authorized_area_ids'] = (1, 2)
    elif change == 'principal':
        db.info['principal_user_id'] = 2
    elif change == 'policy':
        db.query(RoadAccessGroup).update({'policy_revision': 2})
    elif change == 'membership':
        db.query(RoadAccessMembership).delete()
    else:
        db.query(Case).filter_by(id=1).update({'description': '后来补充'})
    db.commit()
    result = CaseResultService.latest(db, 1)
    assert result['id'] == base['id'] and result['composition_status'] == 'road_not_ready'
    if change != 'case_source':
        with pytest.raises(PermissionError):
            CaseResultService.read(db, current['id'])
    else:
        assert result['freshness'] == 'pending_update'
        assert CaseResultService.read(db, current['id'])['id'] == current['id']


def test_attachment_and_composition_both_obey_outer_rollback(prepared):
    db, base, _ = prepared
    count = db.query(CaseResultSnapshot).count()
    road = compare_case_facilities(db, result_id=base['id'], network_id='graph-1',
        analysis_at=AT, vehicle=VEHICLE, artifact_root=None)
    frozen = freeze_road_artifact(db, road)
    db.rollback()
    assert db.query(CaseResultSnapshot).count() == count
    from app.models.case_road_artifact import CaseRoadArtifact
    assert db.get(CaseRoadArtifact, frozen['id']) is None


def test_combined_docx_uses_same_identity_and_road_map_binding(composed):
    import io
    import zipfile
    from PIL import Image
    from app.services.case_result_export import render_docx
    db, _, artifact, _, _ = composed
    result = CaseResultService.latest(db, 1)
    document = load_case_result_document(db, result['id'])
    png = io.BytesIO()
    Image.new('RGB', (960, 700), 'white').save(png, format='PNG')
    data = render_docx(document, map_image=png.getvalue())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read('word/document.xml').decode()
    assert result['id'] in xml and artifact['id'] in xml
    assert '合成设施13' in xml and '测试候选' not in xml


def test_v60_storage_guard_does_not_rewrite_frozen_v34_algorithm():
    from types import SimpleNamespace
    from app.services.scorers.registry import resolve_scorer
    from app.services.scorers.dual_domain_v34 import STORAGE_TYPES
    old, old_hash = resolve_scorer('dual-domain-3.4.0')
    new, new_hash = resolve_scorer('dual-domain-6.0.0-1')
    asset = SimpleNamespace(id=10, name='仅邻近的村屯', verified=True, asset_type='village', latitude=46., longitude=125.)
    case = SimpleNamespace(latitude=46., longitude=125., operational_area_id=1)
    profile, snapshot = SimpleNamespace(id='p'), SimpleNamespace(id='map', operational_area_id=1)
    class Repository:
        @staticmethod
        def nearby_assets(db, **kwargs):
            return [(asset, .1)] if kwargs['asset_types'] == STORAGE_TYPES else []
    assert old._storage_candidates(None, case, profile, snapshot, Repository)
    assert new._storage_candidates(None, case, profile, snapshot, Repository) == []
    assert old_hash != new_hash


@pytest.mark.parametrize('change', ['membership', 'policy'])
def test_cached_query_reauthorizes_composition_on_read_followup_finish_and_export(composed, change):
    from app.models.user import User
    from app.models.map_foundation import UserAreaScope
    from app.services import intelligent_query_tasks as tasks
    from app.services.intelligent_query_tools import execute_tool
    from app.services.intelligent_query_document import export_query_document
    db, _, _, _, _ = composed
    db.get(User, 1).role = 'analyst'
    db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='read'))
    db.commit()
    query = tasks.create_query(db, '汇总已有研判成果')
    attempt = tasks.claim_query(db, query['id'])
    payload = {'status': 'completed', 'cards': [execute_tool(db, 'summarize_results', {})],
               'trace': [], 'error_code': None}
    assert payload['cards'][0]['data']['items'][0]['composition']
    assert tasks.finish_query(db, query['id'], attempt, payload)
    assert tasks.read_query(db, query['id'])['result']['cards']
    pending = tasks.create_query(db, '另一条汇总')
    pending_attempt = tasks.claim_query(db, pending['id'])
    followup = tasks.create_query(db, '继续', parent_query_id=query['id'])
    followup_attempt = tasks.claim_query(db, followup['id'])
    if change == 'membership':
        db.query(RoadAccessMembership).delete()
    else:
        db.query(RoadAccessGroup).update({'policy_revision': 2})
    db.commit()
    for action in (
        lambda: tasks.read_query(db, query['id']),
        lambda: tasks.create_query(db, '继续追问', parent_query_id=query['id']),
        lambda: tasks.finish_query(db, pending['id'], pending_attempt, payload),
        lambda: tasks.finish_query(db, followup['id'], followup_attempt, payload),
        lambda: export_query_document(db, query['id'], 'docx'),
    ):
        with pytest.raises(PermissionError, match='query_road_evidence_changed'):
            action()


def test_historical_query_window_never_substitutes_current_other_run(composed):
    from datetime import datetime, timezone
    from app.models.case_insight import CaseAnalysisRun
    from app.services.case_result_snapshot import assemble_case_result
    from app.services.intelligent_query_tools import execute_tool
    db, _, _, _, _ = composed
    current = CaseResultService.latest(db, 1)
    old_time = datetime(2020, 1, 2, tzinfo=timezone.utc)
    old_run = CaseAnalysisRun(id='historical-run', case_id=1, case_profile_id='profile-1',
        map_snapshot_id='map-1', algorithm_version='historical-test', status='completed',
        started_at=old_time, completed_at=old_time, summary='只有旧范围', information_gaps=[])
    db.add(old_run)
    db.flush()
    old_id, _ = CaseResultService._persist(db, assemble_case_result(
        db.get(CaseAnalysisProfile, 'profile-1'), old_run, []))
    db.query(CaseResultSnapshot).filter_by(id=old_id).update({'created_at': old_time})
    db.commit()
    item = execute_tool(db, 'summarize_results', {'completed_after': '2020-01-01T00:00:00Z',
        'completed_before': '2020-02-01T00:00:00Z'})['data']['items'][0]
    assert item['result_id'] == old_id and item['run_id'] == old_run.id
    assert item['evidence_ref'] == f'case_result:{old_id}'
    assert item['algorithm_version'] == 'historical-test' and item['hypotheses'] == []
    unfiltered = execute_tool(db, 'summarize_results', {})['data']['items'][0]
    assert unfiltered['result_id'] == current['id']
    assert unfiltered['evidence_ref'] == f"case_result:{current['id']}"


def test_historical_road_query_reads_facility_artifact_without_matrix_shape(composed):
    from app.services.intelligent_query_tools import execute_tool
    from app.services.intelligent_query_roads import validate_road_query_evidence
    db, _, artifact, _, _ = composed
    card = execute_tool(db, 'find_road_results', {})
    item = card['data']['items'][0]
    assert item['artifact_id'] == artifact['id'] and item['operation'] == 'facility_comparison'
    assert item['candidates'][0]['asset_id'] == 13
    validate_road_query_evidence(db, {'cards': [card]})
    assert execute_tool(db, 'find_road_results', {'min_detour_ratio': 2})['data']['items'] == []


@pytest.mark.asyncio
async def test_composition_revocation_during_model_wait_discards_cards(composed):
    from types import SimpleNamespace
    from app.services.intelligent_query_loop import run_query
    db, _, _, _, _ = composed
    class Model:
        calls = 0
        async def ainvoke(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(content='{"action":"call","tool":"summarize_results","arguments":{}}')
            db.query(RoadAccessMembership).delete()
            db.commit()
            return SimpleNamespace(content='{"action":"finish","reason":"completed"}')
    result = await run_query(db, '汇总已有研判成果', Model())
    assert result['status'] == 'cancelled' and result['cards'] == [] and result['trace'] == []


def test_new_network_requires_new_composition_but_old_version_stays_readable(composed):
    from datetime import timedelta
    from app.models.road_network import RoadNetworkVersion
    db, base, _, _, _ = composed
    old = CaseResultService.latest(db, 1)
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.valid_from = AT - timedelta(days=1)
    replacement = {column.name: getattr(graph, column.name) for column in graph.__table__.columns
                   if column.name not in {'id', 'created_at'}}
    replacement.update(id='graph-2', valid_from=AT, graph_sha256='d' * 64,
                       conditions_sha256='d' * 64)
    db.add(RoadNetworkVersion(**replacement))
    db.commit()
    assert CaseResultService.latest(db, 1)['id'] == base['id']
    assert CaseResultService.latest(db, 1)['composition_status'] == 'road_not_ready'
    assert CaseResultService.read(db, old['id'])['id'] == old['id']


def test_late_old_attachment_does_not_replace_new_base(composed):
    db, old_base, _, old_road, _ = composed
    profile = db.get(CaseAnalysisProfile, 'profile-1')
    profile.is_current = False
    case = db.get(Case, 1)
    case.description = '后来补充的新记录'
    db.flush()
    from app.services.case_pipeline_service import CasePipelineService
    source_hash = CasePipelineService.source_hash(db, case)
    db.add(CaseAnalysisProfile(id='new-profile', case_id=1, profile_version=2,
        source_hash=source_hash, schema_version=profile.schema_version,
        dictionary_version=profile.dictionary_version, payload={**deepcopy(profile.payload), 'source_hash': source_hash},
        quality_score=profile.quality_score, analysis_readiness=profile.analysis_readiness,
        is_current=True))
    db.commit()
    newer, _ = CaseResultService.create_current(db, 1)
    db.commit()
    assert newer['id'] != old_base['id']
    freeze_road_artifact(db, old_road)
    db.commit()
    assert CaseResultService.latest(db, 1)['id'] == newer['id']
