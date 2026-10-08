"""Opt-in targeted receipt check on one new, disposable PostgreSQL database.

Create aic_v70_receipt_opt once in the existing synthetic-only container before
running. This test refuses a nonempty database and never drops or clears data.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session


@pytest.mark.skipif(os.environ.get("AIC_V70_SUBMISSION_PG") != "1",
                    reason="requires explicit disposable PostgreSQL receipt validation")
def test_postgres_targeted_conflict_arbitration_keeps_atomicity_and_current_access(monkeypatch):
    password = os.environ.get("AIC_V70_SYNTHETIC_PASSWORD")
    assert password, "pass only the disposable container's synthetic password"
    result = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}",
                             "aic-v70-validation-pg"], capture_output=True, check=True, timeout=20)
    assert json.loads(result.stdout).get("5432/tcp") == [{"HostIp": "127.0.0.1", "HostPort": "15470"}]
    url = URL.create("postgresql+psycopg2", username="aic_v70_synthetic", password=password,
                     host="127.0.0.1", port=15470, database="aic_v70_receipt_opt")
    engine = create_engine(url)

    from alembic import command
    from alembic.config import Config
    from app.database import AreaWriteAccessError
    from app.models.case import Case
    from app.models.case_source import CaseRevision
    from app.models.case_submission import CaseSubmissionReceipt
    from app.models.map_foundation import OperationalArea
    from app.models.user import User
    from app.services.case_submission_service import (
        SubmissionConflictError, SubmissionUnavailableError, create_case_submission, submission_status,
    )

    def session():
        db = Session(engine)
        db.info.update(principal_user_id=71, authorized_area_ids=(1,), area_access_levels={1: "write"})
        return db

    def save(db, key="same-key", description="合成并发原始记录"):
        return create_case_submission(db, key=key, request_payload={"description": description},
            values={"case_number": None, "description": description, "operational_area_id": 1})

    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('public.cases')")) is None, "never reuse prior data"
        # Use the real migrations, including the required vector extension;
        # direct ORM create_all is not a PostgreSQL installation procedure.
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with session() as db:
            if db.get(OperationalArea, 1) is None:
                db.add(OperationalArea(id=1, code="synthetic", name="合成测试区"))
            db.add(User(id=71, username="receipt-opt", display_name="合成账号", password_hash="not-a-login", role="analyst"))
            db.commit()

        barrier = Barrier(4)

        def parallel(_):
            with session() as db:
                barrier.wait(timeout=15)
                return save(db).id

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(parallel, range(4)))
        assert len(set(ids)) == 1
        with session() as db:
            assert db.query(Case).count() == db.query(CaseSubmissionReceipt).count() == db.query(CaseRevision).count() == 1
            with pytest.raises(SubmissionConflictError):
                save(db, description="同一标识的不同内容")
            db.info["area_access_levels"] = {1: "read"}
            with pytest.raises(AreaWriteAccessError):
                save(db)
            db.info.update(authorized_area_ids=(), area_access_levels={})
            assert submission_status(db, "same-key") == {"status": "unconfirmed", "case_id": None}
            with pytest.raises(SubmissionUnavailableError):
                save(db)

        with session() as db:
            original_commit = db.commit
            monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("synthetic commit failure")))
            with pytest.raises(SQLAlchemyError, match="synthetic commit failure"):
                save(db, key="failed-then-retry")
            monkeypatch.setattr(db, "commit", original_commit)
            assert db.query(Case).count() == db.query(CaseSubmissionReceipt).count() == 1
            assert submission_status(db, "failed-then-retry")["status"] == "unconfirmed"
            assert save(db, key="failed-then-retry").id != ids[0]

        with session() as db:
            db.info["principal_user_id"] = 9999
            with pytest.raises(IntegrityError):
                save(db, key="invalid-user")
            assert db.query(Case).count() == db.query(CaseSubmissionReceipt).count() == 2

        with session() as db:
            db.delete(db.get(Case, ids[0]))
            db.commit()
            receipt = db.query(CaseSubmissionReceipt).filter_by(idempotency_key="same-key").one()
            assert receipt.case_id is None
            with pytest.raises(SubmissionUnavailableError):
                save(db)
            assert db.query(Case).count() == 1 and db.query(CaseSubmissionReceipt).count() == 2
    finally:
        engine.dispose()
