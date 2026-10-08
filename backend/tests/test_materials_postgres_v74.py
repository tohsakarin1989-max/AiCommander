"""Opt-in real v7.4 upgrade, duplicate workers, preferences and restore.

Only new UUID databases in the existing loopback-only synthetic container are
accepted. Databases are retained, never dropped or reused.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.environ.get('AIC_V74_DISPOSABLE_PG') != '1',
                   reason='requires explicit disposable PostgreSQL v7.4 validation')
def test_material_upgrade_parallel_maintenance_and_restore():
    password = os.environ.get('AIC_V70_SYNTHETIC_PASSWORD')
    assert password, 'only the disposable container password may be supplied'
    container, username = 'aic-v70-validation-pg', 'aic_v70_synthetic'
    inspected = subprocess.run(['docker', 'inspect', '--format', '{{json .HostConfig.PortBindings}}', container],
                               capture_output=True, check=True, timeout=20)
    assert json.loads(inspected.stdout).get('5432/tcp') == [{'HostIp': '127.0.0.1', 'HostPort': '15470'}]
    names = [f'aic_v74_{kind}_{uuid4().hex[:10]}' for kind in ('upgrade', 'restore', 'fresh')]
    url = URL.create('postgresql+psycopg2', username=username, password=password,
                     host='127.0.0.1', port=15470, database='postgres')
    admin = create_engine(url)
    with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        for name in names:
            assert connection.scalar(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': name}) is None
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    print('Synthetic v7.4 databases retained:', ', '.join(names))
    engine, restored, fresh = [create_engine(url.set(database=name)) for name in names]

    from alembic import command
    from alembic.config import Config
    from app.database import bind_principal_scope
    from app.models.analysis_topic import AnalysisTopic, TopicChangeDismissal, TopicSnapshot
    from app.models.case import Case
    from app.models.map_foundation import UserAreaScope
    from app.models.result_catalog import ResultCatalogProjection, ResultCatalogReference
    from app.services import analysis_topic_service as topics
    from app.services.result_catalog import catalog, read_result
    from app.services.result_catalog_projection import reconcile_catalog
    from app.services.topic_notifications import daily_changes, dismiss_changes
    from init_fresh_db import initialize_empty_database
    from tests.test_result_materials_v65 import saved_case
    from tests.test_topic_notifications_v74 import ref, snapshot

    def migrate(target, *, target_engine=engine, direction='upgrade'):
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
        with target_engine.begin() as connection:
            config.attributes['connection'] = connection
            getattr(command, direction)(config, target)

    def session(target=engine):
        db = Session(target)
        bind_principal_scope(db, SimpleNamespace(user_id=1, role='analyst'), method='GET')
        return db

    try:
        migrate('v72m01')
        with engine.begin() as db:
            db.execute(text("INSERT INTO cases(case_number,description,operational_area_id) "
                            "VALUES ('SYN-V74-BEFORE','升级前合成原始记录',1)"))
            db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role,is_active) "
                            "VALUES (1,'v74-pg-synthetic','合成分析员','not-a-real-login','analyst',true)"))
            db.execute(text("INSERT INTO user_area_scopes(user_id,operational_area_id,access_level) VALUES (1,1,'write')"))
        migrate('v74c01')
        with session() as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v74c01'
            assert db.query(Case).one().description == '升级前合成原始记录'
            case, result = saved_case(db, 'V74-并发材料')
            case_id, material_id = case.id, result['id']
            topic_id = topics.create_topic(db, '同对象变化', {}, question_kind='case_gaps',
                                           source_context={'kind': 'case', 'id': case_id})['id']
            assert topics.refresh_topic(db, topic_id)['status'] == 'updated'
            topic = db.get(AnalysisTopic, topic_id)
            assert topic.notification_policy == 'meaningful'
            first = db.query(TopicSnapshot).filter_by(topic_id=topic_id).one()
            second = snapshot(db, topic, first.payload, 2)
            exact = ref(topic, second)
            original_hash = read_result(db, 'case', material_id)['content_sha256']
            assert daily_changes(db)[0]['sources'][0]['snapshot_id'] == second.id

        barrier = Barrier(3)
        def dismiss(_):
            with session() as db:
                barrier.wait(timeout=20)
                return dismiss_changes(db, [exact])
        with ThreadPoolExecutor(max_workers=3) as pool:
            receipts = list(pool.map(dismiss, range(3)))
        assert receipts == [{'sources': [exact], 'dismissed': 1}] * 3

        barrier = Barrier(2)
        def maintain(_):
            with Session(engine) as db:
                barrier.wait(timeout=20)
                return reconcile_catalog(db, limit=25)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(maintain, range(2)))
        with session() as db:
            assert db.query(TopicChangeDismissal).count() == 1
            assert daily_changes(db) == []
            assert db.query(ResultCatalogProjection).count() == 3  # Case plus two topic versions.
            assert db.query(ResultCatalogReference).count() > 0
            assert catalog(db, kind='case')['items'][0]['content_sha256'] == original_hash
            topics.update_topic(db, topic_id, notification_policy='muted')
            assert not db.get(AnalysisTopic, topic_id).paused
            expected = {model.__tablename__: db.query(model).count() for model in
                        (Case, AnalysisTopic, TopicSnapshot, TopicChangeDismissal,
                         ResultCatalogProjection, ResultCatalogReference)}
        backup = subprocess.run(['docker', 'exec', container, 'pg_dump', '-U', username, '-d', names[0],
                                 '--no-owner', '--no-privileges'], capture_output=True, check=True, timeout=60)
        subprocess.run(['docker', 'exec', '-i', container, 'psql', '-U', username, '-d', names[1], '-v', 'ON_ERROR_STOP=1'],
                       input=backup.stdout, capture_output=True, check=True, timeout=60)
        with session(restored) as db:
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == 'v74c01'
            for model in (Case, AnalysisTopic, TopicSnapshot, TopicChangeDismissal,
                          ResultCatalogProjection, ResultCatalogReference):
                assert db.query(model).count() == expected[model.__tablename__]
            assert read_result(db, 'case', material_id)['content_sha256'] == original_hash
            assert db.get(AnalysisTopic, topic_id).notification_policy == 'muted'
            assert dismiss_changes(db, [exact])['dismissed'] == 1
            assert db.query(TopicChangeDismissal).count() == 1
            assert db.query(Case).filter_by(case_number='SYN-V74-BEFORE').one().description == '升级前合成原始记录'
            db.query(UserAreaScope).filter_by(user_id=1).delete()
            db.commit()
            with pytest.raises(PermissionError):
                read_result(db, 'case', material_id)
            assert daily_changes(db) == []
        # Empty new install and safe empty downgrade/upgrade use a separate target.
        assert initialize_empty_database(url.set(database=names[2]).render_as_string(hide_password=False),
                                         confirmed=True) == 'v75r01'
        migrate('v72m01', target_engine=fresh, direction='downgrade')
        migrate('v74c01', target_engine=fresh)
        with fresh.connect() as db:
            assert 'topic_change_dismissals' in inspect(db).get_table_names()
            assert db.scalar(text('SELECT COUNT(*) FROM result_catalog_projections')) == 0
    finally:
        engine.dispose()
        restored.dispose()
        fresh.dispose()
