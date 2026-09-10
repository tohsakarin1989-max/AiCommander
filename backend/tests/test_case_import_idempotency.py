"""A lost HTTP response must not create the same import twice."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from starlette.datastructures import UploadFile

from app.api.cases import import_cases
from app.models.case import Case
from app.models.case_import import CaseImportBatch
from app.models.map_foundation import OperationalArea
from app.services.case_service import CaseService
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def upload():
    return UploadFile(filename="retry.csv", file=io.BytesIO(
        b"occurred_time,description\n2026-09-10,import-idempotency\n"
    ))


def test_same_upload_replays_receipt_without_second_case(db_session):
    first = import_cases(file=upload(), db=db_session)
    second = import_cases(file=upload(), db=db_session)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["replayed"] is True
    assert second["original_created"] == 1
    assert first["batch_id"] == second["batch_id"]
    assert db_session.query(Case).count() == 1
    assert db_session.query(CaseImportBatch).count() == 1


def test_preview_never_persists_batch(db_session):
    assert import_cases(file=upload(), dry_run=True, db=db_session)["valid"] == 1
    assert db_session.query(CaseImportBatch).count() == 0


def test_alias_changes_do_not_change_existing_file_identity(db_session, monkeypatch):
    from app.services.case_import_table import ALIASES
    def file():
        return UploadFile(filename="same.csv", file=io.BytesIO(
            "occurred_time,description,地点补充\n2026-09-10,原文,甲地\n".encode()
        ))
    original = import_cases(file=file(), db=db_session)
    monkeypatch.setitem(ALIASES, "地点补充", "location")
    replay = import_cases(file=file(), db=db_session)
    assert replay["batch_id"] == original["batch_id"]
    assert replay["replayed"] is True
    assert db_session.query(Case).count() == 1
    assert db_session.query(Case).one().location is None  # no implicit factual rewrite


def test_receipts_obey_current_authorized_scope(db_session):
    db_session.add_all([OperationalArea(id=1, code="a", name="A"), OperationalArea(id=2, code="b", name="B")])
    db_session.commit()
    first = import_cases(file=upload(), operational_area_id=1, db=db_session)
    second = import_cases(file=upload(), operational_area_id=2, db=db_session)
    assert first["batch_id"] != second["batch_id"]
    db_session.info["authorized_area_ids"] = (2,)
    assert [x.id for x in db_session.query(CaseImportBatch).all()] == [second["batch_id"]]


def test_case_and_receipt_roll_back_together_on_commit_failure(db_session, monkeypatch):
    original_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("injected commit failure")))
    with pytest.raises(RuntimeError):
        import_cases(file=upload(), db=db_session)
    db_session.rollback()
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert db_session.query(Case).count() == 0
    assert db_session.query(CaseImportBatch).count() == 0
    assert import_cases(file=upload(), db=db_session)["created"] == 1


def test_one_bad_row_does_not_roll_back_successful_rows(db_session, monkeypatch):
    original = CaseService.create_case
    def fail_one(*args, **kwargs):
        case = original(*args, **kwargs)
        if kwargs["description"] == "bad":
            raise ValueError("injected row failure after flush")
        return case
    monkeypatch.setattr(CaseService, "create_case", fail_one)
    def file():
        return UploadFile(filename="partial.csv", file=io.BytesIO(
            b"occurred_time,description\n2026-09-10,good\n2026-09-10,bad\n2026-09-10,last\n"
        ))
    result = import_cases(file=file(), db=db_session)
    assert result["created"] == 2
    assert [x.description for x in db_session.query(Case).order_by(Case.id)] == ["good", "last"]
    assert len(result["errors"]) == 1
    assert import_cases(file=file(), db=db_session)["created"] == 0


def test_concurrent_identical_uploads_commit_once_across_sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    barrier = Barrier(4)
    monkeypatch.setattr(CaseService, "finish_created_case", lambda *args: None)
    def run():
        with sessions() as db:
            barrier.wait(timeout=10)
            return import_cases(file=upload(), db=db)
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: run(), range(4)))
        assert sum(result["created"] for result in results) == 1
        assert sum(result["replayed"] for result in results) == 3
        with sessions() as db:
            assert db.query(Case).count() == 1
            assert db.query(CaseImportBatch).count() == 1
    finally:
        engine.dispose()
