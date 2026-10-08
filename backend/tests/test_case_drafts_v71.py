"""Private work-in-progress is not a Case until an atomic explicit submit."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api import case_drafts, cases
from app.database import get_db
from app.models.case import Case
from app.models.case_draft import CaseDraft
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import CaseRevision
from app.models.case_submission import CaseSubmissionReceipt
from tests.test_case_submissions_v70 import submission_db  # noqa: F401
from tests.test_case_search_page import search_db  # noqa: F401


@pytest.fixture
def client(submission_db):
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")
    app.include_router(case_drafts.router, prefix="/api/case-drafts")
    app.dependency_overrides[get_db] = lambda: submission_db
    return TestClient(app, raise_server_exceptions=False)


def draft_body(**changes):
    return {"expected_revision": 0, "operational_area_id": 1, "schema_version": 1,
            "form_snapshot": {"occurred_time": "还没填完", "aiIntakeText": "合成原文", "bonus": True}, **changes}


def save_draft(client, draft_id=None, **changes):
    draft_id = draft_id or str(uuid4())
    response = client.put(f"/api/case-drafts/{draft_id}", json=draft_body(**changes))
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, draft, **changes):
    return client.post(f'/api/case-drafts/{draft["id"]}/submit', json={
        "expected_revision": draft["revision"],
        "case_payload": {"operational_area_id": 1, "description": "合成正式原始记录"}, **changes})


def test_incomplete_draft_roundtrip_is_retry_safe_and_not_a_business_record(client, submission_db):
    item = save_draft(client)
    assert item["status"] == "active" and item["revision"] == 1
    assert item["expires_at"].endswith("Z") or item["expires_at"].endswith("+00:00")
    assert item["form_snapshot"]["occurred_time"] == "还没填完"
    retry = save_draft(client, item["id"])
    assert retry["revision"] == 1 and retry["submission_key"] == item["submission_key"]
    assert client.get(f'/api/case-drafts/{item["id"]}').headers["cache-control"] == "no-store"
    assert client.get('/api/case-drafts').json()["total"] == 1
    for model in (Case, CaseRevision, OutboxEvent, CaseSubmissionReceipt):
        assert submission_db.query(model).count() == 0
    newer = save_draft(client, item["id"], expected_revision=1, form_snapshot={"description": "较新输入"})
    assert newer["revision"] == 2
    stale = client.put(f'/api/case-drafts/{item["id"]}', json=draft_body(expected_revision=1))
    assert stale.status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json()["form_snapshot"] == {"description": "较新输入"}


def test_private_scope_expiry_and_delete_cas(client, submission_db):
    item = save_draft(client)
    path = f'/api/case-drafts/{item["id"]}'
    submission_db.info["principal_user_id"] = 72
    assert client.get(path).status_code == 404
    assert client.get(path).headers["cache-control"] == "no-store"
    assert client.get('/api/case-drafts').json()["total"] == 0
    assert client.put(path, json=draft_body()).status_code == 404
    submission_db.info["principal_user_id"] = 71
    submission_db.info.update(authorized_area_ids=(), area_access_levels={})
    assert client.get(path).status_code == 404
    submission_db.info.update(authorized_area_ids=(1,), area_access_levels={1: "read"})
    assert client.get(path).status_code == 404
    submission_db.info["area_access_levels"] = {1: "write"}
    assert client.delete(path, params={"expected_revision": 99}).status_code == 409
    record = submission_db.get(CaseDraft, item["id"])
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    submission_db.commit()
    assert client.get(path).status_code == 404
    assert client.get('/api/case-drafts').json()["total"] == 0
    assert client.put(path, json=draft_body()).status_code == 404


def test_submit_consumes_draft_and_receipt_in_one_transaction(client, submission_db):
    item = save_draft(client)
    first = submit(client, item)
    assert first.status_code == 200, first.text
    retry = submit(client, item)
    assert retry.status_code == 200 and retry.json()["case_id"] == first.json()["case_id"]
    latest = client.get(f'/api/case-drafts/{item["id"]}').json()
    assert latest["status"] == "submitted"
    assert latest["submitted_case_id"] == first.json()["case_id"]
    assert latest["form_snapshot"] == {}
    assert submit(client, item, case_payload={"description": "改过的提交内容"}).status_code == 409
    assert submission_db.query(Case).count() == submission_db.query(CaseRevision).count() == 1
    assert submission_db.query(CaseSubmissionReceipt).count() == 1
    assert client.get(f'/api/cases/submissions/{item["submission_key"]}').json()["case_id"] == first.json()["case_id"]


def test_failed_or_lost_submit_response_never_partially_consumes(client, submission_db, monkeypatch):
    item = save_draft(client)
    original_commit = submission_db.commit
    monkeypatch.setattr(submission_db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("synthetic failure")))
    assert submit(client, item).status_code == 500
    assert submission_db.query(Case).count() == submission_db.query(CaseSubmissionReceipt).count() == 0
    assert client.get(f'/api/case-drafts/{item["id"]}').json()["form_snapshot"] == item["form_snapshot"]

    def lost_response():
        original_commit()
        raise SQLAlchemyError("synthetic lost response")

    monkeypatch.setattr(submission_db, "commit", lost_response)
    assert submit(client, item).status_code == 500
    monkeypatch.setattr(submission_db, "commit", original_commit)
    state = client.get(f'/api/case-drafts/{item["id"]}').json()
    assert state["status"] == "submitted"
    assert submit(client, item).json()["case_id"] == state["submitted_case_id"]
    assert submission_db.query(Case).count() == 1


def test_edit_snapshot_detects_scalar_and_detail_updates(client):
    created = client.post('/api/cases/', json={"description": "原始", "operational_area_id": 1}).json()
    path = f'/api/cases/{created["id"]}/edit-snapshot'
    baseline = client.get(path)
    assert baseline.status_code == 200, baseline.text
    revision = baseline.json()["source_revision"]
    assert client.put(path, json={"case_payload": {"description": "缺少版本"}}).status_code == 422
    added = client.post(f'/api/cases/{created["id"]}/persons', json={"name": "合成人员"})
    assert added.status_code == 200, added.text
    stale = client.put(path, json={"expected_revision": revision, "case_payload": {"description": "旧页面覆盖"}})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "case_revision_conflict"
    current = client.get(path).json()
    assert current["case"]["description"] == "原始" and len(current["initial_persons"]) == 1
    saved = client.put(path, json={"expected_revision": current["source_revision"], "case_payload": {"description": "明确更正"}})
    assert saved.status_code == 200 and saved.json()["case"]["description"] == "明确更正"
    legacy = client.put(f'/api/cases/{created["id"]}', json={"expected_revision": revision, "description": "旧token"})
    assert legacy.status_code == 409


def test_edit_draft_conflict_retains_work_and_explicit_rebase_submits_once(client, submission_db):
    created = client.post('/api/cases/', json={"description": "原始", "operational_area_id": 1}).json()
    path = f'/api/cases/{created["id"]}/edit-snapshot'
    baseline = client.get(path).json()
    item = save_draft(client, target_case_id=created["id"], base_case_revision=baseline["source_revision"])
    client.put(f'/api/cases/{created["id"]}', json={"description": "同事更正"})
    assert submit(client, item, case_payload={"description": "本地更正"}).status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json()["form_snapshot"] == item["form_snapshot"]
    latest = client.get(path).json()
    item = save_draft(client, item["id"], expected_revision=item["revision"],
                      target_case_id=created["id"], base_case_revision=latest["source_revision"])
    first = submit(client, item, case_payload={"description": "双方核对后的更正"})
    assert first.status_code == 200, first.text
    assert submit(client, item, case_payload={"description": "双方核对后的更正"}).json()["case_id"] == created["id"]
    assert submission_db.query(Case).count() == 1


def test_expiry_cleanup_removes_private_content_only(client, submission_db):
    from app.services.case_draft_service import purge_expired_case_drafts

    active = save_draft(client)
    expired = save_draft(client)
    record = submission_db.get(CaseDraft, expired["id"])
    record.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    submission_db.commit()
    assert purge_expired_case_drafts(submission_db) == 1
    assert submission_db.get(CaseDraft, active["id"]) is not None
    assert submission_db.query(Case).count() == 0


@pytest.mark.parametrize("revision", [None, False, "1", -1])
def test_provided_invalid_revision_never_bypasses_legacy_guard(client, revision):
    created = client.post('/api/cases/', json={"description": "原始", "operational_area_id": 1}).json()
    assert client.put(f'/api/cases/{created["id"]}', json={
        "expected_revision": revision, "description": "不能覆盖"}).status_code == 422
    assert client.get(f'/api/cases/{created["id"]}').json()["description"] == "原始"


def test_list_filters_before_pagination_and_never_leaks_another_owner(client, submission_db):
    own = [save_draft(client) for _ in range(3)]
    submission_db.info["principal_user_id"] = 72
    save_draft(client)
    submission_db.info["principal_user_id"] = 71
    pages = [client.get('/api/case-drafts', params={"page_size": 2, "page": page}).json() for page in (1, 2)]
    assert [page["total"] for page in pages] == [3, 3]
    assert {item["id"] for page in pages for item in page["items"]} == {item["id"] for item in own}
    assert submit(client, own[0]).status_code == 200
    assert client.get('/api/case-drafts').json()["total"] == 2
    assert client.get('/api/case-drafts', params={"status": "submitted"}).json()["total"] == 1
    assert client.get('/api/case-drafts', params={"status": "all"}).json()["total"] == 3


def test_invalid_or_changed_area_and_submission_key_leave_draft_untouched(client, submission_db):
    from app.models.map_foundation import OperationalArea

    item = save_draft(client)
    assert client.put(f'/api/case-drafts/{item["id"]}', json=draft_body(
        expected_revision=1, operational_area_id=2)).status_code == 403
    submission_db.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write", 2: "write"})
    assert client.put(f'/api/case-drafts/{item["id"]}', json=draft_body(
        expected_revision=1, operational_area_id=2)).status_code == 422
    assert client.post(f'/api/case-drafts/{item["id"]}/submit', headers={"Idempotency-Key": "different"},
        json={"expected_revision": 1, "case_payload": {"description": "合成"}}).status_code == 409
    assert submit(client, item, case_payload={"operational_area_id": 2, "description": "合成"}).status_code == 422
    assert submission_db.query(Case).count() == submission_db.query(CaseSubmissionReceipt).count() == 0
    assert client.get(f'/api/case-drafts/{item["id"]}').json()["revision"] == 1
    area = submission_db.get(OperationalArea, 1)
    area.status = "inactive"
    submission_db.commit()
    assert client.get(f'/api/case-drafts/{item["id"]}').status_code == 404
    assert submit(client, item).status_code == 404
    assert client.put(f'/api/case-drafts/{uuid4()}', json=draft_body()).status_code == 422


def test_deleted_targets_and_consumed_cases_cannot_recreate_a_case(client, submission_db):
    created = client.post('/api/cases/', json={"description": "原始", "operational_area_id": 1}).json()
    revision = client.get(f'/api/cases/{created["id"]}/edit-snapshot').json()["source_revision"]
    edit = save_draft(client, target_case_id=created["id"], base_case_revision=revision)
    assert client.delete(f'/api/cases/{created["id"]}').status_code == 200
    assert client.get(f'/api/case-drafts/{edit["id"]}').status_code == 404
    assert submit(client, edit).status_code == 404
    item = save_draft(client)
    case_id = submit(client, item).json()["case_id"]
    assert client.delete(f'/api/cases/{case_id}').status_code == 200
    assert client.get(f'/api/case-drafts/{item["id"]}').status_code == 404
    assert submit(client, item).status_code == 404
    assert submission_db.query(Case).count() == 0
    assert submission_db.query(CaseSubmissionReceipt).count() == 1


def test_snapshot_is_read_only_and_preserves_all_typed_details(client, submission_db):
    created = client.post('/api/cases/', json={"description": "合成多明细", "operational_area_id": 1,
        "initial_vehicles": [{"plate_number": "合成A001"}], "initial_persons": [{"name": "合成人"}],
        "initial_locations": [{"role": "incident", "description": "合成地点"}],
        "initial_measurements": [{"stage": "seized", "value": 10, "unit": "liter"}]} )
    assert created.status_code == 200, created.text
    before = {model: submission_db.query(model).count() for model in (CaseRevision, OutboxEvent)}
    result = client.get(f'/api/cases/{created.json()["id"]}/edit-snapshot')
    assert result.status_code == 200, result.text
    for kind in ("vehicles", "persons", "locations", "measurements"):
        assert len(result.json()[f"initial_{kind}"]) == 1
    assert before == {model: submission_db.query(model).count() for model in before}


def test_large_snapshot_and_malformed_revisions_are_rejected_without_writes(client, submission_db):
    assert client.put(f'/api/case-drafts/{uuid4()}', json=draft_body(
        form_snapshot={"text": "x" * 262144})).status_code == 422
    assert client.put('/api/case-drafts/not-a-uuid', json=draft_body()).status_code == 422
    assert client.put(f'/api/case-drafts/{uuid4()}', json=draft_body(expected_revision=False)).status_code == 422
    assert submission_db.query(CaseDraft).count() == 0


def test_followup_only_runs_after_successful_atomic_commit(client, submission_db, monkeypatch):
    from app.services.case_service import CaseService

    item = save_draft(client)
    observed = []
    monkeypatch.setattr(CaseService, "finish_created_case", lambda db, case: observed.append(
        db.get(CaseDraft, item["id"]).status))
    original_commit = submission_db.commit
    monkeypatch.setattr(submission_db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("synthetic")))
    assert submit(client, item).status_code == 500
    assert not observed
    monkeypatch.setattr(submission_db, "commit", original_commit)
    assert submit(client, item).status_code == 200
    assert observed == ["submitted"]


def test_cleanup_task_is_registered_without_analysis_work():
    from app.config import settings
    from app.tasks.celery_app import build_beat_schedule, celery_app

    schedule = build_beat_schedule(settings)["expire-case-drafts"]
    assert schedule["task"] == "aicommander.case_drafts.expire"
    assert schedule["schedule"] == 3600
    assert "app.tasks.case_draft_tasks" in celery_app.conf.include


def test_role_demotion_does_not_leave_private_drafts_readable(client, submission_db):
    from app.models.user import User

    item = save_draft(client)
    owner = submission_db.get(User, 71)
    owner.role = "viewer"
    submission_db.commit()
    # Old area scopes can still exist after a role downgrade. Private editable
    # snapshots must not become a loophole around the now read-only role.
    assert client.get(f'/api/case-drafts/{item["id"]}').status_code == 404
    assert client.get('/api/case-drafts').json()["total"] == 0


def test_receipt_from_another_area_cannot_consume_private_draft(client, submission_db):
    item = save_draft(client)
    submission_db.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write", 2: "write"},
                              default_operational_area_id=2)
    payload = {"description": "相同内容但在另一厂区创建"}
    other = client.post('/api/cases/', headers={"Idempotency-Key": item["submission_key"]}, json=payload)
    assert other.status_code == 200 and other.json()["operational_area_id"] == 2
    assert submit(client, item, case_payload=payload).status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json()["status"] == "active"
    assert submission_db.query(Case).count() == 1


@pytest.mark.parametrize("mode", ["create", "edit"])
def test_confirm_only_active_draft_never_writes(client, submission_db, mode):
    target = {}
    if mode == "edit":
        case = client.post('/api/cases/', json={"description": "原始合成事实", "operational_area_id": 1}).json()
        target = {"target_case_id": case["id"], "base_case_revision":
                  client.get(f'/api/cases/{case["id"]}/edit-snapshot').json()["source_revision"]}
    item = save_draft(client, **target)
    models = (Case, CaseRevision, OutboxEvent, CaseSubmissionReceipt)
    before = {model: submission_db.query(model).count() for model in models}
    result = submit(client, item, confirm_only=True)
    assert result.status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json() == item
    assert before == {model: submission_db.query(model).count() for model in models}
    if mode == "edit":
        assert submission_db.get(Case, target["target_case_id"]).description == "原始合成事实"


def test_confirm_only_submitted_same_payload_returns_original_without_writes(client, submission_db):
    from sqlalchemy import event

    item = save_draft(client)
    first = submit(client, item)
    assert first.status_code == 200
    before = client.get(f'/api/case-drafts/{item["id"]}').json()
    writes = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = submission_db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        confirmed = submit(client, item, confirm_only=True)
        assert confirmed.status_code == 200
        assert confirmed.json() == first.json()
        assert client.get(f'/api/case-drafts/{item["id"]}').json() == before
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not writes


def test_confirm_only_other_submitted_payload_conflicts_without_changes(client, submission_db):
    item = save_draft(client)
    first = submit(client, item, case_payload={"description": "另一页面提交的内容", "operational_area_id": 1})
    assert first.status_code == 200
    before = client.get(f'/api/case-drafts/{item["id"]}').json()
    revisions = submission_db.query(CaseRevision).count()
    events = submission_db.query(OutboxEvent).count()
    assert submit(client, item, confirm_only=True).status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json() == before
    assert submission_db.get(Case, first.json()["case_id"]).description == "另一页面提交的内容"
    assert submission_db.query(CaseRevision).count() == revisions
    assert submission_db.query(OutboxEvent).count() == events


def test_confirm_only_deleted_and_recreated_id_does_not_promote_new_draft(client, submission_db):
    item = save_draft(client)
    assert client.delete(f'/api/case-drafts/{item["id"]}', params={"expected_revision": 1}).status_code == 204
    recreated = save_draft(client, item["id"], form_snapshot={"description": "同ID的新草稿"})
    assert recreated["revision"] == item["revision"]
    assert submit(client, item, confirm_only=True).status_code == 409
    assert client.get(f'/api/case-drafts/{item["id"]}').json() == recreated
    for model in (Case, CaseRevision, OutboxEvent, CaseSubmissionReceipt):
        assert submission_db.query(model).count() == 0


@pytest.mark.parametrize("value", ["true", 1, None])
def test_confirm_only_requires_a_real_boolean(client, submission_db, value):
    item = save_draft(client)
    assert submit(client, item, confirm_only=value).status_code == 422
    assert submission_db.query(Case).count() == 0
