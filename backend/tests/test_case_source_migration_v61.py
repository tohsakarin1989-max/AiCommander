"""An isolated upgrade must not invent units or silently rewrite legacy facts."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_v61_incremental_schema_preserves_raw_data_and_allows_unknown_time(tmp_path):
    database = tmp_path / "synthetic-v61.sqlite"
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "ENABLE_VECTOR_DB": "false",
           "ENABLE_AGENT_LAB": "false", "AGENT_MODE": "off"}
    def migrate(revision):
        process = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=backend,
                                 env=env, capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stderr
    migrate("v60c01")
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("INSERT INTO cases(id,case_number,occurred_time,description,oil_volume,vehicle_info) "
                   "VALUES (1,'V61-LEGACY','2026-09-27','原始记录',120,'{\"原始\":true}')")
        before = db.execute("SELECT occurred_time,description,oil_volume,vehicle_info FROM cases").fetchone()
    migrate("v61s01")
    with closing(sqlite3.connect(database)) as db, db:
        assert db.execute("SELECT occurred_time,description,oil_volume,vehicle_info FROM cases").fetchone() == before
        assert db.execute("SELECT oil_volume_unit,time_precision FROM cases").fetchone() == ("unknown", None)
        assert db.execute("SELECT count(*) FROM case_revisions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM domain_changes").fetchone()[0] == 0
        db.execute("INSERT INTO cases(case_number,occurred_time,time_expression) VALUES('V61-UNKNOWN',NULL,'昨晚')")
        db.execute("PRAGMA foreign_keys=ON")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        columns = {row[1] for row in db.execute("PRAGMA table_info(evidence_objects)")}
        assert {"storage_key", "sha256", "availability", "content"} <= columns
    migrate("v61s01")
