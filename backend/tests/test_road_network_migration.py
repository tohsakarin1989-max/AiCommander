from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest


@pytest.mark.parametrize('head, error_code', [
    ('5fa2c86b91f6', 'restore_compatible_backup_required_for_road_network_downgrade'),
    ('60b3d97ca207', 'restore_compatible_backup_required_for_road_alias_downgrade'),
    ('71c4e08db318', 'restore_compatible_backup_required_for_case_road_artifact_downgrade'),
    ('82d5f19ec429', 'restore_compatible_backup_required_for_vehicle_conditions_downgrade'),
    ('93e6a20fd53b', 'restore_compatible_backup_required_for_query_scope_downgrade'),
])
def test_upgrade_preserves_cases_and_requires_compatible_restore(tmp_path, head, error_code):
    database = tmp_path / 'roads.sqlite'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}', 'ENABLE_VECTOR_DB': 'false'}
    backend = Path(__file__).resolve().parents[1]

    def migrate(direction, target):
        return subprocess.run([sys.executable, '-m', 'alembic', direction, target],
            cwd=backend, env=env, capture_output=True, text=True, timeout=60)

    initial = migrate('upgrade', '4ef1b75a80e5')
    assert initial.returncode == 0, initial.stderr
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,occurred_time,description) VALUES ('SYNTHETIC-ROAD-MIGRATION','2026-09-11','原文不可改变')")
        db.execute("INSERT INTO case_vehicles(case_id,vehicle_type,oil_volume) VALUES (1,'重型挂车',10)")
    upgrade = migrate('upgrade', head)
    assert upgrade.returncode == 0, upgrade.stderr
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT description FROM cases').fetchone()[0] == '原文不可改变'
        if head == '93e6a20fd53b':
            assert db.execute('SELECT revision FROM query_scope_revision WHERE id=1').fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'aic_query_scope_%'").fetchone()[0] == 6
        if head == '82d5f19ec429':
            assert db.execute('SELECT vehicle_type,oil_volume,road_vehicle_kind,height_m,gross_weight_t FROM case_vehicles').fetchone() == ('重型挂车',10,None,None,None)
        for table in ('road_access_groups', 'road_access_memberships', 'road_access_grants', 'road_network_versions'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        if head in ('60b3d97ca207', '71c4e08db318'):
            assert db.execute('SELECT count(*) FROM road_public_aliases').fetchone()[0] == 0
        if head == '71c4e08db318':
            assert db.execute('SELECT count(*) FROM case_road_artifacts').fetchone()[0] == 0
        before = list(db.iterdump())
    rejected = migrate('downgrade', '4ef1b75a80e5')
    assert rejected.returncode != 0
    assert error_code in rejected.stderr
    with closing(sqlite3.connect(database)) as db:
        assert list(db.iterdump()) == before
