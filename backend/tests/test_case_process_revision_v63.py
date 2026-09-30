"""Source identity is stronger than a content hash, including A -> B -> A edits."""
from copy import deepcopy

import pytest

from app.config import settings
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_process_contract import digest
from app.services.case_result_access import CaseResultAccessError, require_result_access
from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import assemble_case_result, verify_snapshot
from app.services.case_saved_profile import read_saved_profile
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService
from tests.test_case_sources_v61 import db  # noqa: F401


@pytest.fixture(autouse=True)
def model_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CASE_SEMANTIC_MODEL_ID", None)


def prepared(db):
    case = CaseService.create_case(db, case_number="R07-REV-SYNTHETIC", description="抽取原油。")
    event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").one()
    CasePipelineService.process_event(db, event.id)
    return case, db.query(CaseAnalysisProfile).one()


def restore_without_worker(db, case):
    original = case.description
    CaseService.update_case(db, case.id, description="转运原油。")
    CaseService.update_case(db, case.id, description=original)
    return CaseSourceService.latest_revision(db, case.id)


def test_same_hash_different_revision_is_updating_until_worker_completes(db):
    case, profile = prepared(db)
    first = CaseResultService.latest_base(db, case.id)
    assert read_saved_profile(db, case)["status"] == "ready"
    assert first["freshness"] == "current"
    revision = restore_without_worker(db, case)
    assert revision.source_hash == profile.source_hash and revision.id != profile.source_revision_id
    assert read_saved_profile(db, case)["status"] == "updating"
    pending = CaseResultService.latest_base(db, case.id)
    assert pending["freshness"] == "pending_update" and pending["id"] == first["id"]
    # Historical identity remains readable; only current applicability changed.
    require_result_access(db, pending)
    from app.models.case_pipeline import CasePipelineState
    state = db.query(CasePipelineState).filter_by(case_id=case.id).one()
    CasePipelineService.process_event(db, state.event_id)
    assert read_saved_profile(db, case)["status"] == "ready"
    newest = CaseResultService.latest_base(db, case.id)
    assert newest["freshness"] == "current"
    assert newest["content"]["versions"]["source_revision_id"] == revision.id


def test_snapshot_revision_and_profile_column_are_both_checked(db):
    case, profile = prepared(db)
    original = assemble_case_result(profile, None, [])
    revision = restore_without_worker(db, case)
    changed = deepcopy(original)
    changed["content"]["versions"]["source_revision_id"] = revision.id
    changed["content_sha256"] = digest(changed["content"])
    assert not verify_snapshot(changed)

    def replace_revision(value):
        if isinstance(value, dict):
            if "source_revision_id" in value:
                value["source_revision_id"] = revision.id
            for child in value.values():
                replace_revision(child)
        elif isinstance(value, list):
            for child in value:
                replace_revision(child)

    replace_revision(changed["content"]["semantics"]["process"])
    changed["content_sha256"] = digest(changed["content"])
    assert verify_snapshot(changed)  # Internally consistent, not trusted authority.
    with pytest.raises(CaseResultAccessError):
        require_result_access(db, changed)
    require_result_access(db, original)


def test_saved_profile_rejects_revision_splicing_inside_payload(db):
    case, profile = prepared(db)
    revision = restore_without_worker(db, case)
    altered = deepcopy(profile.payload)
    altered["source_revision_id"] = revision.id
    profile.payload = altered
    db.commit()
    assert read_saved_profile(db, case) == {"status": "unavailable", "data": None}
    with pytest.raises(ValueError, match="process_source_revision"):
        assemble_case_result(profile, None, [])


def test_legacy_snapshot_without_process_preserves_its_hash_contract():
    from tests.test_case_result_snapshot import inputs
    profile, run, candidate = inputs()
    original = assemble_case_result(profile, run, [candidate])
    profile.source_revision_id = 7
    after = assemble_case_result(profile, run, [candidate])
    assert original == after
    assert "source_revision_id" not in after["content"]["versions"]
