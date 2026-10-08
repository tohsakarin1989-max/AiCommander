"""Only disposable synthetic SQLite databases; no configured business database."""
from sqlalchemy import create_engine, inspect, text

from tests.test_result_material_migration_v65 import migrate


def test_v70_upgrade_empty_downgrade_and_nonempty_receipt_protection(tmp_path):
    url = f"sqlite:///{tmp_path / 'synthetic-submissions.sqlite'}"
    original = migrate(url, "upgrade", "v65r01")
    assert original.returncode == 0, original.stderr
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description) VALUES (701,'V70-SYNTHETIC','原始合成事实')"))
        db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) "
                        "VALUES(701,'v70-synthetic','合成用户','not-a-login','admin')"))
    for direction, revision in [("upgrade", "v70s01"), ("downgrade", "v65r01"), ("upgrade", "v70s01")]:
        result = migrate(url, direction, revision)
        assert result.returncode == 0, result.stderr
    with engine.begin() as db:
        assert db.scalar(text("SELECT description FROM cases WHERE id=701")) == "原始合成事实"
        indexes = inspect(db).get_indexes("case_submission_receipts")
        assert any(row["column_names"] == ["case_id"] for row in indexes)
        db.execute(text("INSERT INTO case_submission_receipts(user_id,idempotency_key,request_sha256,case_id) "
                        "VALUES(701,'synthetic-attempt',:digest,701)"), {"digest": "a" * 64})
    refused = migrate(url, "downgrade", "v65r01")
    assert refused.returncode != 0 and "case_submission_receipts_require_backup_before_downgrade" in refused.stderr
    with engine.connect() as db:
        assert db.scalar(text("SELECT case_id FROM case_submission_receipts")) == 701
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v70s01"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
