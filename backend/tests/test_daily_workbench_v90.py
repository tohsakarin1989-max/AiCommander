from datetime import datetime, timezone
from uuid import uuid4

from app.models.case import Case
from app.models.case_import import CaseImportBatch, CaseImportRow
from app.services.case_draft_service import save_draft
from app.services.daily_workbench_service import DailyWorkbenchService, information_gaps
from tests.test_case_submissions_v70 import submission_db  # noqa: F401
from tests.test_case_search_page import search_db  # noqa: F401


def test_sparse_field_record_does_not_demand_investigation_time():
    item = Case(description="已记录查获和本单位处置", location="查获地点",
                discovered_at=datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert information_gaps(item) == []


def test_personal_resume_never_aggregates_other_owners_or_without_identity(submission_db):
    db = submission_db
    own = save_draft(db, str(uuid4()), expected_revision=0, operational_area_id=1,
                     form_snapshot={"values": {"description": "本人尚未登记原文"}})
    db.info["principal_user_id"] = 72
    save_draft(db, str(uuid4()), expected_revision=0, operational_area_id=1,
               form_snapshot={"values": {"description": "他人敏感草稿"}})
    db.info["principal_user_id"] = 71
    for owner in [71, 72]:
        batch = CaseImportBatch(id=str(uuid4()), input_hash=str(owner), operational_area_id=1, created_by=owner)
        db.add(batch); db.flush()
        db.add(CaseImportRow(batch_id=batch.id, operational_area_id=1, row_number=1,
                             source_values={}, current_values={}, status="failed", error="合成错误"))
    db.commit()
    payload = DailyWorkbenchService.daily(db, user_id=71, role="analyst")
    assert payload["resume"]["drafts"]["total"] == 1
    assert payload["resume"]["imports"]["total"] == 1
    assert "敏感草稿" not in str(payload) and own.form_snapshot["values"]["description"] not in str(payload)
    assert DailyWorkbenchService.daily(db)["resume"]["state"] == "unavailable"
    assert DailyWorkbenchService.daily(db, user_id=72, role="analyst")["resume"]["state"] == "unavailable"
    assert DailyWorkbenchService.daily(db, user_id=71, role="viewer")["resume"]["state"] == "not_applicable"
    db.info["area_access_levels"] = {1: "read"}
    assert DailyWorkbenchService.daily(db, user_id=71, role="analyst")["resume"]["drafts"]["total"] == 0
    assert DailyWorkbenchService.daily(db, user_id=71, role="analyst")["resume"]["imports"]["total"] == 0


def test_admin_full_scope_still_only_counts_own_drafts_and_failed_or_conflict_imports(submission_db):
    from app.models.user import User
    from app.database import bind_principal_scope
    from types import SimpleNamespace
    db = submission_db
    db.get(User, 71).role = 'admin'
    db.commit()
    bind_principal_scope(db, SimpleNamespace(user_id=71, role='admin'), method='GET')
    save_draft(db, str(uuid4()), expected_revision=0, operational_area_id=1,
               form_snapshot={'values': {'description': '本人管理员草稿'}})
    db.info['principal_user_id'] = 72
    save_draft(db, str(uuid4()), expected_revision=0, operational_area_id=1,
               form_snapshot={'values': {'description': '他人草稿'}})
    db.info['principal_user_id'] = 71
    for owner, status in [(71, 'conflict'), (71, 'failed'), (72, 'conflict')]:
        batch = CaseImportBatch(id=str(uuid4()), input_hash=str(uuid4()), operational_area_id=1, created_by=owner)
        db.add(batch); db.flush()
        db.add(CaseImportRow(batch_id=batch.id, operational_area_id=1, row_number=1,
                             source_values={}, current_values={}, status=status, error='待核'))
    db.commit()
    resume = DailyWorkbenchService.daily(db, user_id=71, role='admin')['resume']
    assert resume['state'] == 'ready'
    assert resume['drafts']['total'] == 1 and resume['imports']['total'] == 2
    # A role string alone cannot turn a normal analyst into full-scope admin.
    db.info['principal_user_id'] = 72
    assert DailyWorkbenchService.daily(db, user_id=72, role='admin')['resume']['state'] == 'unavailable'
