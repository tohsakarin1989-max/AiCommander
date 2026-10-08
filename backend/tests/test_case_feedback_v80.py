"""Explicit feedback provenance, using only isolated synthetic records."""
import pytest

from app.models.case import Case
from app.models.case_source import CaseRevision
from app.services.case_feedback_semantics import feedback_state, known_feedback_value
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService
from tests.test_case_submissions_v70 import submission_db  # noqa: F401
from tests.test_case_search_page import client_for, search_db  # noqa: F401


def create(client, **values):
    return client.post("/api/cases/", json={"description": "现场发现后移交公安，后续反馈未知", **values})


def test_new_intake_keeps_police_feedback_unknown(search_db):
    response = create(client_for(search_db))
    assert response.status_code == 200
    data = response.json()
    assert data["police_reported"] is None and data["case_filed"] is None
    assert data["feedback_known_fields"] == []
    assert known_feedback_value(data, "case_filed") is None
    assert feedback_state(data, "police_reported") == "unknown"
    revision = search_db.query(CaseRevision).one()
    assert revision.payload["case"]["feedback_known_fields"] == []


@pytest.mark.parametrize("unknown", ["", "未知", "未获反馈", "不详", "unknown"])
def test_import_unknown_feedback_does_not_become_no(search_db, unknown):
    from app.services.case_import_values import normalize_case_row

    values = normalize_case_row({"description": "合成台账记录", "police_reported": unknown,
                                 "case_filed": unknown}, time_zone="Asia/Shanghai")
    case = CaseService.create_case(search_db, case_number=None, **values)
    assert case.police_reported is None and case.case_filed is None
    assert case.feedback_known_fields == []


def test_import_explicit_negative_is_preserved_as_known(search_db):
    from app.services.case_import_values import normalize_case_row

    values = normalize_case_row({"description": "合成台账记录", "police_reported": "是",
                                 "case_filed": "否"}, time_zone="Asia/Shanghai")
    case = CaseService.create_case(search_db, case_number=None, **values)
    assert known_feedback_value(case, "case_filed") is False
    assert known_feedback_value(case, "police_reported") is True


def test_explicit_no_is_distinct_from_unknown_and_handover_is_not_closure(search_db):
    response = create(client_for(search_db), police_reported=True, case_filed=False,
                      person_handling="移交公安", vehicle_handling="移交公安", oil_handling="移交公安")
    assert response.status_code == 200
    data = response.json()
    assert data["feedback_known_fields"] == ["case_filed", "police_reported"]
    assert known_feedback_value(data, "police_reported") is True
    assert known_feedback_value(data, "case_filed") is False
    assert data["status"] == "pending" and data["current_stage"] == "reported"


@pytest.mark.parametrize("legacy_value", [True, False])
def test_legacy_value_survives_unrelated_edit_without_confirmation(search_db, legacy_value):
    case = Case(case_number="LEGACY-FEEDBACK", description="旧资料", police_reported=legacy_value,
                case_filed=legacy_value, time_precision="unknown")
    search_db.add(case)
    search_db.commit()
    original = CaseSourceService.source_payload(search_db, case)
    assert "feedback_known_fields" not in original["case"]
    CaseSourceService.capture_change(search_db, case)
    search_db.commit()
    before = search_db.query(CaseRevision).one()
    CaseService.update_case(search_db, case.id, description="仅补充现场经过")
    assert case.police_reported is legacy_value and case.case_filed is legacy_value
    assert case.feedback_known_fields is None
    assert feedback_state(case, "case_filed") == "legacy_unverified"
    assert known_feedback_value(case, "case_filed") is None
    assert before.payload == original
    assert CaseSourceService.source_payloads(search_db, [case])[case.id] == CaseSourceService.source_payload(search_db, case)


def test_confirmation_of_same_legacy_false_is_a_versioned_fact_and_repeat_is_idempotent(search_db):
    case = Case(case_number="CONFIRM-LEGACY", description="旧资料", police_reported=False,
                case_filed=True, time_precision="unknown")
    search_db.add(case)
    search_db.flush()
    old, _ = CaseSourceService.capture_change(search_db, case)
    search_db.commit()
    CaseService.update_case(search_db, case.id, police_reported=False)
    current = CaseSourceService.latest_revision(search_db, case.id)
    assert current.revision == old.revision + 1 and current.source_hash != old.source_hash
    assert case.police_reported is False and case.feedback_known_fields == ["police_reported"]
    assert known_feedback_value(case, "police_reported") is False
    assert feedback_state(case, "case_filed") == "legacy_unverified"
    CaseService.update_case(search_db, case.id, police_reported=False)
    assert CaseSourceService.latest_revision(search_db, case.id).id == current.id
    CaseService.update_case(search_db, case.id, police_reported=None)
    assert case.police_reported is None and case.feedback_known_fields == []
    assert current.payload["case"]["police_reported"] is False
    assert old.payload["case"]["police_reported"] is False
    assert "feedback_known_fields" not in old.payload["case"]


