"""Check an isolated verification database against the current repository schema."""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from alembic.script import ScriptDirectory


MIGRATIONS = Path(__file__).resolve().parents[1] / "backend" / "alembic"


def verify_schema(database: Path, required_tables: set[str]) -> None:
    expected_heads = set(ScriptDirectory(str(MIGRATIONS)).get_heads())
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = (required_tables | {"alembic_version"}) - tables
        if missing:
            raise RuntimeError(f"Missing required tables: {sorted(missing)}")
        actual_heads = {row[0] for row in connection.execute(
            "SELECT version_num FROM alembic_version"
        )}
    if actual_heads != expected_heads:
        raise RuntimeError(
            f"Migration heads mismatch: expected {sorted(expected_heads)}, "
            f"found {sorted(actual_heads)}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("tables", nargs="+")
    args = parser.parse_args()
    verify_schema(args.database, set(args.tables))
