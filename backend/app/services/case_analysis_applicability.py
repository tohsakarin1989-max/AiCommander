"""Versioned input suitability, not business completion or dependency health.

Only explicitly recorded location roles may supply an incident endpoint. Legacy
coordinates remain source data; their presence never establishes a theft site.
"""
from __future__ import annotations

from math import isfinite

VERSION = "case-applicability-8.0-1"
LABELS = {
    "base": "已知资料整理", "history": "历史条件参考", "statistics": "时间统计",
    "spatial_background": "地点与周边背景", "source_inference": "来源候选分析",
    "road_analysis": "道路条件比较",
}
STATUS_LABELS = {
    "applicable": "资料适用", "insufficient_data": "资料暂不足", "not_applicable": "本记录不适用",
}


def exact_point(location):
    if location.get("precision") != "exact":
        return None
    geometry = location.get("geometry") or {}
    values = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(values, list) or len(values) != 2:
        return None
    if any(type(value) not in (int, float) or not isfinite(value) for value in values):
        return None
    lon, lat = values
    return {"longitude": lon, "latitude": lat} if -180 <= lon <= 180 and -90 <= lat <= 90 else None


def assess(source: dict, semantics: dict, *, source_revision_id=None) -> dict:
    """Pure projection of source records and grounded, deterministic assertions."""
    case = source.get("case") or {}
    locations = source.get("locations") or []
    incidents = [row for row in locations if row.get("role") == "incident"]
    incident = exact_point(incidents[0]) if len(incidents) == 1 else None
    discovery_only = bool(locations) and not incidents and any(
        row.get("role") == "discovery" for row in locations)
    claims = [item for item in semantics.get("assertions", []) if item.get("kind") == "stated"
              and (item.get("category") == "upstream_clue"
                   or (item.get("category") == "method" and item.get("value") == "打孔盗油"))]
    # A simultaneous negated/uncertain assertion cannot silently become a
    # positive trigger just because another clause contains the same word.
    conflicts = {(item.get("category"), item.get("value")) for item in semantics.get("assertions", [])
                 if item.get("kind") in ("negated", "uncertain")}
    claims = [item for item in claims if (item.get("category"), item.get("value")) not in conflicts]
    has_history = any(case.get(key) for key in ("description", "modus_operandi", "case_type"))
    precision = case.get("time_precision")
    has_time = bool(case.get("discovered_at") or
                    (precision == "exact" and case.get("occurred_time")) or
                    (precision == "interval" and case.get("occurred_from") and case.get("occurred_to")))
    has_place = bool(case.get("location") or locations)
    source_ok = incident is not None and bool(claims)
    refs = [f"case_revision:{source_revision_id}"] if source_revision_id is not None else []
    entries = []

    def entry(kind, status, reason):
        entries.append({"kind": kind, "label": LABELS[kind], "status": status,
                        "reason": reason, "evidence_refs": refs,
                        "assessment_scope": "input_data_only"})

    entry("base", "applicable", "可整理已记录资料；未知不妨碍保存，不代表案件已办结。")
    entry("history", "applicable" if has_history else "insufficient_data",
          "按授权检索已知条件，不推定正式案件关系。" if has_history else "尚无可供历史对照的描述或类型，保留已知字段。")
    entry("statistics", "applicable" if has_time else "insufficient_data",
          "仅进入相应已知时间口径，不以录入时间替代发生或发现时间。" if has_time else "发现和发生时间尚未明确，统计时单列未知。")
    entry("spatial_background", "applicable" if has_place else "insufficient_data",
          "仅提供记录地点的背景；附近设施不等于涉案设施。" if has_place else "地点未明确，暂不定位；不补造坐标。")
    entry("source_inference", "applicable" if source_ok else "not_applicable" if discovery_only else "insufficient_data",
          "已有明确案发点及原文来源或盗取手法线索，仅可形成待核参考。" if source_ok else
          "本记录仅明确发现或查获地点，不据此寻找盗取来源。" if discovery_only else
          "缺少明确案发点及来源或盗取手法依据，保留背景资料，不要求补齐侦查信息。")
    entry("road_analysis", "applicable" if source_ok else "not_applicable",
          "来源问题有适用起点；实际执行仍须核验车型、入口、路网及当前许可。" if source_ok else
          "当前没有具备依据和适用端点的道路问题，不自动启动道路任务。")
    return {"version": VERSION, "entries": entries, "incident_point": incident,
            "source_basis": [{"category": item["category"], "value": item["value"],
                              "reference": item.get("reference")} for item in claims],
            "boundary": "仅判断资料用途，不确认案件事实，不代表本单位处置或公安办理状态。"}


def allows(payload: dict, kind: str) -> bool:
    assessment = payload.get("analysis_applicability") or {}
    return assessment.get("version") == VERSION and any(
        item.get("kind") == kind and item.get("status") == "applicable"
        for item in assessment.get("entries", []))


def reason(payload: dict, kind: str) -> str:
    assessment = payload.get("analysis_applicability") or {}
    return next((item["reason"] for item in assessment.get("entries", []) if item.get("kind") == kind),
                "旧成果未声明分析适用条件，不自动继续深入分析；可查看历史资料。")
