"""Upgrade/downgrade on disposable SQLite only; no raw feedback rewrites."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_feedback_migration_preserves_legacy_values_and_guards_downgrade(tmp_path):
    database = tmp_path / "synthetic-feedback.sqlite"
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "ENABLE_VECTOR_DB": "false",
           "ENABLE_AGENT_LAB": "false", "AGENT_MODE": "off"}

    def migrate(command, revision, *, ok=True):
        result = subprocess.run([sys.executable, "-m", "alembic", command, revision],
                                cwd=backend, env=env, capture_output=True, text=True, timeout=60)
        assert (result.returncode == 0) == ok, result.stderr
        return result

    migrate("upgrade", "v75r01")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,description,police_reported,case_filed) "
                   "VALUES ('LEGACY-FEEDBACK','原始事实',0,1)")
        before = db.execute("SELECT case_number,description,police_reported,case_filed FROM cases").fetchall()
    migrate("upgrade", "v80f01")
    migrate("upgrade", "v80f01")
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute("SELECT case_number,description,police_reported,case_filed FROM cases").fetchall() == before
        assert db.execute("SELECT feedback_known_fields FROM cases").fetchone() == (None,)
        assert db.execute("SELECT count(*) FROM case_revisions").fetchone() == (0,)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    migrate("downgrade", "v75r01")
    migrate("upgrade", "v80f01")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(case_number,feedback_known_fields) VALUES ('NEW-FEEDBACK','[]')")
    rejected = migrate("downgrade", "v75r01", ok=False)
    assert "feedback_provenance_requires_compatible_backup" in rejected.stderr
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT count(*) FROM cases").fetchone() == (2,)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("v80f01",)
