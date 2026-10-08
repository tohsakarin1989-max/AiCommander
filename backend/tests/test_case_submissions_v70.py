"""An uncertain network result must never create a second case on retry."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.case import Case
from app.models.case_source import CaseRevision
from app.models.case_pipeline import OutboxEvent
from app.models.user import User
from tests.test_case_search_page import client_for, search_db  # noqa: F401


@pytest.fixture
def submission_db(search_db):
    search_db.add_all([
        User(id=71, username="submit-one", display_name="提交人一", password_hash="test", role="analyst"),
        User(id=72, username="submit-two", display_name="提交人二", password_hash="test", role="analyst"),
    ])
    search_db.commit()
    search_db.info.update(principal_user_id=71, authorized_area_ids=(1,),
                          area_access_levels={1: "write"}, default_operational_area_id=1)
    return search_db


def submit(client, key="v70-attempt", **changes):
    return client.post("/api/cases/", headers={"Idempotency-Key": key},
                       json={"description": "合成保存可靠性样本", "operational_area_id": 1, **changes})


def test_retry_reuses_case_revision_and_outbox(submission_db):
    client = client_for(submission_db)
    first = submit(client)
    original_events = {row.id for row in submission_db.scalars(select(OutboxEvent))}
    second = submit(client)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert submission_db.scalar(select(func.count()).select_from(Case)) == 1
    assert submission_db.scalar(select(func.count()).select_from(CaseRevision)) == 1
    assert original_events and {row.id for row in submission_db.scalars(select(OutboxEvent))} == original_events
    assert client.get("/api/cases/submissions/v70-attempt").json() == {
        "status": "completed", "case_id": first.json()["id"]}


def test_key_is_bound_to_payload_and_user(submission_db):
    client = client_for(submission_db)
    first = submit(client).json()
    changed = submit(client, description="不同的事实")
    assert changed.status_code == 409
    submission_db.info["principal_user_id"] = 72
    assert client.get("/api/cases/submissions/v70-attempt").json() == {
        "status": "unconfirmed", "case_id": None}
    second = submit(client)
    assert second.status_code == 200 and second.json()["id"] != first["id"]


def test_replay_uses_current_content_and_current_access(submission_db):
    client = client_for(submission_db)
    item_id = submit(client).json()["id"]
    item = submission_db.get(Case, item_id)
    item.description = "后来人工补充的事实"
    submission_db.commit()
    assert submit(client).json()["description"] == "后来人工补充的事实"
    submission_db.info.update(authorized_area_ids=(), area_access_levels={})
    assert submit(client).status_code in {403, 404}
    assert client.get("/api/cases/submissions/v70-attempt").json() == {
        "status": "unconfirmed", "case_id": None}
    submission_db.info.update(authorized_area_ids=(1,), area_access_levels={1: "read"})
    assert submit(client).status_code == 403


def test_deleted_case_does_not_free_key_for_another_create(submission_db):
    client = client_for(submission_db)
    item_id = submit(client).json()["id"]
    submission_db.delete(submission_db.get(Case, item_id))
    submission_db.commit()
    assert client.get("/api/cases/submissions/v70-attempt").json() == {
        "status": "unconfirmed", "case_id": None}
    assert submit(client).status_code == 404


@pytest.mark.parametrize("key", ["", "contains space", "a" * 129, "bad/key"])
def test_invalid_key_is_rejected_without_case(submission_db, key):
    assert submit(client_for(submission_db), key).status_code == 422
    assert submission_db.query(Case).count() == 0


def test_key_requires_identity_but_legacy_creation_stays_compatible(search_db):
    client = client_for(search_db)
    assert submit(client).status_code == 401
    assert client.get("/api/cases/submissions/v70-attempt").status_code == 401
    assert client.post("/api/cases/", json={"description": "兼容旧客户端"}).status_code == 200


def test_failed_transaction_has_no_receipt_and_original_key_can_retry(submission_db, monkeypatch):
    from app.models.case_submission import CaseSubmissionReceipt

    client = TestClient(client_for(submission_db).app, raise_server_exceptions=False)
    commit = submission_db.commit
    monkeypatch.setattr(submission_db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("test failure")))
    assert submit(client).status_code == 500
    assert submission_db.query(Case).count() == 0
    assert submission_db.query(CaseSubmissionReceipt).count() == 0
    assert client.get("/api/cases/submissions/v70-attempt").json()["status"] == "unconfirmed"
    monkeypatch.setattr(submission_db, "commit", commit)
    assert submit(client).status_code == 200


def test_committed_but_lost_response_is_confirmable(submission_db, monkeypatch):
    client = TestClient(client_for(submission_db).app, raise_server_exceptions=False)
    commit = submission_db.commit

    def lost_response():
        commit()
        raise SQLAlchemyError("synthetic response lost after commit")

    monkeypatch.setattr(submission_db, "commit", lost_response)
    assert submit(client).status_code == 500
    status = client.get("/api/cases/submissions/v70-attempt").json()
    assert status["status"] == "completed" and status["case_id"]
    monkeypatch.setattr(submission_db, "commit", commit)
    assert submit(client).json()["id"] == status["case_id"]
    assert submission_db.query(Case).count() == 1


def test_new_receipt_claim_avoids_a_savepoint_without_skipping_unique_arbitration(submission_db):
    statements = []
    engine = submission_db.get_bind()

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = submit(client_for(submission_db), case_number="synthetic-manual-claim")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    # A manual number needs no numbering savepoint either, isolating the receipt.
    assert not any(sql.startswith(("SAVEPOINT", "RELEASE")) for sql in statements)
    claims = [sql for sql in statements if sql.startswith("INSERT INTO case_submission_receipts")]
    assert len(claims) == 1
    assert "ON CONFLICT (user_id, idempotency_key) DO NOTHING" in claims[0]
    assert "RETURNING id" in claims[0]
    assert submit(client_for(submission_db), case_number="synthetic-manual-claim").json()["id"] == response.json()["id"]


def test_claim_does_not_ignore_unrelated_foreign_key_failure(submission_db):
    from app.models.case_submission import CaseSubmissionReceipt

    submission_db.info["principal_user_id"] = 9999
    client = TestClient(client_for(submission_db).app, raise_server_exceptions=False)
    assert submit(client).status_code == 500
    assert submission_db.query(Case).count() == 0
    assert submission_db.query(CaseSubmissionReceipt).count() == 0
    # A rejected integrity violation did not leave a pending claim or bad Session.
    submission_db.info["principal_user_id"] = 71
    assert submit(client).status_code == 200


@pytest.mark.parametrize("case_number", [None, "manual-synthetic-number"])
def test_parallel_requests_create_only_one_case_and_receipt(tmp_path, case_number):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.api.cases import CaseCreate, create_case
    from app.database import Base
    from app.models.case_submission import CaseSubmissionReceipt

    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent-submissions.sqlite'}",
                           connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id=71, username="parallel", display_name="合成用户", password_hash="test", role="admin"))
        db.commit()
    barrier = Barrier(4)

    def run(_):
        with Session(engine) as db:
            db.info["principal_user_id"] = 71
            barrier.wait(timeout=10)
            case = create_case(CaseCreate(case_number=case_number, description="合成并发"),
                               db=db, idempotency_key="parallel-attempt")
            return case.id

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(run, range(4)))
        assert len(set(ids)) == 1
        with Session(engine) as db:
            assert db.query(Case).count() == db.query(CaseSubmissionReceipt).count() == 1
            assert db.query(CaseRevision).count() == 1
    finally:
        engine.dispose()