def test_api_cannot_claim_provenance_and_rejected_update_leaves_original(search_db):
    client = client_for(search_db)
    assert create(client, feedback_known_fields=["police_reported"]).status_code == 422
    case = create(client, police_reported=False).json()
    revision_count = search_db.query(CaseRevision).count()
    response = client.put(f"/api/cases/{case['id']}", json={
        "feedback_known_fields": ["case_filed"], "description": "不应保存"})
    assert response.status_code == 422
    assert search_db.get(Case, case["id"]).description == case["description"]
    assert search_db.query(CaseRevision).count() == revision_count


def test_api_edit_unknown_and_omitted_feedback_are_different(search_db):
    client = client_for(search_db)
    item_id = create(client, case_filed=False).json()["id"]
    preserved = client.put(f"/api/cases/{item_id}", json={"description": "现场记录补充"})
    assert preserved.status_code == 200
    assert preserved.json()["case_filed"] is False
    assert preserved.json()["feedback_known_fields"] == ["case_filed"]
    cleared = client.put(f"/api/cases/{item_id}", json={"case_filed": None})
    assert cleared.status_code == 200
    assert cleared.json()["case_filed"] is None and cleared.json()["feedback_known_fields"] == []


def test_preview_uses_explicit_feedback_without_writing_sources(search_db):
    response = client_for(search_db).post("/api/cases/quality-preview", json={
        "description": "合成现场记录", "case_filed": True, "police_reported": False})
    assert response.status_code == 200
    assert any(item["field"] == "case_filed" for item in response.json()["warnings"])
    assert search_db.query(Case).count() == search_db.query(CaseRevision).count() == 0


def test_save_retry_retains_provenance_without_additional_revision(submission_db):
    client = client_for(submission_db)
    payload = {"description": "合成反馈记录", "operational_area_id": 1,
               "police_reported": False, "case_filed": None}
    headers = {"Idempotency-Key": "v80-feedback-retry"}
    first = client.post("/api/cases/", json=payload, headers=headers)
    second = client.post("/api/cases/", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["feedback_known_fields"] == ["police_reported"]
    assert submission_db.query(CaseRevision).count() == 1


def test_failed_edit_rolls_back_feedback_value_and_provenance(search_db, monkeypatch):
    case = CaseService.create_case(search_db, "FEEDBACK-ROLLBACK", case_filed=False)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic_delivery_failure")

    monkeypatch.setattr(CaseSourceService, "attach_delivery", fail)
    with pytest.raises(RuntimeError, match="synthetic_delivery_failure"):
        CaseService.update_case(search_db, case.id, case_filed=None)
    search_db.refresh(case)
    assert case.case_filed is False and case.feedback_known_fields == ["case_filed"]
    assert search_db.query(CaseRevision).count() == 1


def test_preprocess_prompt_excludes_unverified_legacy_feedback(search_db, monkeypatch):
    from app.services.case_quality_service import CaseQualityService
    from app.services.preprocess_service import CasePreprocessService

    case = Case(case_number="LEGACY-PROMPT", police_reported=True, case_filed=False)
    monkeypatch.setattr(CaseQualityService, "build_case_feature_profile", lambda *_: {})
    prompt = CasePreprocessService._build_prompt(search_db, case)
    assert "- police_reported:" not in prompt and "- case_filed:" not in prompt
    case.feedback_known_fields = ["police_reported", "case_filed"]
    prompt = CasePreprocessService._build_prompt(search_db, case)
    assert "- police_reported: True" in prompt and "- case_filed: False" in prompt


def test_legacy_boolean_does_not_require_police_feedback_documents():
    from app.services.case_automation_service import CaseAutomationService

    case = Case(case_number="LEGACY-MATERIAL", police_reported=True, case_filed=True)
    related = {"vehicles": [], "persons": [], "evidence": [], "oil_recovery": []}
    checks = CaseAutomationService._build_material_checks(case, related)
    police = next(item for item in checks if item["requirement_key"] == "police_case_document")
    assert police["status"] == "not_required"
    case.feedback_known_fields = ["police_reported"]
    checks = CaseAutomationService._build_material_checks(case, related)
    police = next(item for item in checks if item["requirement_key"] == "police_case_document")
    assert police["status"] == "missing"
