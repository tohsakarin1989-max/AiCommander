"""4.2 storage gate, only in the disposable database owned by the container runner.

Synthetic graph metadata is not a published/compiled production routing graph.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from threading import Barrier


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'verify'])
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    url = make_url(os.environ.get('DATABASE_URL', ''))
    if (os.environ.get('AIC_DISPOSABLE_ROAD_PG') != '1' or url.host != '127.0.0.1'
            or url.database != 'aic_road_test' or url.get_backend_name() != 'postgresql'):
        raise RuntimeError('explicit_local_disposable_database_required')
    backend = Path(__file__).resolve().parents[1] / 'backend'
    os.environ['SECRET_KEY'] = 'disposable-road-verification-only'
    os.environ['ENVIRONMENT'] = 'development'
    sys.path.insert(0, str(backend))
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import Session
    from app.models.case import Case, CaseVehicle
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.case_result import CaseResultSnapshot
    from app.models.case_road_artifact import CaseRoadArtifact
    from app.models.map_foundation import PublicMapBundle
    from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_artifact_service import freeze_road_artifact, read_road_artifact, road_artifact_history

    engine = create_engine(url, connect_args={'options': '-c statement_timeout=15000 -c lock_timeout=10000'})
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '4ef1b75a80e5'
    def bind(db):
        db.info.update(principal_user_id=991, authorized_area_ids=(991,), area_access_levels={991: 'manage'})
    if args.stage == 'prepare':
        with Session(engine) as db:
            bind(db)
            assert db.scalar(select(Case.id).where(Case.id == 991)) is None
            db.add(Case(id=991, case_number='SYNTHETIC-V41-ORIGINAL', occurred_time=datetime(2026, 9, 1),
                        description='合成原文：升级和道路计算不得覆盖。', operational_area_id=991))
            db.flush()
            # Use the actual 4.1 schema before adding road-condition columns.
            db.execute(text("INSERT INTO case_vehicles (case_id,vehicle_type,oil_volume) VALUES (991,'重型挂车',2.5)"))
            db.add(CaseAnalysisProfile(id='pg-road-profile', case_id=991, profile_version=1, source_hash='a' * 64,
                schema_version='4.1.0', dictionary_version='pg-synthetic-1', payload={
                    'source_hash': 'a' * 64, 'standard': {'location': '合成地点'}},
                quality_score=1, analysis_readiness='ready'))
            db.flush()
            CaseResultService.create_current(db, 991)
            db.commit()
        print(json.dumps({'v41_original_case_seeded': True}))
        engine.dispose()
        return

    with engine.connect() as connection:
        original = connection.scalar(text("SELECT to_jsonb(c)::text FROM cases c WHERE id=991"))
        frozen = connection.scalar(text("SELECT to_jsonb(c)::text FROM case_result_snapshots c WHERE case_id=991"))
        assert original and frozen
    command.upgrade(config, '82d5f19ec429')
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        bind(db)
        assert db.scalar(text("SELECT to_jsonb(c)::text FROM cases c WHERE id=991")) == original
        assert db.scalar(text("SELECT to_jsonb(c)::text FROM case_result_snapshots c WHERE case_id=991")) == frozen
        old_vehicle = db.scalar(select(CaseVehicle).where(CaseVehicle.case_id == 991))
        assert old_vehicle.vehicle_type == '重型挂车' and old_vehicle.oil_volume == 2.5
        assert old_vehicle.road_vehicle_kind is None and old_vehicle.height_m is None and old_vehicle.gross_weight_t is None
        for table in ['road_access_groups', 'road_access_memberships', 'road_access_grants',
                      'road_network_versions', 'road_public_aliases', 'case_road_artifacts']:
            assert db.scalar(text(f'SELECT count(*) FROM {table}')) == 0
        db.add(PublicMapBundle(id=991, bundle_id='pg-synthetic-public', provider='synthetic', source_version='1',
            license_record='synthetic only', bounds=[], manifest={}, package_hash='b' * 64))
        db.add(RoadAccessGroup(id=991, name='合成通行组'))
        db.flush()
        db.add(RoadAccessMembership(group_id=991, user_id=991, valid_from=now - timedelta(days=1)))
        db.add(RoadNetworkVersion(id='pg-synthetic-graph', group_id=991, policy_revision=1, public_bundle_id=991,
            input_sha256='a' * 64, conditions_sha256='b' * 64, source_manifest={'internal_area_ids': [],
                'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'}},
            engine_version='synthetic-not-executable', builder_version='synthetic-storage-check', status='ready',
            graph_sha256='c' * 64, artifact_key='c' * 64, valid_from=now - timedelta(hours=1)))
        # A post-upgrade original record must survive a rollback rehearsal in another DB.
        db.add(Case(id=992, case_number='SYNTHETIC-V42-NEW', occurred_time=datetime(2026, 9, 11),
                    description='合成升级后新增原文，恢复旧库不得丢弃。', operational_area_id=991))
        db.flush()
        db.add(CaseVehicle(case_id=992, vehicle_type='重型挂车', road_vehicle_kind='truck',
                           height_m=3.2, gross_weight_t=12.5, oil_volume=2.))
        db.commit()
        source = CaseResultService.latest(db, 991)
        content = {'schema_version': 'case-road-comparison-4.2.0-1', 'result_id': source['id'],
            'content_sha256': source['content_sha256'], 'map_snapshot_id': None,
            'targets': [], 'information_gaps': [], 'boundary': '合成存储验收，不证明道路计算正确',
            'matrix': {'network_id': 'pg-synthetic-graph', 'graph_sha256': 'c' * 64, 'policy_revision': 1,
                'analysis_at': now.isoformat(), 'vehicle': {'kind': 'auto', 'source': 'explicit_reference_assumption'}, 'cells': []}}
    barrier = Barrier(4, timeout=10)
    def concurrent_save(_):
        with Session(engine) as db:
            bind(db)
            barrier.wait()
            item = freeze_road_artifact(db, content)
            db.commit()
            assert read_road_artifact(db, item['id'])['content'] == content
            return item
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(concurrent_save, range(4)))
    assert sum(item['created'] for item in results) == 1
    assert len({item['id'] for item in results}) == 1
    with Session(engine) as db:
        bind(db)
        rollback_item = freeze_road_artifact(db, {**content, 'boundary': '合成事务回滚'})
        db.rollback()
        assert db.get(CaseRoadArtifact, rollback_item['id']) is None
        assert db.scalar(select(CaseRoadArtifact.id)) == results[0]['id']
        assert road_artifact_history(db, source['id'])['items'][0]['availability'] == 'available'
        db.query(RoadAccessMembership).delete()
        db.commit()
        try:
            read_road_artifact(db, results[0]['id'])
        except PermissionError:
            pass
        else:
            raise AssertionError('revoked_road_artifact_delivered')
        assert road_artifact_history(db, source['id'])['items'][0]['availability'] == 'unavailable'
        assert db.scalar(text("SELECT to_jsonb(c)::text FROM cases c WHERE id=991")) == original
        assert db.scalar(text("SELECT to_jsonb(c)::text FROM case_result_snapshots c WHERE case_id=991")) == frozen
        db.rollback()
    try:
        command.downgrade(config, '4ef1b75a80e5')
    except RuntimeError as error:
        assert 'restore_compatible_backup_required' in str(error)
    else:
        raise AssertionError('unsafe_downgrade_allowed')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '82d5f19ec429'
        assert connection.scalar(text('SELECT count(*) FROM case_road_artifacts')) == 1
        assert connection.scalar(text('SELECT count(*) FROM cases WHERE id IN (991,992)')) == 2
    print(json.dumps({'v42_migration': 'passed', 'original_case_and_snapshot_unchanged': True,
        'legacy_vehicle_preserved_without_inferred_mass': True,
        'concurrent_writers': 4, 'created_artifacts': 1, 'transaction_rollback': True,
        'revocation_denies_read': True, 'destructive_downgrade_rejected': True,
        'routing_graph_validated': False}))
    engine.dispose()


if __name__ == '__main__':
    main()
