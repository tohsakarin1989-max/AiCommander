import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_document import build_case_result_document, load_case_result_document
from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import assemble_case_result
from test_case_result_snapshot import inputs
from test_case_results import db_session, prepare, result_data  # noqa: F401


def document_input():
    profile, run, candidate = inputs()
    candidate.supporting_evidence = [f"支持证据{i}" for i in range(12)]
    candidate.counter_evidence = ["相反条件"]
    profile.payload["semantics"]["assertions"][0]["reference"] = {
        "field": "description", "start": 0, "end": 5, "quote": "未发现罐车",
    }
    return {"id": "frozen-result-1", "created_at": "2026-09-11T00:00:00+00:00",
            **assemble_case_result(profile, run, [candidate])}


def test_document_preserves_all_evidence_negation_versions_and_does_not_mutate_input():
    result = document_input()
    original = copy.deepcopy(result)
    document = build_case_result_document(result)
    assert build_case_result_document(result) == document
    assert original == result
    text = "\n".join(block.text for block in document.blocks)
    assert "原文否定：罐车" in text
    assert "description · 字符 1 至 5：未发现罐车" in text
    for index in range(12):
        assert f"支持证据{index}" in text
    assert "相反条件" in text and "尚未核实" in text
    assert "不是准确概率" in text
    version = next(block for block in document.blocks if block.text == "输入版本")
    assert ("case_profile_id", "profile-1") in version.rows
    assert ("map_snapshot_id", "map-1") in version.rows
    assert document.content_sha256 == result["content_sha256"]


def test_empty_analysis_remains_empty_and_no_fabricated_map():
    profile, _, _ = inputs()
    result = {"id": "base-only", **assemble_case_result(profile, None, [])}
    document = build_case_result_document(result)
    text = "\n".join(block.text for block in document.blocks)
    assert "尚无可展示候选" in text and "尚无与该画像版本匹配" in text
    map_input = json.loads(next(block.text for block in document.blocks if block.kind == "map"))
    assert map_input["map_snapshot_id"] is None
    assert map_input["candidates"] == []


def test_document_is_deeply_immutable_and_tampered_input_is_rejected():
    result = document_input()
    document = build_case_result_document(result)
    with pytest.raises(FrozenInstanceError):
        document.blocks[0].text = "被修改"
    result["content"]["facts_summary"]["recorded_fields"]["location"] = "后来变动"
    assert "后来变动" not in repr(document)
    with pytest.raises(ValueError, match="invalid_case_result_document_input"):
        build_case_result_document(result)


def test_document_rejects_unknown_schema_even_with_recomputed_hash():
    import hashlib

    result = document_input()
    result["content"]["schema_version"] = "future-version"
    encoded = json.dumps(result["content"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["content_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    with pytest.raises(ValueError, match="invalid_case_result_document_input"):
        build_case_result_document(result)


def test_document_load_rechecks_evidence_permission_each_time(db_session, result_data):
    prepare(db_session)
    result_data[2].evidence_refs = ["case:2"]
    db_session.info["authorized_area_ids"] = (1, 2)
    db_session.commit()
    result, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    document = load_case_result_document(db_session, result["id"])
    assert document.result_id == result["id"]
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError):
        load_case_result_document(db_session, result["id"])
