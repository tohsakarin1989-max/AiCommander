import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.api.cases import import_cases
from app.database import AreaWriteAccessError, Base
from app.models.case import Case
from app.models.case_import import CaseImportRow
from app.services.case_import_retry_service import get_batch_rows, retry_batch_rows


def initial(db):
    return import_cases(file=UploadFile(filename="rows.csv", file=io.BytesIO(
        "案发时间,案情描述,经度,纬度\n2026-09-10 08:00,成功原文,124,47\n2026-09-10 09:00,失败原文,错误坐标,47\n".encode()
    )), db=db, time_zone="Asia/Shanghai")


def test_retry_only_failed_row_and_repeated_request_is_noop(db_session):
    batch = initial(db_session)
    request = [{"row": 3, "revision": 0, "changes": {"longitude": "125"}}]
    result = retry_batch_rows(db_session, batch["batch_id"], request)
    assert result["created"] == 1
    assert result["batch_created_total"] == 2
    assert retry_batch_rows(db_session, batch["batch_id"], request)["created"] == 0
    assert db_session.query(Case).count() == 2
    row = db_session.query(CaseImportRow).filter_by(row_number=3).one()
    assert row.source_values["longitude"] == "错误坐标"
    assert row.current_values["longitude"] == "125"
    assert row.revision == 1
    assert len(row.corrections) == 1
    assert db_session.query(Case).filter_by(id=row.case_id).one().occurred_time.hour == 1


def test_successful_source_row_cannot_be_rewritten_via_retry(db_session):
    batch = initial(db_session)
    with pytest.raises(HTTPException) as error:
        retry_batch_rows(db_session, batch["batch_id"], [{"row": 2, "revision": 0, "changes": {"description": "不能改"}}])
    assert error.value.status_code == 409
    assert not db_session.in_transaction(), "Rejected corrections must release the batch lock"
    assert db_session.query(Case).one().description == "成功原文"


def test_failed_correction_keeps_source_and_new_revision(db_session):
    batch = initial(db_session)
    result = retry_batch_rows(db_session, batch["batch_id"], [{"row": 3, "revision": 0, "changes": {"longitude": "仍然错误"}}])
    assert result["created"] == 0
    assert result["rows"][0]["status"] == "failed"
    assert result["rows"][0]["revision"] == 1
    with pytest.raises(HTTPException) as error:
        retry_batch_rows(db_session, batch["batch_id"], [{"row": 3, "revision": 0, "changes": {"longitude": "125"}}])
    assert error.value.status_code == 409


def test_retry_rejects_missing_rows_and_security_field_changes(db_session):
    batch = initial(db_session)
    for rows in ([{"row": 999, "revision": 0, "changes": {"longitude": "125"}}],
                 [{"row": 3, "revision": 0, "changes": {"operational_area_id": 9}}]):
        with pytest.raises(HTTPException):
            retry_batch_rows(db_session, batch["batch_id"], rows)
    assert db_session.query(Case).count() == 1


def test_retry_and_source_rows_are_scoped(db_session):
    batch = initial(db_session)
    db_session.info["authorized_area_ids"] = ()
    with pytest.raises(HTTPException) as error:
        get_batch_rows(db_session, batch["batch_id"])
    assert error.value.status_code == 404
    db_session.info["authorized_area_ids"] = None
    db_session.info["area_access_levels"] = {}
    with pytest.raises(AreaWriteAccessError):
        retry_batch_rows(db_session, batch["batch_id"], [{"row": 3, "revision": 0, "changes": {"longitude": "125"}}])


def test_retry_commit_failure_rolls_back_case_and_correction(db_session, monkeypatch):
    batch = initial(db_session)
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    with pytest.raises(RuntimeError):
        retry_batch_rows(db_session, batch["batch_id"], [{"row": 3, "revision": 0, "changes": {"longitude": "125"}}])
    assert db_session.query(Case).count() == 1
    row = db_session.query(CaseImportRow).filter_by(row_number=3).one()
    assert row.revision == 0
    assert row.current_values["longitude"] == "错误坐标"
    assert row.corrections == []


def test_concurrent_retry_creates_only_one_case(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}", connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            batch_id = initial(db)["batch_id"]
        barrier = Barrier(4)
        def run():
            with sessions() as db:
                barrier.wait(timeout=10)
                try:
                    return retry_batch_rows(db, batch_id, [{"row": 3, "revision": 0, "changes": {"longitude": "125"}}])["created"]
                except HTTPException as exc:
                    assert exc.status_code == 409
                    return 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(lambda _: run(), range(4))) == 1
        with sessions() as db:
            assert db.query(Case).count() == 2
            row = db.query(CaseImportRow).filter_by(row_number=3).one()
            assert row.revision == 1
            assert len(row.corrections) == 1
    finally:
        engine.dispose()
