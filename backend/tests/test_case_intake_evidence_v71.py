import hashlib
import json
from types import SimpleNamespace

import pytest

from app.services.case_automation_service import CaseAutomationService


@pytest.mark.parametrize("text,reported,filed", [
    ("发现油品，尚未向公安报案，未立案。", False, False),
    ("已报案，已立案。", True, True),
    ("是否报案待核，是否立案不详。", None, None),
    ("未报案，另一份记录称已经报案。", None, None),
    ("已受案，是否立案待核。", None, None),
    ("已报案。暂不清楚是否立案。", True, None),
    ("没报案，未确认立案。", False, None),
    ("现场暂不报案，公安决定不立案。", False, False),
    ("不是未报案，不能说未立案。", None, None),
])
def test_negation_uncertainty_conflict_and_acceptance_are_not_affirmation(text, reported, filed):
    result = CaseAutomationService.structure_case_text(text)
    assert result["case_fields"].get("police_reported") is reported
    assert result["case_fields"].get("case_filed") is filed
    candidates = {item["field"]: item["value"] for item in result["candidates"]}
    assert candidates.get("police_reported") is reported
    assert candidates.get("case_filed") is filed


def test_reference_is_exact_including_original_whitespace_and_unicode():
    text = "  合成资料🙂，在测试1号井附近发现被盗原油0.18吨，尚未报案。 \n"
    result = CaseAutomationService.structure_case_text(text)
    assert result["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    refs = [item for item in result["evidence_anchors"] if item["reference_status"] == "verified"]
    assert refs
    for ref in refs:
        assert text[ref["start"]:ref["end"]] == ref["text"]
        assert ref["source_sha256"] == result["source_sha256"]
    assert any("尚未报案" in ref["text"] for ref in refs if ref["field"] == "police_reported")


def test_missing_model_reference_does_not_cite_first_eighty_characters():
    class FakeModel:
        def invoke(self, _prompt):
            return SimpleNamespace(content=json.dumps({"case_fields": {"location": "模型未提供出处的地点"}}))
    text = "这里没有记录地点，仅描述发现油迹。"
    result = CaseAutomationService.structure_case_text(text, llm=FakeModel())
    ref = next(item for item in result["evidence_anchors"] if item["field"] == "location")
    assert ref["reference_status"] == "unverified"
    assert ref["text"] == "" and ref["start"] is None and ref["end"] is None
    assert result["human_confirmation_required"] is True


def test_model_cannot_turn_negative_into_positive_or_return_secret_error():
    class WrongModel:
        def invoke(self, _prompt):
            return SimpleNamespace(content=json.dumps({"case_fields": {
                "case_filed": True, "police_reported": "true", "description": "已报案已立案。"},
                "candidates": [{"field": "case_filed", "value": True}]}))
    text = "尚未报案，未立案。"
    result = CaseAutomationService.structure_case_text(text, llm=WrongModel())
    assert result["case_fields"]["case_filed"] is False
    assert result["case_fields"]["police_reported"] is False
    assert result["case_fields"]["description"] == text
    assert all(item["value"] is False for item in result["candidates"] if item["field"] in {"case_filed", "police_reported"})

    class FailedModel:
        def invoke(self, _prompt):
            raise RuntimeError("Authorization Bearer SECRET url and raw private prompt")
    failed = CaseAutomationService.structure_case_text(text, llm=FailedModel())
    assert "SECRET" not in str(failed)
    assert failed["model_status"] == "llm_failed"


def test_correct_model_negative_is_not_overridden_by_literal_status_guard():
    class CorrectModel:
        def invoke(self, _prompt):
            return SimpleNamespace(content=json.dumps({"case_fields": {
                "case_filed": False, "police_reported": False}}))

    text = "现场暂不报案，公安决定不立案。"
    result = CaseAutomationService.structure_case_text(text, llm=CorrectModel())
    assert result["case_fields"]["police_reported"] is False
    assert result["case_fields"]["case_filed"] is False
