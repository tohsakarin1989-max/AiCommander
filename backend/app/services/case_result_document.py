"""Word/PDF共用内容模型；仅排布冻结输入，不查询业务事实或执行模型。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import RESULT_SCHEMA_VERSION, verify_snapshot


DOCUMENT_SCHEMA = "case-result-document-4.1.0-1"
FIELD_LABELS = {
    "occurred_time": "案发时间（存储值）", "location": "地点", "case_type": "案件类型",
    "oil_type": "油品", "oil_nature": "油品性质", "facility_type": "设施类型",
    "modus_operandi": "作案手法", "report_unit": "报案单位", "source_type": "案件来源",
    "upstream_source": "来源线索", "downstream_destination": "去向线索",
    "water_cut": "含水率（记录值）", "oil_volume": "涉油数量（记录值）",
    "oil_value": "涉油价值（记录值）", "evidence_count": "证据记录数",
    "vehicle_count": "车辆记录数", "person_count": "人员记录数",
}
ASSERTION_LABELS = {"stated": "原文陈述", "negated": "原文否定", "uncertain": "待核表述", "inferred": "推断"}


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


def _text(value: object) -> str:
    if value is None or value == "":
        return "未记录"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _fields(values: dict) -> tuple[tuple[str, str], ...]:
    # 未认识的新字段仍保留字段名和值，不悄悄丢弃版本化证据。
    return tuple((FIELD_LABELS.get(key, key), _text(value)) for key, value in sorted(values.items()))


def build_case_result_document(result: dict) -> CaseResultDocument:
    """纯转换；调用者须先授权。hash校验只证明内容一致，不证明可向用户交付。"""
    if not verify_snapshot(result) or result["content"].get("schema_version") != RESULT_SCHEMA_VERSION:
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
    blocks.append(DocumentBlock("heading", "关键缺项"))
    for gap in content["information_gaps"]["profile"]:
        blocks.append(DocumentBlock("paragraph", f'{gap["label"]}：{gap.get("reason") or "待补充核对"}'))
    blocks.append(DocumentBlock("heading", "待核验候选"))
    if not content["candidates"]:
        blocks.append(DocumentBlock("paragraph", "尚无可展示候选，不代表不存在相关线索。"))
    for candidate in content["candidates"]:
        blocks.extend([
            DocumentBlock("heading", f'{candidate["rank"]}. {candidate["title"]}'),
            DocumentBlock("paragraph", candidate["claim"]),
            DocumentBlock("paragraph", f'规则支持度：{_text(candidate["score"])}，不是准确概率。'),
        ])
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
                ref = item["reference"]
                blocks.append(DocumentBlock("source", f'{ref["field"]} · 字符 {ref["start"] + 1} 至 {ref["end"]}：{ref["quote"]}'))
        # 精确时间精度、结构化路径、冲突及完整引用供渲染器排版，不丢弃折叠区内容。
        for key, label in (("time_intervals", "时间表达（保留精度与时区）"),
                           ("structured_sources", "结构化来源与字段路径"),
                           ("potential_conflicts", "表述冲突"), ("information_gaps", "提取限制")):
            if semantics.get(key):
                blocks.append(DocumentBlock("source", label, ((key, _text(semantics[key])),)))
        blocks.append(DocumentBlock("paragraph", f'语义规则版本：{semantics.get("rule_version", "未记录")}'))
    else:
        blocks.append(DocumentBlock("paragraph", "当前成果未携带语义画像。"))
    # 地图渲染器只接受冻结坐标/区域及版本，不允许下载时混入最新案件位置。
    blocks.append(DocumentBlock("map", _text({
        "map_snapshot_id": content["versions"]["map_snapshot_id"],
        "recorded_fields": content["facts_summary"]["recorded_fields"],
        "candidates": [{"id": item["id"], "region": item["region"], "evidence_refs": item["evidence_refs"]}
                       for item in content["candidates"]],
    })))
    blocks.extend([
        DocumentBlock("heading", "版本与适用边界"),
        DocumentBlock("table", "输入版本", _fields(content["versions"])),
        DocumentBlock("paragraph", f'分析状态（记录值）：{content["analysis_status"]}'),
    ])
    blocks.extend(DocumentBlock("paragraph", text) for text in content["boundary"])
    return CaseResultDocument(DOCUMENT_SCHEMA, result["id"], result["content_sha256"], tuple(blocks))


def load_case_result_document(db: Session, result_id: str) -> CaseResultDocument:
    """每次准备导出均重新读取并核对当前权限；不缓存已授权正文。"""
    return build_case_result_document(CaseResultService.read(db, result_id))
