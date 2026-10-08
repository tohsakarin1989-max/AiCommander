"""Optional real PostgreSQL check; URL must name the disposable validation DB."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


URL = os.environ.get("AIC_V80_POSTGRES_MIGRATION_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires isolated PostgreSQL migration container")


def test_feedback_postgres_upgrade_preserves_facts_and_blocks_lossy_downgrade():
    assert make_url(URL).database == "aicommander_v80_isolated_migration"
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": URL, "ENABLE_VECTOR_DB": "false", "ENABLE_AGENT_LAB": "false", "AGENT_MODE": "off"}
    engine = create_engine(URL)
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0

    def migrate(command, revision, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", command, revision], cwd=backend,
                                env=env, capture_output=True, text=True, timeout=90)
        assert (result.returncode == 0) == success, result.stderr
        return result

    migrate("upgrade", "v75r01")
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,description,police_reported,case_filed) VALUES "
                        "('LEGACY-PG','合成迁移记录',false,true),('UNKNOWN-PG','合成未知记录',null,null)"))
        before = db.execute(text("SELECT case_number,description,police_reported,case_filed FROM cases ORDER BY case_number")).all()
    migrate("upgrade", "v80f01")
    migrate("upgrade", "v80f01")
    with engine.connect() as db:
        assert db.execute(text("SELECT case_number,description,police_reported,case_filed FROM cases ORDER BY case_number")).all() == before
        assert db.scalar(text("SELECT count(*) FROM cases WHERE feedback_known_fields IS NOT NULL")) == 0
        assert db.scalar(text("SELECT count(*) FROM case_revisions")) == 0
    migrate("downgrade", "v75r01")
    migrate("upgrade", "v80f01")
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(case_number,police_reported,feedback_known_fields) "
                        "VALUES ('EXPLICIT-PG',false,CAST('[\"police_reported\"]' AS JSON))"))
    result = migrate("downgrade", "v75r01", success=False)
    assert "feedback_provenance_requires_compatible_backup" in result.stderr
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM cases")) == 3
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v80f01"
        assert db.scalar(text("SELECT feedback_known_fields FROM cases WHERE case_number='EXPLICIT-PG'")) == ["police_reported"]
    engine.dispose()
