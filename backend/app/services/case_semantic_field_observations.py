"""Literal field response notes, separate from alleged conduct and source facts.

These notes do not participate in method similarity: two units both handing
over property does not establish a shared theft method or criminal linkage.
"""
from dataclasses import asdict
from math import isfinite
import re

from app.services.case_event_fragments import UNCERTAIN, action_kind
from app.services.case_semantic_evidence import SourceText, TextReference, text_hash


VERSION = "field-observations-1"
LIMIT = 100
CLAUSES = re.compile(r"[^，,。；;！!？?\n]+[，,。；;！!？?]?")
OPERATIONS = {
    "巡逻发现": ("discovery", "发现情况", "unknown"),
    "巡查发现": ("discovery", "发现情况", "unknown"),
    "现场发现": ("discovery", "发现情况", "unknown"),
    "发现": ("discovery", "发现情况", "unknown"),
    "查获": ("seizure", "现场查获", "seized"),
    "查扣": ("seizure", "现场查扣", "seized"),
    "收缴": ("seizure", "现场收缴", "seized"),
    "回收": ("recovery", "回收情况", "recovered"),
    "移交": ("handover", "移交情况", "transferred"),
    "检斤": ("weighing", "检斤记录", "unknown"),
}
OPERATION = re.compile("|".join(map(re.escape, sorted(OPERATIONS, key=len, reverse=True))))
RECOVERY_NOUN = re.compile(
    r"站|点|池|设备|系统|中心|部门|人员|员|"
    r"(?:第?[一二三四五六七八九十百0-9]{0,3})(?:大队|中队|分队|小队|队|班|组)"
)
PLANNED_OR_REPORTED = re.compile(
    r"拟|计划|准备|据称|听说|要求|建议|应当|应予|应该|需要|须|"
    r"拒绝|暂缓|推迟|待(?:移交|回收|检斤)|尚待"
)
OIL = r"原油|凝析油|柴油|落地油|油品|含油污水|油水混合物"
UNIT = {"吨": "tonne", "千克": "kg", "公斤": "kg", "升": "liter", "立方米": "m3"}
MEASUREMENT = re.compile(
    rf"(?P<oil>{OIL})\s*[:：]?\s*(?P<approx>约|大约)?\s*"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>吨|千克|公斤|升|立方米)"
)
MEASUREMENT_FIRST = re.compile(
    r"(?P<approx>约|大约)?\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*"
    rf"(?P<unit>吨|千克|公斤|升|立方米)\s*(?:的)?(?P<oil>{OIL})"
)


def _reference(source: SourceText, start: int, end: int) -> dict:
    ref = TextReference(source.field, source.sha256, start, end, source.text[start:end])
    ref.validate(source)
    return asdict(ref)


def _measurements(source, clause, operation, *, stage, kind):
    # Capacity/load specifications must never become an amount of seized oil.
    text = clause.group()
    if re.search(r"载重|荷载|容积|容量|额定|核载|核定", text):
        return []
    found = []
    for pattern in (MEASUREMENT, MEASUREMENT_FIRST):
        for match in pattern.finditer(text):
            if re.search(r"[-+－—~～至]\s*$", text[:match.start("value")]):
                continue
            if re.match(r"\s*(?:以上|以下|左右|上下|或|至|到|[-－—~～])", text[match.end():]):
                continue
            # The action must precede this quantity with only a narrow literal
            # qualifier, not another person/vehicle or a different object.
            between = text[operation.end():match.start()].strip()
            if match.start() < operation.end() or not re.fullmatch(
                r"(?:了|的|含水|涉案|被盗|现场|查获的|扣押的|共计|共|合计|油品)*", between
            ):
                continue
            value = float(match["value"])
            if not isfinite(value):
                continue
            found.append({"value": value, "unit": UNIT[match["unit"]],
                "oil_type": match["oil"], "stage": stage,
                "kind": "uncertain" if match["approx"] and kind == "stated" else kind,
                "reference": _reference(source, clause.start() + match.start(), clause.start() + match.end()),
                "is_official_fact": False})
    # Multiple numbers in the same clause need a source-aware measurement row;
    # do not guess whether they are gross/net, before/after, or separate lots.
    return found if len(found) == 1 else []


def build_field_observations(sources: tuple[SourceText, ...]) -> dict:
    items, omitted = [], 0
    for source in sources:
        if source.field != "description":
            continue
        for clause in CLAUSES.finditer(source.text):
            text = clause.group()
            operations = [match for match in OPERATION.finditer(text)
                          if not (match.group() == "回收" and RECOVERY_NOUN.match(text[match.end():]))]
            for match in operations:
                if len(items) >= LIMIT:
                    omitted += 1
                    continue
                category, label, stage = OPERATIONS[match.group()]
                kind = ("uncertain" if UNCERTAIN.search(text) or PLANNED_OR_REPORTED.search(text)
                        else action_kind(text, match.start()))
                # A form name or a procedural requirement is not a completed
                # response. Preserve the quoted wording as uncertain instead.
                if re.match(r"清单|要求|手续|规定|单据|证明", text[match.end():]):
                    kind = "uncertain"
                quantities = _measurements(source, clause, match, stage=stage, kind=kind) if len(operations) == 1 else []
                items.append({
                    "id": text_hash(f"{VERSION}:{source.field}:{source.sha256}:{clause.start() + match.start()}"),
                    "category": category, "label": label, "kind": kind,
                    "reference": _reference(source, clause.start(), clause.end()),
                    "measurements": quantities, "is_official_fact": False,
                })
    return {
        "schema_version": VERSION, "items": items,
        "coverage": {"state": "partial" if omitted else "rule_scan_complete", "limit": LIMIT, "omitted_items": omitted},
        "boundary": "仅整理发现、查获、回收、移交等原文表述，与盗取及转运行为分开。各环节数量不相加、不等于损失量，不换算净油量；移交不代表公安立案或办结。缺少单位、存在多环节或跨句歧义时不绑定数量，仍保留原文。",
    }
