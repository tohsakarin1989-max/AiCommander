"""旧知识检索/问答在交付新结论前重新核验冻结来源。"""
import asyncio
import json

import pytest

from app.models.conclusion import Conclusion
from app.services.case_knowledge_service import CaseKnowledgeService
from app.services.case_result_service import CaseResultService
from app.services.conclusion_factory_service import ConclusionFactoryService
from test_conclusion_result_reuse import current_profile, result_data  # noqa: F401


@pytest.mark.parametrize("method", ["search", "evidence_qa", "citation_assist"])
def test_revoked_result_cannot_enter_legacy_knowledge_response(
    db_session, current_profile, result_data, method,
):
    marker = "甲乙丙丁戊己庚辛壬癸"
    result_data[2].claim = marker
    result_data[2].evidence_refs = ["case:2"]
    db_session.commit()
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    draft = asyncio.run(ConclusionFactoryService.generate_conclusion(db_session, 1))
    reader = getattr(CaseKnowledgeService, method)
    before = reader(db_session, marker, case_id=1)
    assert marker in json.dumps({key: value for key, value in before.items() if key != "query"}, ensure_ascii=False)
    assert draft.id in [item.id for item in CaseKnowledgeService._conclusion_query(db_session, 1)]

    db_session.info["authorized_area_ids"] = (1,)
    after = reader(db_session, marker, case_id=1)
    assert marker not in json.dumps({key: value for key, value in after.items() if key != "query"}, ensure_ascii=False)
    assert after["insufficient_evidence"] is True
    assert CaseKnowledgeService._conclusion_query(db_session, 1) == []


def test_legacy_conclusion_without_result_reference_keeps_existing_read_contract(db_session, current_profile):
    marker = "LegacyEvidenceTokenY"
    legacy = Conclusion(case_id=1, summary=marker, status="published", evidence={"key_evidence": [marker]})
    db_session.add(legacy)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    results = CaseKnowledgeService.search(db_session, marker, case_id=1)
    assert results["items"][0]["source_type"] == "conclusion"
    assert results["items"][0]["source_id"] == legacy.id
    assert results["items"][0]["snippet"] == marker


def test_missing_frozen_source_does_not_fall_back_to_saved_summary(db_session, current_profile):
    marker = "子丑寅卯辰巳午未申酉"
    db_session.add(Conclusion(case_id=1, summary=marker, status="needs_review", evidence={
        "source_result": {"result_id": "not-present", "content_sha256": "invalid"},
    }))
    db_session.commit()
    results = CaseKnowledgeService.search(db_session, marker, case_id=1)
    assert results["items"] == []
    assert results["insufficient_evidence"] is True
    assert marker not in json.dumps(results.get("items"), ensure_ascii=False)
