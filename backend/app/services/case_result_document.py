"""Word/PDF共用内容模型；仅排布冻结输入，不查询业务事实或执行模型。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal

from sqlalchemy.orm import Session

from app.services.case_result_service import CaseResultService
from app.services.case_result_map import frozen_result_map_input
from app.services.case_result_snapshot import RESULT_SCHEMA_VERSION, verify_snapshot
from app.services.case_result_composition import COMPOSITION_SCHEMA_VERSION


DOCUMENT_SCHEMA = "case-result-document-5.1.0-1"
FIELD_LABELS = {
    "occurred_time": "案发时间（存储值）", "location": "地点", "case_type": "案件类型",
    "occurred_from": "发生时间范围起点", "occurred_to": "发生时间范围终点",
    "time_precision": "发生时间精度", "time_expression": "原始时间表达",
    "time_timezone": "原始时间表达时区", "discovered_at": "发现时间",
    "oil_type": "油品", "oil_nature": "油品性质", "facility_type": "设施类型",
    "modus_operandi": "作案手法", "report_unit": "报案单位", "source_type": "案件来源",
    "upstream_source": "来源线索", "downstream_destination": "去向线索",
    "water_cut": "含水率（记录值）", "oil_volume": "涉油数量（记录值）",
    "oil_volume_unit": "涉油数量单位（未知不换算）", "oil_measurements": "分阶段计量记录",
    "oil_value": "涉油价值（记录值）", "evidence_count": "证据记录数",
    "vehicle_count": "车辆记录数", "person_count": "人员记录数",
    "description": "案情描述", "vehicle_info": "车辆信息", "case_vehicles": "关联车辆记录", "involved_items": "涉案物品",
    "case_profile_id": "画像编号", "profile_version": "画像版本", "case_source_hash": "源案件摘要",
    "profile_schema": "画像结构版本", "dictionary_version": "字典版本", "analysis_run_id": "分析运行编号",
    "map_snapshot_id": "地图快照编号", "algorithm_version": "算法版本",
}
ASSERTION_LABELS = {"stated": "原文陈述", "negated": "原文否定", "uncertain": "待核表述", "inferred": "推断"}
GAP_LABELS = {
    "lineage_not_established": "来源或去向尚未明确", "invalid_time_interval": "起止时间需核对",
    "relative_time_requires_anchor": "相对时间缺少日期依据", "time_expression_requires_context": "时刻缺少日期或上下文",
    "extraction_limit": "文本提取未覆盖全部内容", "invalid_structured_source": "结构化资料格式需核对",
    "structured_source_too_large": "资料过大，尚未完成结构化提取",
    "structured_extraction_limit": "结构化资料仅提取了部分内容",
}


@dataclass(frozen=True)
class DocumentBlock:
    kind: Literal["heading", "paragraph", "table", "source", "map"]
    text: str
    rows: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CaseResultDocument:
    schema: str
    result_id: str
    content_sha256: str
    blocks: tuple[DocumentBlock, ...]
    road_artifact_id: str | None = None
    road_artifact_sha256: str | None = None


def _text(value: object) -> str:
    if value is None or value == "":
        return "未记录"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _fields(values: dict) -> tuple[tuple[str, str], ...]:
    # 未认识的新字段仍保留字段名和值，不悄悄丢弃版本化证据。
    return tuple((FIELD_LABELS.get(key, key), _text(value)) for key, value in sorted(values.items()))


def _source(reference: dict) -> DocumentBlock:
    field = reference["field"]
    label = FIELD_LABELS.get(field, field)
    return DocumentBlock("source", f'{label}（{field}） · 字符 {reference["start"] + 1} 至 {reference["end"]}：{reference["quote"]}')


def _time_label(value: str, precision: str) -> str:
    if precision == "hour" and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00", value):
        return value[:13].replace("T", " ") + "时（精度：小时）"
    label = {"minute": "分钟", "second": "秒"}.get(precision, "待核对")
    return f'{value.replace("T", " ")}（精度：{label}）'


def _semantic_details(semantics: dict) -> list[DocumentBlock]:
    blocks = []
    if semantics.get("process"):
        from app.services.case_process_document import process_blocks
        blocks.extend(process_blocks(semantics["process"]))
        if not semantics.get("model_extraction"):
            blocks.append(DocumentBlock("paragraph", "深层模型理解未启用，当前使用本地规则。"))
    model = semantics.get("model_extraction")
    if model:
        state = {"ready": "已返回", "partial": "部分结果", "unavailable": "暂不可用", "not_enabled": "未启用"}.get(model["status"], "状态待核")
        blocks.append(DocumentBlock("heading", f"内网模型提取参考 · {state}"))
        blocks.append(DocumentBlock("paragraph", model["boundary"]))
        blocks.append(DocumentBlock("paragraph", "仅展示选取片段，不代表完整覆盖原文；规则画像继续可用。"))
        if model["status"] == "partial":
            blocks.append(DocumentBlock("paragraph", "部分引用不通过校验或达到处理上限，未采用内容保留未知。"))
        for item in model["items"]:
            blocks.append(DocumentBlock("paragraph", f'{item["value"]}（{ASSERTION_LABELS.get(item["kind"], "待核表述")}；模型判断待核对）'))
            blocks.append(_source(item["reference"]))
        blocks.append(DocumentBlock("paragraph", f'模型提取版本：{model["version"]}'))
    events = semantics.get("event_fragments")
    if events is not None and not semantics.get("process"):
        blocks.append(DocumentBlock("heading", f'事件片段 {len(events["items"])} 项'))
        blocks.append(DocumentBlock("paragraph", events["boundary"]))
        if not model and events.get("deep_model_status") != "enabled":
            blocks.append(DocumentBlock("paragraph", "深层模型理解未启用，当前使用本地规则。"))
        if events["coverage"]["state"] == "partial":
            blocks.append(DocumentBlock("paragraph", "片段或词项提取不完整，请结合原文查看未覆盖内容。"))
        dimensions = {"action": "明确动作", "time": "时间条件", "facility": "设施", "oil": "油品",
                      "place": "地点条件", "upstream": "来源", "downstream": "去向"}
        assertions = semantics.get("assertions", [])
        for index, fragment in enumerate(events["items"], 1):
            actions = "；".join(f'{action["value"]}（{ASSERTION_LABELS.get(action["kind"], "类型待核")}）'
                               for action in fragment["actions"]) or "动作尚未明确"
            blocks.append(DocumentBlock("paragraph", f"片段 {index}：{actions}"))
            conditions = [assertions[item] for item in fragment["assertion_indices"]
                          if type(item) is int and 0 <= item < len(assertions)]
            if conditions:
                labels = "、".join(f'{item["value"]}（{ASSERTION_LABELS.get(item["kind"], "类型待核")}）'
                                  for item in conditions)
                blocks.append(DocumentBlock("paragraph", f"句内条件：{labels}"))
            if fragment["missing_dimensions"]:
                missing = "、".join(dimensions.get(item, "待核条件") for item in fragment["missing_dimensions"])
                blocks.append(DocumentBlock("paragraph", f"本片段尚未明确：{missing}。不作为新增必填要求。"))
            blocks.append(_source(fragment["reference"]))
    for index, interval in enumerate(semantics.get("time_intervals", []), 1):
        blocks.append(DocumentBlock("table", f"时间表达 {index}（不是正式案发时间）", (
            ("起始", _time_label(interval["start"], interval["start_precision"])),
            ("结束", _time_label(interval["end"], interval["end_precision"])),
            ("时区", interval.get("timezone") or "未注明，不自动转换"),
            ("状态", "原文表达待核验，不替代正式案发时间"),
        )))
        blocks.append(_source(interval["reference"]))
    structured = semantics.get("structured_sources") or {}
    entries = structured.get("entries", [])
    if entries:
        blocks.append(DocumentBlock("heading", "结构化资料与字段路径"))
    for index, entry in enumerate(entries, 1):
        ref = entry["reference"]
        path = " / ".join(f"第{part + 1}项" if type(part) is int else str(part) for part in ref["path"]) or "字段值"
        value = ("是" if ref["value"] else "否") if type(ref["value"]) is bool else _text(ref["value"])
        blocks.append(DocumentBlock("table", f"结构化记录 {index}", (
            ("来源字段", FIELD_LABELS.get(ref["field"], ref["field"])), ("字段路径", path),
            ("记录值", value), ("源数据摘要", ref["source_sha256"]),
        )))
    for conflict in semantics.get("potential_conflicts", []):
        blocks.append(DocumentBlock("paragraph", f'表述冲突待核：{conflict["value"]}。需结合时间和上下文核对，不自动选择结论。'))
    # 合并结构化提取和语义层的缺口；完全相同的缺口只展示一次。
    seen = set()
    for gap in [*semantics.get("information_gaps", []), *structured.get("information_gaps", [])]:
        identity = json.dumps(gap, sort_keys=True, ensure_ascii=False)
        if identity in seen:
            continue
        seen.add(identity)
        label = GAP_LABELS.get(gap["code"], "本项信息待核对")
        field = gap.get("field")
        if field:
            label += f'（{FIELD_LABELS.get(field, field)}）'
        blocks.append(DocumentBlock("paragraph", f'提取限制：{label}；记录代码：{gap["code"]}'))
        if gap.get("reference"):
            blocks.append(_source(gap["reference"]))
    return blocks


def build_case_result_document(result: dict) -> CaseResultDocument:
    """纯转换；调用者须先授权。hash校验只证明内容一致，不证明可向用户交付。"""
    if not verify_snapshot(result) or result["content"].get("schema_version") not in {RESULT_SCHEMA_VERSION, COMPOSITION_SCHEMA_VERSION}:
        raise ValueError("invalid_case_result_document_input")
    content = result["content"]
    created_at = result.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    blocks = [
        DocumentBlock("heading", "案件统一研判成果"),
        DocumentBlock("paragraph", "原始记录、候选解释与信息缺口分开呈现；供人工判断，不是新增核实结论。"),
        DocumentBlock("table", "成果标识", (("成果编号", result["id"]),
            ("生成时间（保留原时区）", _text(created_at)), ("内容摘要", result["content_sha256"]))),
        DocumentBlock("heading", "事实摘要与关联条件"),
        DocumentBlock("paragraph", content["facts_summary"]["label"]),
        DocumentBlock("table", "原始记录摘要", _fields(content["facts_summary"]["recorded_fields"])),
        DocumentBlock("table", "关联条件", _fields(content["related_conditions"])),
        DocumentBlock("paragraph", "存储值未注明时区时，不与原文时刻直接比较或自动换算。"),
    ]
    for ref in content["facts_summary"]["evidence_refs"]:
        blocks.append(DocumentBlock("source", ref))
    applicability = content.get("analysis_applicability")
    if applicability:
        from app.services.case_analysis_applicability import STATUS_LABELS
        blocks.append(DocumentBlock("heading", "资料适用范围与分析状态"))
        blocks.append(DocumentBlock("paragraph", applicability["boundary"]))
        for item in applicability["entries"]:
            blocks.append(DocumentBlock("paragraph", f"{item['label']}：{STATUS_LABELS.get(item['status'], '待核对')}。{item['reason']}"))
            blocks.extend(DocumentBlock("source", ref) for ref in item.get("evidence_refs", []))
        if content.get("recorded_locations"):
            blocks.append(DocumentBlock("table", "已记录地点角色", tuple(
                ({"incident": "案发", "discovery": "发现/查获", "mentioned": "原文提及", "custody": "保管", "source_candidate": "来源线索"}.get(row.get("role"), "角色未明"),
                 f"{row.get('description') or '未记录描述'}；位置精度：{row.get('precision') or '未知'}")
                for row in content["recorded_locations"])))
        handling = content.get("recorded_handling") or {}
        if handling:
            blocks.append(DocumentBlock("heading", "本单位处置及已知反馈"))
            for key, label in (("person_handling", "人员处理"), ("vehicle_handling", "车辆处理"), ("oil_handling", "油品处理")):
                blocks.append(DocumentBlock("paragraph", f"{label}：{_text(handling.get(key))}"))
            for field, item in handling.get("police_feedback", {}).items():
                value = ("是" if item.get("value") else "否") if item.get("state") == "known" else (
                    "历史值来源未确认" if item.get("state") == "legacy_unverified" else "未知/未获反馈")
                blocks.append(DocumentBlock("paragraph", f"{'是否报案' if field == 'police_reported' else '是否立案'}：{value}"))
            blocks.append(DocumentBlock("paragraph", handling["boundary"]))
    if not content.get("composition") and content["candidates"]:
        blocks.append(DocumentBlock("paragraph", "本版本为基础空间成果，未绑定当前道路组合；空间接近不表示道路可达，候选仅供历史参考。"))
    blocks.append(DocumentBlock("heading", "关键缺项"))
    for gap in content["information_gaps"]["profile"]:
        blocks.append(DocumentBlock("paragraph", f'{gap["label"]}：{gap.get("reason") or "待补充核对"}'))
    if not content["information_gaps"]["profile"]:
        blocks.append(DocumentBlock("paragraph", "当前成果未标记关键缺项，不等于全部信息已完整核实。"))
    blocks.append(DocumentBlock("heading", "待核验候选"))
    if content.get("composition"):
        reference = content["composition"]
        blocks.append(DocumentBlock("table", "当前组合的冻结来源", (
            ("基础成果", reference["base_result_id"]), ("道路附件", reference["road_artifact_id"]),
            ("基础成果摘要", reference["base_content_sha256"]), ("道路附件摘要", reference["road_content_sha256"]),
            ("候选来源", "道路前置设施比较；不混用原空间候选评分"),
            ("道路条件时刻", content["road_versions"]["analysis_at"]),
            ("路网版本", content["road_versions"]["network_id"]),
            ("路网摘要", content["road_versions"]["graph_sha256"]),
            ("通行规则版本", str(content["road_versions"]["policy_revision"])),
            ("车型假设", _text(content["road_versions"]["vehicle"])),
            ("算法与检索版本", _text(content.get("road_algorithm_versions"))),
        )))
        coverage = content["road_coverage"]
        blocks.append(DocumentBlock("paragraph", f"授权设施召回 {coverage['recalled']} 个，完成比较 {coverage['compared']} 个；仅展示前三项，不代表全域最优。"))
        if content["road_unresolved"]:
            road_states = {"entrance_unknown": "入口或连接待核", "restricted": "通行受限",
                "permission_unknown": "许可资料不足", "no_path_found": "未取得道路路径",
                "calculation_failed": "计算失败", "not_calculated": "尚未计算", "network_missing": "路网缺失"}
            blocks.append(DocumentBlock("table", "尚未形成比较的设施（不按低风险处理）", tuple(
                (str(item["asset_id"]), road_states.get(item["state"], "资料待核"))
                for item in content["road_unresolved"])))
    if not content["candidates"]:
        blocks.append(DocumentBlock("paragraph", "尚无可展示候选，不代表不存在相关线索。"))
    if content.get("road_condition_comparison"):
        from app.services.case_process_document import condition_blocks
        blocks.extend(condition_blocks(content["road_condition_comparison"], content.get("road_ranking_changes")))
    for candidate in content["candidates"]:
        blocks.extend([
            DocumentBlock("heading", f'{candidate["rank"]}. {candidate["title"]}'),
            DocumentBlock("paragraph", candidate["claim"]),
            DocumentBlock("paragraph", f'规则支持度：{_text(candidate["score"])}，不是准确概率。'),
        ])
        if content.get("composition"):
            blocks.append(DocumentBlock("paragraph", f'可信入口参考道路距离：{candidate["road_distance_m"] / 1000:.2f} 公里；不是实际轨迹。'))
        for key, label in (("supporting_evidence", "支持证据"), ("counter_evidence", "反向证据"),
                           ("information_gaps", "信息缺口")):
            blocks.append(DocumentBlock("heading", label))
            blocks.extend(DocumentBlock("paragraph", text) for text in candidate[key])
        blocks.extend(DocumentBlock("source", ref) for ref in candidate["evidence_refs"])
        blocks.append(DocumentBlock("paragraph", candidate["boundary"]))
    blocks.append(DocumentBlock("heading", "分析信息缺口"))
    blocks.extend(DocumentBlock("paragraph", text) for text in content["information_gaps"]["analysis"])
    semantics = content.get("semantics")
    blocks.append(DocumentBlock("heading", "案情语义画像与原文引用"))
    if semantics:
        blocks.append(DocumentBlock("paragraph", "本地规则整理的原文表述，不是核实结论。复杂语义仍需结合上下文判断。"))
        for item in semantics.get("assertions", []):
            blocks.append(DocumentBlock("paragraph", f'{ASSERTION_LABELS.get(item["kind"], "类型待核")}：{item["value"]}'))
            if item.get("reference"):
                blocks.append(_source(item["reference"]))
        blocks.extend(_semantic_details(semantics))
        blocks.append(DocumentBlock("paragraph", f'语义规则版本：{semantics.get("rule_version", "未记录")}'))
    else:
        blocks.append(DocumentBlock("paragraph", "当前成果未携带语义画像。"))
    # 地图渲染器只接受冻结坐标/区域及版本，不允许下载时混入最新案件位置。
    blocks.append(DocumentBlock("map", _text(frozen_result_map_input(content))))
    blocks.extend([
        DocumentBlock("heading", "版本与适用边界"),
        DocumentBlock("table", "输入版本", _fields(content["versions"])),
        DocumentBlock("paragraph", f'分析状态（记录值）：{content["analysis_status"]}'),
    ])
    blocks.extend(DocumentBlock("paragraph", text) for text in content["boundary"])
    reference = content.get("composition") or {}
    return CaseResultDocument(DOCUMENT_SCHEMA, result["id"], result["content_sha256"], tuple(blocks),
                              reference.get("road_artifact_id"), reference.get("road_content_sha256"))


def load_case_result_document(db: Session, result_id: str, road_artifact_id: str | None = None) -> CaseResultDocument:
    """每次准备导出均重新读取并核对当前权限；不缓存已授权正文。"""
    from app.services.case_result_composition import resolve_result_components
    result, base, artifact = resolve_result_components(db, result_id, road_artifact_id)
    document = build_case_result_document(result)
    if artifact is not None and not result['content'].get('composition'):
        from app.services.case_road_document import attach_road_document, load_document_road

        from app.services.facility_document_map import resolve_facility_map_input
        map_spec = resolve_facility_map_input(db, artifact, case_id=result['content']['case_id'])
        document = attach_road_document(document, artifact, map_spec=map_spec)
    return document
