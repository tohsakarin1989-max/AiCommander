"""本地词项语义基线：只整理有原文出处的表述，不生成案情事实。"""
from __future__ import annotations

import re
from typing import Any, Mapping

from app.services.case_semantic_evidence import (
    TextReference, freeze_sources, grounded_assertion, snapshot_payload,
)
from app.services.case_semantic_time import extract_time_intervals
from app.services.case_semantic_structured import extract_structured_sources
from app.services.case_event_fragments import build_event_fragments


SEMANTIC_RULE_VERSION = "local-events-5.1.0-1"
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
UNCERTAIN = re.compile(
    r"可能|疑似|不详|不确定|不能确定|无法确定|不能排除|不排除|未排除|并非没有|不是没有|"
    r"没有证据|未证实|否认|假设|如果|是否|\?|？|忽略|指令|提示词|system|assistant|[“”\"「」]",
    re.IGNORECASE,
)
NEGATED = re.compile(r"未发现|未见|未查获|未使用|未携带|没有|不存在|不是|并非")
CLAUSE = re.compile(r"[^，,。；;！!\n]+")


def _mention_kind(text: str, start: int, end: int) -> str:
    if UNCERTAIN.search(text):
        return "uncertain"
    if not NEGATED.search(text):
        return "stated"
    before, after = text[:start].strip(), text[end:].strip()
    # 仅接受直接否定该词项的简式；“原油没有丢失”是否定丢失，不能转成否定原油。
    direct_prefix = re.search(r"(?:未发现|未见|未查获|未使用|未携带|没有(?:发现)?|不存在|不是|并非)$", before)
    if (direct_prefix and not after) or (after in {"未见", "未发现", "不存在"} and not before):
        return "negated"
    return "uncertain"


def build_semantic_profile(
    values: Mapping[str, str | None], *, structured: dict[str, Any] | None = None,
) -> dict:
    sources = freeze_sources(values)
    assertions = []
    gaps = []
    time_intervals = []
    for source in sources:
        intervals, time_gaps = extract_time_intervals(source)
        time_intervals.extend(intervals)
        gaps.extend(time_gaps)
        for clause in CLAUSE.finditer(source.text):
            fragment = clause.group()
            # 转折后不继承前半句的否定作用范围；保留原文字偏移。
            parts = re.finditer(r"(?:(?!但是|但|然而|不过).)+", fragment)
            for part in parts:
                start = clause.start() + part.start()
                text = part.group()
                for category, terms in TERMS.items():
                    pattern = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
                    for match in re.finditer(pattern, text):
                        if len(assertions) >= 200:
                            gaps.append({"code": "extraction_limit", "field": source.field})
                            break
                        reference = TextReference(source.field, source.sha256, start, start + len(text), text)
                        assertion = grounded_assertion(
                            source, reference, category=category,
                            normalized_value=terms[match.group()],
                            kind=_mention_kind(text, match.start(), match.end()),
                        )
                        assertion["mention_span"] = [start + match.start(), start + match.end()]
                        assertions.append(assertion)
    for field in ("upstream_source", "downstream_destination"):
        value = values.get(field)
        missing = not value or value.strip() in {"", "无", "暂无", "未知", "不详", "待查", "未查明"}
        if missing or UNCERTAIN.search(value):
            gaps.append({"code": "lineage_not_established", "field": field})
        if not missing:
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
    return {
        "rule_version": SEMANTIC_RULE_VERSION, "method": "local_dictionary_rules",
        "source_snapshot": snapshot_payload(sources), "assertions": assertions,
        "time_intervals": time_intervals,
        "structured_sources": structured_result,
        "potential_conflicts": conflicts, "information_gaps": gaps,
        "event_fragments": build_event_fragments(sources, assertions, time_intervals, gaps),
        "boundary": [
            "词项及句内标记仅整理原文表述，不代表事实已核实。",
            "本地规则尚不能完整解析复杂否定、指代、时间区间及上下游关系。",
            "跨句肯定和否定并存仅提示结合时间与上下文核验，不自动认定矛盾。",
            "不生成坐标、嫌疑人结论或正式案件链条；原文不外发。",
        ],
    }
