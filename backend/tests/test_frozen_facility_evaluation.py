"""Fixed old-source/new-road scoring, not claims of real routing accuracy."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.case import Case
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.road_network import RoadAccessMembership
from app.services import frozen_evaluation_service as evaluation
from app.services.frozen_facility_inputs import replay_facility_inputs
from app.services.frozen_insight_inputs import checksum
from app.services.case_road_artifact_service import freeze_road_artifact
from test_facility_document_map import comparison, db_session, result_data, ready  # noqa: F401
from test_case_facility_comparison import prepared as prepared_base  # noqa: F401


@pytest.fixture
def prepared(prepared_base):
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_result_service import CaseResultService
    db, _, calls = prepared_base
    case = db.get(Case, 1)
    case.latitude, case.longitude, case.oil_type, case.facility_type = 46., 125., '原油', '井口'
    profile = db.get(CaseAnalysisProfile, 'profile-1')
    profile.source_hash = CasePipelineService.source_hash(db, case)
    profile.payload = {**profile.payload, 'source_hash': profile.source_hash}
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    return db, source, calls


def dataset(comparison, labels=False, negative=False):
    db, _, _, artifact = comparison
    return evaluation.create_dataset(db, name='合成道路固定对照', version='1', inputs=[],
        facility_artifact_ids=[artifact['id']],
        ground_truth={'1': [{'hypothesis_type': 'possible_source', 'expected_asset_ids': [13]}]} if labels else {},
        negative_case_ids=[1] if negative else [])


def test_old_scorer_and_frozen_road_pool_show_rank_difference(comparison, monkeypatch):
    db, _, content, _ = comparison
    frozen = dataset(comparison, labels=True)
    def no_live(*args, **kwargs):
        raise AssertionError('replay must not retrieve or route live inputs')
    monkeypatch.setattr('app.repositories.spatial_repository.SpatialRepository.nearby_assets', no_live)
    monkeypatch.setattr('app.services.facility_road_batches.calculate_distance_matrix', no_live)
    old = evaluation.run_evaluation(db, frozen.id, scorer_policy='captured')
    new = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert old.metrics['positive_top1_hit_rate'] == 0
    assert new.metrics['positive_top1_hit_rate'] == 1
    assert new.metrics['positive_top3_hit_rate'] == 1
    assert old.trace_manifest['records'][0]['candidate_count'] == 1
    assert new.trace_manifest['records'][0]['candidate_count'] == 3
    replay = replay_facility_inputs(frozen.manifest['entries'][0])
    assert [item['asset_id'] for item in replay['candidates']] == [item['asset_id'] for item in content['result']['candidates']]
    report = evaluation.compare_runs(db, old.id, new.id)
    assert report['mode'] == 'algorithm_comparison'
    assert report['counts']['improved'] == 1 and report['evaluation_family'] == 'facility_source'
    db.get(Case, 1).description = '后续原文变化不能改变冻结评测'
    db.commit()
    repeated = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert repeated.metrics == new.metrics and repeated.trace_manifest == new.trace_manifest


def test_unlabeled_changes_are_not_improvements_and_road_revocation_blocks_history(comparison):
    db, _, _, _ = comparison
    frozen = dataset(comparison)
    old = evaluation.run_evaluation(db, frozen.id)
    new = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert new.metrics['positive_top1_hit_rate'] is None
    assert evaluation.compare_runs(db, old.id, new.id)['counts']['unlabeled_changed'] == 1
    assert evaluation.compare_runs(db, old.id, new.id)['counts']['improved'] == 0
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        evaluation.read_run(db, new.id)


def test_unsupported_old_artifact_does_not_infer_full_pool_from_top_three(comparison):
    db, _, content, _ = comparison
    legacy = deepcopy(content)
    del legacy['result']['scoring_evidence']
    artifact = freeze_road_artifact(db, legacy)
    db.commit()
    with pytest.raises(ValueError, match='inputs_not_recorded'):
        evaluation.create_dataset(db, name='旧附件', version='1', inputs=[], facility_artifact_ids=[artifact['id']])


def test_changed_implementation_counts_failure_instead_of_silent_replay(comparison, monkeypatch):
    db, _, _, _ = comparison
    frozen = dataset(comparison, negative=True)
    from app.services import frozen_facility_inputs as replay
    original = replay.resolve_facility_scorer
    monkeypatch.setattr(replay, 'resolve_facility_scorer', lambda version: (original(version)[0], 'changed-code'))
    run = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert run.metrics['failed_case_count'] == 1
    assert run.metrics['negative_correct_empty_rate'] == 0
    assert run.status == 'partial_failure'


def test_incomplete_empty_pool_does_not_pass_negative_label(comparison):
    db, _, content, _ = comparison
    failed = deepcopy(content)
    for row in failed['result']['scoring_evidence']:
        row['road_state'], row['road_distance_m'] = 'calculation_failed', None
    failed['result']['coverage']['complete'] = False
    artifact = freeze_road_artifact(db, failed)
    db.commit()
    frozen = evaluation.create_dataset(db, name='合成故障输入', version='1', inputs=[],
        facility_artifact_ids=[artifact['id']], negative_case_ids=[1])
    run = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert run.metrics['negative_correct_empty_rate'] == 0
    assert run.metrics['incomplete_case_count'] == 1 and run.status == 'incomplete'


def test_changed_frozen_evidence_rejected_even_if_dataset_checksum_recomputed(comparison):
    db, _, _, _ = comparison
    frozen = dataset(comparison)
    manifest = deepcopy(frozen.manifest)
    envelope = manifest['entries'][0]
    envelope['payload']['facility_evaluation']['evidence'][0]['road_distance_m'] = 1
    envelope['checksum'] = checksum(envelope['payload'])
    frozen.manifest, frozen.checksum = manifest, checksum(manifest)
    db.commit()
    with pytest.raises(ValueError, match='binding_changed'):
        evaluation.read_dataset(db, frozen.id)


def test_late_grading_failure_is_not_counted_as_success(comparison, monkeypatch):
    db, _, _, _ = comparison
    frozen = dataset(comparison, labels=True)
    def fail(*args):
        raise ValueError('grading failed after candidate match')
    monkeypatch.setattr(evaluation, 'candidate_observations', fail)
    run = evaluation.run_evaluation(db, frozen.id, scorer_policy='facility_captured')
    assert run.metrics['failed_case_count'] == 1
    assert run.metrics['positive_top3_hit_rate'] == 0 and run.metrics['positive_top1_hit_rate'] == 0


def test_facility_archive_api_requires_admin_and_never_exports_raw_inputs(comparison):
    from app.api import governance
    from app.database import get_db
    db, _, _, artifact = comparison
    app = FastAPI()
    app.include_router(governance.router, prefix='/api')
    role = {'value': 'admin'}
    @app.middleware('http')
    async def principal(request, call_next):
        request.state.principal = SimpleNamespace(role=role['value'], user_id=1)
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: db
    payload = {'name': '接口归档合成集', 'version': '1', 'artifact_ids': [artifact['id']]}
    with TestClient(app) as client:
        response = client.post('/api/admin/evaluations/facility-datasets', json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data['evaluation_family'] == 'facility_source' and not data['frozen_input_exported']
        assert 'manifest' not in data and 'evidence' not in data
        run = client.post('/api/admin/evaluations/fixed-run', json={'dataset_id': data['id'], 'scorer_policy': 'facility_captured'})
        assert run.status_code == 201, run.text
        assert run.json()['metrics']['unlabeled_case_count'] == 1
        role['value'] = 'analyst'
        assert client.post('/api/admin/evaluations/facility-datasets', json=payload).status_code == 403
