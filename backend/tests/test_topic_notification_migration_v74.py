"""Disposable SQLite upgrade/defaults/restore; never touches the configured DB."""
from contextlib import closing
import sqlite3

import pytest

from tests.test_result_material_migration_v65 import migrate


def test_v74_notifications_preserve_old_topics_and_protect_new_preferences(tmp_path):
    path, backup = tmp_path / 'v74-notifications.sqlite', tmp_path / 'v72-backup.sqlite'
    url = f'sqlite:///{path}'
    result = migrate(url, 'upgrade', 'v72m01')
    assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO users(id,username,display_name,password_hash,role) VALUES (1,'notification-test','合成测试','not-a-login','admin')")
        db.execute("INSERT INTO analysis_topics(id,created_by,title,notes,filters,scope_version,paused,refresh_state) "
                   "VALUES ('synthetic-topic',1,'升级前专题','保留备注','{}','scope',1,'ready')")
        db.execute("INSERT INTO topic_snapshots(id,topic_id,revision,content_sha256,payload,changes) "
                   "VALUES ('synthetic-snapshot','synthetic-topic',1,?,'{}','{}')", ('a' * 64,))
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as dest:
        source.backup(dest)
    for direction, target in [('upgrade', 'v74n01'), ('downgrade', 'v72m01'), ('upgrade', 'v74n01')]:
        result = migrate(url, direction, target)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT title,notes,paused,refresh_state,notification_policy FROM analysis_topics').fetchone() == (
            '升级前专题', '保留备注', 1, 'ready', 'meaningful')
        assert db.execute('SELECT COUNT(*) FROM topic_snapshots').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE analysis_topics SET notification_policy='external_push'")
        db.execute("UPDATE analysis_topics SET notification_policy='muted'")
        db.execute("INSERT INTO topic_change_dismissals(created_by,snapshot_id,content_sha256) VALUES (1,'synthetic-snapshot',?)", ('a' * 64,))
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    refused = migrate(url, 'downgrade', 'v72m01')
    assert refused.returncode != 0 and 'v74_notification_preferences_require_compatible_backup' in refused.stderr
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM topic_change_dismissals').fetchone()[0] == 1
    restored = tmp_path / 'separate-restored.sqlite'
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored)) as dest:
        source.backup(dest)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'v72m01'
        assert db.execute('SELECT COUNT(*) FROM topic_snapshots').fetchone()[0] == 1
