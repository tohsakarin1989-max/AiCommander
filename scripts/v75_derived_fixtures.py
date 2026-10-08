"""Disposable metadata/scan-only fixtures, not a real road-engine demonstration."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4


def seed_v75(db, snapshot, root):
    from app.database import bind_principal_scope
    from app.models.case_insight import CaseAnalysisRun
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.map_foundation import MapSnapshotFeature
    from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
    from app.models.user import User
    from app.services import case_road_jobs, facility_job_checkpoint
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_status import automatic_comparison_status
    from app.services.road_access_policy import VehicleAssumption
    from tests.test_case_search_page import add_case
    from tests.test_query_profiles import profile

    admin = db.query(User).filter_by(username='v72-admin').one()
    bind_principal_scope(db, SimpleNamespace(user_id=admin.id, role=admin.role), method='POST')
    failed_case = add_case(db, 'V75-FAILED-SYNTHETIC', description='合成失败恢复原文，不得由重试改写。')
    failed = CasePipelineService.enqueue_case_change(db, failed_case)
    failed.status, failed.attempts, failed.error = 'failed', 3, 'synthetic-failure'
    db.commit()

    case = add_case(db, 'V75-SCAN-SYNTHETIC', description='合成扫描进度，非真实道路执行。',
                    latitude=46.5, longitude=125.1, location='合成验收位置，非真实业务点位')
    case_profile = profile(db, case)
    db.add(CaseAnalysisRun(id=str(uuid4()), case_id=case.id, case_profile_id=case_profile.id,
        map_snapshot_id=snapshot.id, algorithm_version='synthetic-browser-metadata', status='completed',
        information_gaps=['隔离合成底图与设施，仅用于进度界面验证，未执行真实路由。']))
    for index in range(12):
        asset = JurisdictionAsset(operational_area_id=1, name=f'合成进度设施{index + 1}',
            asset_type='well', latitude=46.5, longitude=125.1 + index / 1000,
            verified=False, source='manual', status='active')
        db.add(asset); db.flush()
        db.add(MapSnapshotFeature(snapshot_id=snapshot.id, asset_id=asset.id, operational_area_id=1,
            name=asset.name, asset_type='well', geometry_type='point', status='active', source='manual',
            verified=False, latitude=asset.latitude, longitude=asset.longitude, attributes={}))
    vehicle = VehicleAssumption(kind='auto', source='explicit_reference_assumption')
    at = datetime.now(timezone.utc)
    group = RoadAccessGroup(name='合成进度通行组（非真实道路授权）')
    db.add(group); db.flush()
    db.add(RoadAccessMembership(group_id=group.id, user_id=admin.id, valid_from=at - timedelta(days=1)))
    db.add(RoadNetworkVersion(id='v75-synthetic-graph-metadata', group_id=group.id, policy_revision=1,
        public_bundle_id=snapshot.public_bundle_id, input_sha256='a' * 64, conditions_sha256='b' * 64,
        graph_sha256='c' * 64, artifact_key='c' * 64, engine_version='synthetic-no-matrix',
        builder_version='synthetic-metadata-only', status='ready', valid_from=at - timedelta(days=1),
        source_manifest={'internal_area_ids': [1], 'vehicle': vehicle.model_dump()}))
    db.commit()
    source, _ = CaseResultService.create_current(db, case.id)
    db.commit()
    job = case_road_jobs.enqueue_comparison(db, result_id=source['id'], analysis_at=at,
        vehicle=vehicle, engine_version='synthetic-no-matrix', include_facility_pool=True)
    db.commit()

    # Run the real scanning/checkpoint writer, yielding before any entrance or
    # native matrix stage. This temporary budget changes no production setting.
    original_limit = facility_job_checkpoint.SCAN_LIMIT
    try:
        facility_job_checkpoint.SCAN_LIMIT = 3
        outcome = case_road_jobs.process_comparison(db, job['event_id'], artifact_root=root / 'unused-road-artifacts')
    finally:
        facility_job_checkpoint.SCAN_LIMIT = original_limit
    if outcome['status'] != 'pending':
        raise RuntimeError(f'synthetic_scan_did_not_yield:{outcome}')
    status = automatic_comparison_status(db, source['id'])
    if status.get('progress', {}).get('scanned') != 3:
        raise RuntimeError('synthetic_scan_progress_unavailable')
    return {'failed_case_id': failed_case.id, 'failed_event_id': failed.id,
        'failed_original': failed_case.description, 'progress_case_id': case.id,
        'progress_result_id': source['id'], 'progress_content_sha256': source['content_sha256'],
        'progress_event_id': job['event_id'], 'progress': status['progress'],
        'boundary': '扫描服务真实运行并保存3个合成设施的进度；无真实入口、矩阵或完整道路执行。'}
