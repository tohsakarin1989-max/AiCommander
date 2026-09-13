"""Historical release checks must track current heads without accepting old schema."""
import importlib.util
from pathlib import Path
import sqlite3

from alembic.script import ScriptDirectory
import pytest


SPEC = importlib.util.spec_from_file_location(
    "verify_sqlite_schema", Path(__file__).parents[1] / "verify-sqlite-schema.py"
)
SCHEMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEMA)


def _database(tmp_path, heads):
    path = tmp_path / "verification.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE workbench_task_sessions (id INTEGER)")
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.executemany("INSERT INTO alembic_version VALUES (?)", [(h,) for h in heads])
    return path


def test_schema_accepts_the_current_repository_heads(tmp_path):
    heads = ScriptDirectory(str(SCHEMA.MIGRATIONS)).get_heads()
    database = _database(tmp_path, heads)
    SCHEMA.verify_schema(database, {"workbench_task_sessions"})


@pytest.mark.parametrize("heads", [[], ["a7d9e1f2b304"], ["unknown-head"]])
def test_schema_rejects_missing_stale_or_unknown_migrations(tmp_path, heads):
    with pytest.raises(RuntimeError, match="Migration heads mismatch"):
        SCHEMA.verify_schema(_database(tmp_path, heads), {"workbench_task_sessions"})


def test_schema_rejects_missing_business_tables_even_at_current_head(tmp_path):
    heads = ScriptDirectory(str(SCHEMA.MIGRATIONS)).get_heads()
    with pytest.raises(RuntimeError, match="knowledge_assets"):
        SCHEMA.verify_schema(_database(tmp_path, heads), {"knowledge_assets"})


def test_schema_does_not_create_an_absent_database(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        SCHEMA.verify_schema(missing, {"workbench_task_sessions"})
    assert not missing.exists()
