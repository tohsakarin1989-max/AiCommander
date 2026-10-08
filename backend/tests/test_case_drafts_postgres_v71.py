"""Opt-in real v7.1 migration, CAS, concurrent promotion and backup restore.

Only the already verified synthetic loopback container is accepted. Every run
creates new named databases; none is dropped, reset or silently reused.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.environ.get("AIC_V71_DISPOSABLE_PG") != "1",
                    reason="requires explicit synthetic PostgreSQL v7.1 validation")
def test_upgrade_concurrent_drafts_edit_conflict_atomic_failure_and_restore(monkeypatch):
    password = os.environ.get("AIC_V70_SYNTHETIC_PASSWORD")
    assert password, "provide only the disposable database password"
    container = "aic-v70-validation-pg"
    inspected = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}",
                                container], capture_output=True, check=True, timeout=20)
    assert json.loads(inspected.stdout).get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "15470"}]
    username = "aic_v70_synthetic"
    suffix = uuid4().hex[:10]
    names = [f"aic_v71_{kind}_{suffix}" for kind in ("upgrade", "restore")]
    url = URL.create("postgresql+psycopg2", username=username, password=password,
                     host="127.0.0.1", port=15470, database="postgres")
    admin = create_engine(url)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for name in names:
            assert connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}) is None
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    print("Synthetic v7.1 databases retained:", ", ".join(names))
    engine = create_engine(url.set(database=names[0]))
    restored_engine = create_engine(url.set(database=names[1]))

    from alembic import command
    from alembic.config import Config
    from app.models.case import Case
    from app.models.case_draft import CaseDraft
    from app.models.case_source import CaseRevision, EvidenceObject
    from app.models.case_submission import CaseSubmissionReceipt
    from app.services.case_draft_service import DraftConflict, DraftUnavailable, get_draft, save_draft, submit_draft
    from app.services.case_edit_service import CaseEditConflict, edit_snapshot, update_case_checked
    from app.services.case_submission_service import create_case_submission

    def migrate(target):
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, target)

    def session():
        db = Session(engine)
        db.info.update(principal_user_id=71, authorized_area_ids=(1,), area_access_levels={1: "write"})
        return db

    try:
        migrate("v70s01")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO cases(case_number,description,operational_area_id) "
                "VALUES ('SYN-V71-BEFORE','升级前合成原始记录',1)"))
            connection.execute(text("INSERT INTO users(id,username,display_name,password_hash,role) "
                "VALUES (71,'v71-pg-synthetic','合成账号','not-a-real-login','analyst')"))
        migrate("v71d01")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "v71d01"
            assert connection.scalar(text("SELECT description FROM cases WHERE case_number='SYN-V71-BEFORE'")) == "升级前合成原始记录"

        draft_id = str(uuid4())
        barrier = Barrier(4)
        def save(_):
            with session() as db:
                barrier.wait(timeout=20)
                row = save_draft(db, draft_id, expected_revision=0, operational_area_id=1,
                                 form_snapshot={"description": "合成草稿，尚未完整"})
                return row.id, row.revision
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert set(pool.map(save, range(4))) == {(draft_id, 1)}
        with session() as db:
            assert db.query(Case).count() == 1
            assert db.query(CaseRevision).count() == db.query(CaseSubmissionReceipt).count() == 0
            with pytest.raises(DraftConflict):
                submit_draft(db, draft_id, expected_revision=1,
                    request_payload={"description": "只确认，不应提交"},
                    values={"description": "只确认，不应提交"}, confirm_only=True)
            assert get_draft(db, draft_id).status == "active"
            assert db.query(Case).count() == 1
            assert db.query(CaseRevision).count() == db.query(CaseSubmissionReceipt).count() == 0

        barrier = Barrier(4)
        payload = {"description": "合成正式原文", "operational_area_id": 1}
        def promote(_):
            with session() as db:
                barrier.wait(timeout=20)
                row = submit_draft(db, draft_id, expected_revision=1, request_payload=payload, values=payload)
                return row.submitted_case_id
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(promote, range(4)))
        assert len(set(ids)) == 1
        case_id = ids[0]
        with session() as db:
            assert db.query(Case).count() == 2
            assert db.query(CaseSubmissionReceipt).count() == db.query(CaseRevision).count() == 1
            assert submit_draft(db, draft_id, expected_revision=1, request_payload=payload,
                values=payload, confirm_only=True).submitted_case_id == case_id
            different = {**payload, "description": "另一个页面的不同输入"}
            with pytest.raises(DraftConflict):
                submit_draft(db, draft_id, expected_revision=1, request_payload=different,
                    values=different, confirm_only=True)
            assert db.query(Case).count() == 2
            revision = edit_snapshot(db, case_id)["source_revision"]

        barrier = Barrier(2)
        def edit(index):
            with session() as db:
                barrier.wait(timeout=20)
                try:
                    row = update_case_checked(db, case_id, {"description": f"合成并发编辑{index}"}, expected_revision=revision)
                    return "saved", row.description
                except CaseEditConflict:
                    return "conflict", None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, range(2)))
        assert sorted(item[0] for item in outcomes) == ["conflict", "saved"]
        with session() as db:
            assert db.query(CaseRevision).count() == 2
            assert db.get(Case, case_id).description == next(value for state, value in outcomes if state == "saved")

        # Formal facts, source event, receipt and consumed state roll back together.
        failed_id = str(uuid4())
        with session() as db:
            save_draft(db, failed_id, expected_revision=0, operational_area_id=1,
                       form_snapshot={"description": "事务失败仍保留草稿"})
            original_commit = db.commit
            monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("synthetic commit failure")))
            with pytest.raises(SQLAlchemyError, match="synthetic commit failure"):
                submit_draft(db, failed_id, expected_revision=1, request_payload=payload, values=payload)
            monkeypatch.setattr(db, "commit", original_commit)
            assert db.query(Case).count() == 2 and db.query(CaseSubmissionReceipt).count() == 1
            assert get_draft(db, failed_id).form_snapshot == {"description": "事务失败仍保留草稿"}
            db.info.update(authorized_area_ids=(), area_access_levels={})
            with pytest.raises(DraftUnavailable):
                get_draft(db, failed_id)
        with session() as db:
            db.add(EvidenceObject(storage_key="v71-synthetic-original", sha256="b" * 64,
                media_type="text/plain", sensitivity="internal", availability="available", content=b"v71 synthetic original"))
            db.commit()

        backup = subprocess.run(["docker", "exec", container, "pg_dump", "-U", username,
            "-d", names[0], "--no-owner", "--no-privileges"], capture_output=True, check=True, timeout=60)
        subprocess.run(["docker", "exec", "-i", container, "psql", "-U", username,
            "-d", names[1], "-v", "ON_ERROR_STOP=1"], input=backup.stdout,
            capture_output=True, check=True, timeout=60)
        with Session(restored_engine) as db:
            db.info.update(principal_user_id=71, authorized_area_ids=(1,), area_access_levels={1: "write"})
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "v71d01"
            assert db.query(Case).count() == 2 and db.query(CaseDraft).count() == 2
            assert db.query(CaseSubmissionReceipt).count() == 1 and db.query(CaseRevision).count() == 2
            assert get_draft(db, draft_id).submitted_case_id == case_id
            assert get_draft(db, failed_id).form_snapshot == {"description": "事务失败仍保留草稿"}
            assert bytes(db.scalar(text("SELECT content FROM evidence_objects WHERE storage_key='v71-synthetic-original'"))) == b"v71 synthetic original"
            # A retry after restore still cannot create a second formal case.
            assert submit_draft(db, draft_id, expected_revision=1, request_payload=payload, values=payload).submitted_case_id == case_id
            assert db.query(Case).count() == 2

        # A former writer's stale area grant does not override their current role.
        with session() as db:
            db.execute(text("UPDATE users SET role='viewer' WHERE id=71"))
            db.commit()
            with pytest.raises(DraftUnavailable):
                get_draft(db, failed_id)
            db.execute(text("UPDATE users SET role='analyst' WHERE id=71"))
            db.commit()
            assert get_draft(db, failed_id).status == "active"

        # One key must not bind a draft to a formal case in another default area,
        # even when this user legitimately has both areas' write grants.
        from app.models.map_foundation import OperationalArea
        cross_id = str(uuid4())
        cross_payload = {"description": "合成两厂区绑定检查"}
        with session() as db:
            db.add(OperationalArea(id=2, code="v71-other", name="另一个合成范围"))
            db.commit()
            db.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write", 2: "write"})
            cross_draft = save_draft(db, cross_id, expected_revision=0, operational_area_id=1, form_snapshot={})
            other_case = create_case_submission(db, key=cross_draft.submission_key, request_payload=cross_payload,
                values={"case_number": None, "operational_area_id": 2, **cross_payload})
            other_id = other_case.id
            with pytest.raises(DraftConflict):
                submit_draft(db, cross_id, expected_revision=1, request_payload=cross_payload, values=cross_payload)
            assert get_draft(db, cross_id).status == "active"
            assert db.get(Case, other_id).operational_area_id == 2
    finally:
        engine.dispose()
        restored_engine.dispose()
