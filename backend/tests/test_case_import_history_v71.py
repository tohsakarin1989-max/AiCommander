"""Recent import receipts are scoped, read-only and reflect corrected rows."""
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.case_imports import router
from app.database import Base, get_db
from app.models.case_import import CaseImportBatch, CaseImportRow
from app.models.map_foundation import OperationalArea
from app.services.case_import_retry_service import list_import_batches


def seed(db, batch_id, area_id, statuses=("created", "failed"), age=0):
    batch = CaseImportBatch(
        id=batch_id, input_hash=batch_id.ljust(64, "0"),
        operational_area_id=area_id,
        created_at=datetime.now(timezone.utc) - timedelta(days=age),
        result={"total": 2, "created": 1, "errors": [{"error": "不能外露的原文"}],
                "preview": [{"description": "原始案情不属于列表摘要"}],
                "table": {"worksheet": "记录", "time_zone": "Asia/Shanghai"}},
    )
    db.add(batch)
    db.flush()
    for i, status in enumerate(statuses, start=2):
        db.add(CaseImportRow(
            batch_id=batch_id, operational_area_id=area_id, row_number=i,
            source_values={"description": "原始案情"}, current_values={},
            status=status, corrections=[],
        ))
    db.commit()
    return batch


def areas(db):
    db.add_all([OperationalArea(id=1, name="范围一", code="area-1"),
                OperationalArea(id=2, name="范围二", code="area-2")])
    db.commit()


def test_filter_before_count_and_pagination_and_revoke(db_session):
    areas(db_session)
    seed(db_session, "hidden", 2)
    seed(db_session, "visible-new", 1, age=1)
    seed(db_session, "visible-old", 1, age=2)
    db_session.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"})
    first = list_import_batches(db_session, page=1, page_size=1)
    assert first["total"] == 2
    assert first["items"][0]["batch_id"] == "visible-new"
    assert first["items"][0]["retry_available"] is True
    second = list_import_batches(db_session, page=2, page_size=1)
    assert second["items"][0]["batch_id"] == "visible-old"
    assert "原始案情" not in str(first) and "不能外露" not in str(first)
    assert list_import_batches(db_session, operational_area_id=2)["total"] == 0
    db_session.info["authorized_area_ids"] = ()
    assert list_import_batches(db_session)["items"] == []
    assert list_import_batches(db_session)["total"] == 0


def test_current_rows_not_stale_receipt_and_get_never_writes(db_session):
    areas(db_session)
    seed(db_session, "corrected", 1, statuses=("created", "created"))
    db_session.info.update(authorized_area_ids=(1,), area_access_levels={1: "read"})
    statements = []
    def capture(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql.lstrip().split(None, 1)[0].upper())
    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        item = list_import_batches(db_session)["items"][0]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert item["success"] == 2 and item["failed"] == 0 and item["total"] == 2
    assert item["retry_available"] is False
    assert item["duplicate"] is None, "No per-row duplicate measurement must not be invented"
    assert not {"UPDATE", "INSERT", "DELETE"}.intersection(statements)
    assert not db_session.new and not db_session.dirty


def test_legacy_no_rows_exposes_receipt_without_inventing_retry(db_session):
    areas(db_session)
    seed(db_session, "legacy", 1, statuses=())
    item = list_import_batches(db_session)["items"][0]
    assert item["total"] == 2 and item["success"] == 1 and item["failed"] == 1
    assert item["state"] == "legacy_receipt"
    assert item["retry_available"] is False


def test_history_route_bounds_and_empty_success():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(router, prefix="/api/case-imports")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            response = client.get("/api/case-imports/batches")
            assert response.status_code == 200
            assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
            for params in ({"page": 0}, {"page_size": 101}, {"operational_area_id": -1}):
                assert client.get("/api/case-imports/batches", params=params).status_code == 422
            areas(db)
            item = seed(db, "utc-receipt", 1)
            item.created_at = datetime(2026, 10, 5, 9, 40, 8)
            db.commit()
            db.expire_all()
            timestamp = client.get("/api/case-imports/batches").json()["items"][0]["created_at"]
            # SQLite returns a naive timestamp: still declare UTC on the wire,
            # otherwise an Asia/Shanghai browser shows 09:40 instead of 17:40.
            assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")) == datetime(
                2026, 10, 5, 9, 40, 8, tzinfo=timezone.utc)
    finally:
        db.close()
        engine.dispose()
