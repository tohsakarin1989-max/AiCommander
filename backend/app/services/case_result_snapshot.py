"""统一成果内容组装：冻结既有画像与候选，不重新推理、不查询或写入业务表。"""
from __future__ import annotations

import hashlib
import json
from typing import Sequence

from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile


RESULT_SCHEMA_VERSION = "case-result-4.1.0-1"


def _canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def verify_snapshot(snapshot: dict) -> bool:
    """仅验证内容完整性，不替代当前用户权限校验。"""
    try:
        semantics = snapshot["content"].get("semantics") or {}
        if semantics.get("process") is not None:
            from app.services.case_process_contract import validate_process
            validate_process(semantics["process"], semantics["source_snapshot"])
            process_hash = semantics["process"].get("source_hash")
            if process_hash is not None and process_hash != snapshot["content"]["versions"]["case_source_hash"]:
                return False
            if semantics["process"]["source_revision_id"] != snapshot["content"]["versions"]["source_revision_id"]:
                return False
        encoded = _canonical(snapshot["content"])
        return snapshot["content_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def assemble_case_result(
    profile: CaseAnalysisProfile,
    run: CaseAnalysisRun | None,
    hypotheses: Sequence[CaseHypothesis],
) -> dict:
    """调用方必须先按当前权限读取输入，历史读取与导出时也须重新授权。"""
    if not profile.id or not profile.source_hash or not isinstance(profile.payload, dict):
        raise ValueError("invalid_result_profile")
    if profile.payload.get("source_hash") != profile.source_hash:
        raise ValueError("result_profile_hash_mismatch")
    if profile.payload.get("case_id", profile.case_id) != profile.case_id:
        raise ValueError("result_profile_case_mismatch")
    semantics = profile.payload.get("semantics") or {}
    process = semantics.get("process")
    if process is not None:
        from app.services.case_process_contract import validate_process
        validate_process(process, semantics["source_snapshot"])
        if (process["source_revision_id"] != profile.source_revision_id
                or profile.payload.get("source_revision_id") != profile.source_revision_id
                or process["source_hash"] not in (None, profile.source_hash)):
            raise ValueError("result_process_source_revision_mismatch")
    if run is None and hypotheses:
        raise ValueError("result_candidates_without_run")
    if run is not None and (run.case_id != profile.case_id or run.case_profile_id != profile.id):
        raise ValueError("result_input_version_mismatch")
    if run is not None and (not run.map_snapshot_id or not run.algorithm_version):
        raise ValueError("result_missing_analysis_version")
    if len(hypotheses) > 3 or len({item.rank for item in hypotheses}) != len(hypotheses):
        raise ValueError("invalid_result_candidate_ranks")
    candidates = []
    for item in sorted(hypotheses, key=lambda candidate: candidate.rank):
        if run is None or item.case_id != profile.case_id or item.analysis_run_id != run.id:
            raise ValueError("result_candidate_scope_mismatch")
        if not item.evidence_refs or not item.supporting_evidence:
            raise ValueError("result_candidate_missing_evidence")
        if not item.counter_evidence and not item.information_gaps:
            raise ValueError("result_candidate_missing_counter_evidence")
        if not item.boundary or type(item.rank) is not int or item.rank not in {1, 2, 3}:
            raise ValueError("invalid_result_candidate")
        candidates.append({
            "id": item.id, "rank": item.rank, "category": item.hypothesis_type,
            "title": item.title, "claim": item.claim, "region": item.region,
            "score": item.score, "score_kind": "rule_support_not_probability",
            "score_components": item.score_components,
            "evidence_refs": item.evidence_refs, "supporting_evidence": item.supporting_evidence,
            "counter_evidence": item.counter_evidence, "information_gaps": item.information_gaps,
            "boundary": item.boundary, "status": item.status, "is_official_fact": False,
        })
    content = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "case_id": profile.case_id,
        "versions": {
            "case_profile_id": profile.id, "profile_version": profile.profile_version,
            "case_source_hash": profile.source_hash, "profile_schema": profile.schema_version,
            "dictionary_version": profile.dictionary_version,
            "analysis_run_id": run.id if run else None,
            "map_snapshot_id": run.map_snapshot_id if run else None,
            "algorithm_version": run.algorithm_version if run else None,
        },
        "facts_summary": {
            "label": "原始记录摘要，非新增核实结论",
            "recorded_fields": profile.payload.get("standard", {}),
            "evidence_refs": [f"case_profile:{profile.id}"],
        },
        "related_conditions": profile.payload.get("analysis_facts", {}),
        "semantics": profile.payload.get("semantics"),
        "candidates": candidates,
        "information_gaps": {
            "profile": profile.payload.get("critical_gaps", []),
            "analysis": run.information_gaps if run else ["尚无与该画像版本匹配的地图融合研判成果。"],
        },
        "analysis_status": run.status if run else "not_generated",
        "boundary": [
            "仅汇总已生成的画像与候选，不再次调用模型生成事实。",
            "候选解释、信息缺口和原文表述不自动转为正式案件事实。",
            "规则支持度不是经校准的概率；本成果不自动形成执行任务。",
            "历史成果及导出仍须重新核对当前案件与每项证据访问权限。",
        ],
    }
    # Old snapshots without process keep exactly their historical hash contract.
    if profile.payload.get("analysis_applicability"):
        from app.services.case_analysis_applicability import allows, reason
        content["analysis_applicability"] = profile.payload["analysis_applicability"]
        content["recorded_locations"] = profile.payload.get("recorded_locations", [])
        content["recorded_handling"] = profile.payload.get("recorded_handling", {})
        if run is None and not allows(profile.payload, "source_inference"):
            content["analysis_status"] = next(item["status"] for item in
                content["analysis_applicability"]["entries"] if item["kind"] == "source_inference")
            content["information_gaps"]["analysis"] = [reason(profile.payload, "source_inference")]
    if process is not None:
        content["versions"]["source_revision_id"] = profile.source_revision_id
    encoded = _canonical(content)
    return {"content_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "content": json.loads(encoded)}
