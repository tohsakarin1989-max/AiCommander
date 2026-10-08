"""Disposable SQLite upgrade/rollback; never touches the configured database."""
from sqlalchemy import create_engine, inspect, text

from tests.test_result_material_migration_v65 import migrate


def test_v71_private_draft_migration_preserves_original_and_refuses_data_loss(tmp_path):
    url = f"sqlite:///{tmp_path / 'synthetic-v71.sqlite'}"
    original = migrate(url, "upgrade", "v70s01")
    assert original.returncode == 0, original.stderr
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) "
                        "VALUES(7101,'V71-ORIGINAL','迁移前合成原始事实',1)"))
        db.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) "
                        "VALUES(7101,'v71-synthetic','合成用户','not-a-login','admin')"))
    for direction, revision in [("upgrade", "v71d01"), ("downgrade", "v70s01"), ("upgrade", "v71d01")]:
        result = migrate(url, direction, revision)
        assert result.returncode == 0, result.stderr
    # The migration process owns its connection; discard the old SQLite schema
    # cache from before the external DDL before reflecting its new indexes.
    engine.dispose()
    with engine.begin() as db:
        schema = inspect(db)
        assert {row["name"] for row in schema.get_indexes("case_drafts")} == {
            "ix_case_drafts_expires_at", "ix_case_drafts_owner_expiry"}
        assert schema.get_unique_constraints("case_preprocess_supplements")[0]["column_names"] == [
            "case_profile_id", "model_fingerprint"]
        assert db.scalar(text("SELECT description FROM cases WHERE id=7101")) == "迁移前合成原始事实"
        db.execute(text("INSERT INTO case_drafts(id,owner_id,operational_area_id,mode,revision,schema_version,status,"
                        "form_snapshot,last_save_sha256,submission_key,created_at,updated_at,expires_at) "
                        "VALUES('00000000-0000-0000-0000-000000007101',7101,1,'create',1,1,'active',"
                        "'{\"description\":\"合成私有草稿\"}',:digest,'draft-synthetic',"
                        "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'2099-01-01')"), {"digest": "a" * 64})
    refused = migrate(url, "downgrade", "v70s01")
    assert refused.returncode != 0 and "case_drafts_require_backup_before_downgrade" in refused.stderr
    with engine.connect() as db:
        assert db.scalar(text("SELECT revision FROM case_drafts")) == 1
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v71d01"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
