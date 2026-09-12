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
    assert "案情描述（description） · 字符 1 至 5：未发现罐车" in text
    for index in range(12):
        assert f"支持证据{index}" in text
    assert "相反条件" in text and "尚未核实" in text
    assert "不是准确概率" in text
    version = next(block for block in document.blocks if block.text == "输入版本")
    assert ("画像编号", "profile-1") in version.rows
    assert ("地图快照编号", "map-1") in version.rows
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


def test_model_excerpts_export_same_quotes_status_and_versions_without_fact_promotion():
    from app.services.case_semantic_service import build_semantic_profile
    profile, _, _ = inputs()
    semantics = build_semantic_profile({"description": "未发现罐车"})
    profile.payload["semantics"] = semantics
    semantics["model_extraction"] = {"status": "partial", "version": "test-model-v1",
        "items": semantics["assertions"], "boundary": "模型提取候选，不是正式事实。"}
    original = copy.deepcopy(profile.payload)
    document = build_case_result_document({"id": "model-excerpts", **assemble_case_result(profile, None, [])})
    text = "\n".join(block.text for block in document.blocks)
    assert "内网模型提取参考 · 部分结果" in text
    assert "未发现罐车" in text and "test-model-v1" in text
    assert "模型判断待核对" in text and "未采用内容保留未知" in text
    assert original == profile.payload


def test_map_input_uses_frozen_analysis_coordinates_and_candidate_legend():
    profile, run, candidate = inputs()
    profile.payload["analysis_facts"] = {"latitude": 46.6, "longitude": 125.1}
    profile.payload["standard"]["latitude"] = 0  # 错误来源不能覆盖分析层冻结坐标。
    result = {"id": "mapped-result", **assemble_case_result(profile, run, [candidate])}
    document = build_case_result_document(result)
    map_input = json.loads(next(block.text for block in document.blocks if block.kind == "map"))
    assert map_input["case_marker"] == {"case_id": 1, "latitude": 46.6, "longitude": 125.1, "title": "合成地点"}
    assert map_input["candidates"][0]["title"] == candidate.title
    assert map_input["candidates"][0]["category"] == candidate.hypothesis_type


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


def test_real_semantics_export_has_readable_precision_paths_negation_and_gaps():
    from app.services.case_semantic_service import build_semantic_profile

    profile, _, _ = inputs()
    source = "2026年9月10日22时至2026年9月11日2时30分。发现罐车。后来未见罐车。昨晚信息需核对。"
    profile.payload["semantics"] = build_semantic_profile({"description": source}, structured={
        "vehicle_info": [{"是否核实": False, "数量": 0, "说明": ""}],
        "case_vehicles": [{"vehicle_type": "货车"}],
    })
    document = build_case_result_document({"id": "real-semantics", **assemble_case_result(profile, None, [])})
    rows = [row for block in document.blocks for row in block.rows]
    text = "\n".join(block.text for block in document.blocks)
    assert ("起始", "2026-09-10 22时（精度：小时）") in rows
    assert ("结束", "2026-09-11 02:30（精度：分钟）") in rows
    assert ("时区", "未注明，不自动转换") in rows
    assert ("字段路径", "第1项 / 是否核实") in rows
    assert ("来源字段", "关联车辆记录") in rows
    assert ("字段路径", "第1项 / vehicle_type") in rows
    assert ("记录值", "货车") in rows
    assert ("记录值", "否") in rows and ("记录值", "0") in rows
    assert "表述冲突待核：罐车" in text
    assert "相对时间缺少日期依据" in text
    assert "原文否定：罐车" in text and "原文陈述：罐车" in text
    assert all(not value.startswith('{"') for _, value in rows)
    # 全部时间/断言引用仍可回到冻结的原文片段。
    semantics = profile.payload["semantics"]
    for item in [*semantics["assertions"], *semantics["time_intervals"]]:
        assert item["reference"]["quote"] in text


def test_unknown_semantic_gap_remains_visible_and_duplicate_gap_is_not_repeated():
    profile, _, _ = inputs()
    gap = {"code": "future_gap", "field": "vehicle_info"}
    profile.payload["semantics"] = {
        "assertions": [], "information_gaps": [gap],
        "structured_sources": {"entries": [], "information_gaps": [gap]},
    }
    document = build_case_result_document({"id": "unknown-gap", **assemble_case_result(profile, None, [])})
    messages = [block.text for block in document.blocks if "future_gap" in block.text]
    assert len(messages) == 1 and "本项信息待核对（车辆信息）" in messages[0]


def test_event_fragments_share_frozen_source_and_polarity_with_page():
    from app.services.case_semantic_service import build_semantic_profile
    profile, _, _ = inputs()
    profile.payload["semantics"] = build_semantic_profile({"description": "未转运原油。次日在村屯存放。"})
    frozen = {"id": "event-fragments", **assemble_case_result(profile, None, [])}
    original = copy.deepcopy(frozen)
    document = build_case_result_document(frozen)
    text = "\n".join(block.text for block in document.blocks)
    assert document.schema == "case-result-document-5.1.0-1"
    assert "转运（原文否定）" in text
    assert "共现不证明" in text and "深层模型理解未启用" in text
    for item in profile.payload["semantics"]["event_fragments"]["items"]:
        assert item["reference"]["quote"] in text
    assert "不作为新增必填要求" in text
    assert frozen == original
