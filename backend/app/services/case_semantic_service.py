"""本地词项语义基线：只整理有原文出处的表述，不生成案情事实。"""
from __future__ import annotations

from typing import Any, Mapping

from app.services.case_semantic_evidence import (
    TextReference, freeze_sources, grounded_assertion, snapshot_payload,
)
from app.services.case_semantic_time import extract_time_intervals
from app.services.case_semantic_structured import extract_structured_sources
from app.services.case_event_fragments import build_event_fragments
from app.services.case_process_service import build_process
from app.services.case_semantic_mentions import (
    CLAUSE, NEGATED, UNCERTAIN, extract_term_assertions,
)


SEMANTIC_RULE_VERSION = "local-events-6.3-1"
TEXT_FIELDS = (
    "description", "location", "modus_operandi", "facility_type", "oil_type",
    "upstream_source", "downstream_destination",
)
# 只做显式同义词归一，不把“原油”“凝析油”等不同业务属性互相合并。
TERMS = {
    "vehicle": {"油罐车": "罐车", "罐车": "罐车", "货车": "货车", "面包车": "面包车"},
    "oil": {"原油": "原油", "凝析油": "凝析油", "柴油": "柴油"},
    "facility": {"采油井": "油井", "油井": "油井", "井口": "井口", "输油管线": "输油管线", "阀门": "阀门"},
    "tool": {"抽油泵": "抽油泵", "软管": "软管", "胶管": "软管", "油桶": "油桶"},
    "method": {"打孔盗油": "打孔盗油", "打眼盗油": "打孔盗油", "车辆转运": "车辆转运"},
    "place_condition": {"井场": "井场", "村屯": "村屯", "河边": "临水", "河岸": "临水", "路口": "路口"},
    "time_condition": {"夜间": "夜间", "夜里": "夜间", "凌晨": "凌晨", "白天": "白天"},
}


def build_semantic_profile(
    values: Mapping[str, str | None], *, structured: dict[str, Any] | None = None,
    source_revision_id: int | None = None, source_hash: str | None = None,
    source_payload: dict[str, Any] | None = None,
) -> dict:
    sources = freeze_sources(values)
    mentions = extract_term_assertions(values, TERMS)
    assertions = mentions["assertions"]
    gaps = mentions["information_gaps"]
    time_intervals = []
    for source in sources:
        intervals, time_gaps = extract_time_intervals(source)
        time_intervals.extend(intervals)
        gaps.extend(time_gaps)
    for field in ("upstream_source", "downstream_destination"):
        value = values.get(field)
        missing = not value or value.strip() in {"", "无", "暂无", "未知", "不详", "待查", "未查明"}
        if missing or UNCERTAIN.search(value):
            gaps.append({"code": "lineage_not_established", "field": field})
        if not missing:
            if len(assertions) >= 200:
                gap = {"code": "extraction_limit", "field": field}
                if gap not in gaps:
                    gaps.append(gap)
                continue
            source = next(item for item in sources if item.field == field)
            ref = TextReference(field, source.sha256, 0, len(source.text), source.text)
            assertions.append(grounded_assertion(
                source, ref, category="upstream_clue" if field == "upstream_source" else "downstream_clue",
                normalized_value=source.text.strip(),
                kind="uncertain" if UNCERTAIN.search(value) or NEGATED.search(value) else "stated",
            ))
    structured_result = extract_structured_sources(structured or {})
    gaps.extend(structured_result["information_gaps"])
    grouped: dict[tuple[str, str], set[str]] = {}
    for item in assertions:
        grouped.setdefault((item["category"], item["value"]), set()).add(item["kind"])
    conflicts = [
        {"category": category, "value": value, "status": "needs_context_review"}
        for (category, value), kinds in sorted(grouped.items())
        if {"stated", "negated"} <= kinds
    ]
    fragments = build_event_fragments(sources, assertions, time_intervals, gaps)
    process = build_process(sources, assertions, time_intervals, fragments, gaps,
                            source_revision_id=source_revision_id, source_hash=source_hash,
                            source_payload=source_payload)
    return {
        "rule_version": SEMANTIC_RULE_VERSION, "method": "local_dictionary_rules",
        "source_snapshot": snapshot_payload(sources), "assertions": assertions,
        "time_intervals": time_intervals,
        "structured_sources": structured_result,
        "potential_conflicts": conflicts, "information_gaps": gaps,
        "event_fragments": fragments, "process": process,
        "boundary": [
            "词项及句内标记仅整理原文表述，不代表事实已核实。",
            "本地规则尚不能完整解析复杂否定、指代、时间区间及上下游关系。",
            "跨句肯定和否定并存仅提示结合时间与上下文核验，不自动认定矛盾。",
            "不生成坐标、嫌疑人结论或正式案件链条；原文不外发。",
        ],
    }
