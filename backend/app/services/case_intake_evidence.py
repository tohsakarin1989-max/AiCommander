"""Literal intake references and conservative reporting-status candidates.

These are editable suggestions, never official case facts. A verified reference
means only that the quoted characters exist, not that a model interpretation is
correct. Missing references stay missing instead of citing unrelated text.
"""
import hashlib
import re


CLAUSES = re.compile(r"[^，,。；;！？!?\n]+[，,。；;！？!?\n]?")
STATUS_TERMS = {
    "police_reported": ("报案", "报警", "移交公安", "公安接收", "公安处理"),
    "case_filed": ("立案",),
}
UNIT_TERMS = {"tonne": ("吨",), "liter": ("升",), "kg": ("千克", "公斤"), "m3": ("立方米", "方")}


def reporting_status(text: str, field: str) -> bool | None:
    """Unknown or conflicting statements do not become an affirmative checkbox."""
    seen: set[bool] = set()
    for clause in CLAUSES.finditer(text):
        for match in re.finditer("|".join(STATUS_TERMS[field]), clause.group()):
            before = clause.group()[:match.start()]
            after = clause.group()[match.end():]
            if (re.search(r"是否|不详|待核|未核实|未确认|拟|准备|计划|可能|据称|无法确认|不清楚"
                          r"|不是|并非|不能说|不能认定|未否认|不排除|不一定|未必", before)
                    or re.search(r"不详|待核|未确认|不明确|[？?]", after)):
                return None
            # Deliberately conservative: mixed earlier/later states stay unknown
            # until the employee chooses the current state; no chronology guess.
            negative = bool(re.search(
                r"(?:未|没有|没|不予|不曾|尚无|未经)[^但而]{0,8}$"
                r"|不(?:予|再|曾|向(?:公安(?:机关)?|警方))?$", before))
            seen.add(not negative)
    return next(iter(seen)) if len(seen) == 1 else None


def intake_anchor(text: str, field: str, value) -> dict:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    terms = []
    if field in STATUS_TERMS:
        terms = list(STATUS_TERMS[field])
    elif field == "oil_volume_unit":
        terms = list(UNIT_TERMS.get(value, ())) if isinstance(value, str) else []
    elif isinstance(value, str) and value:
        terms = [value]
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        terms = [str(value)]
    elif isinstance(value, list):
        terms = [item for item in value if isinstance(item, str) and item]
    for term in terms:
        index = text.find(term)
        if index < 0:
            continue
        for clause in CLAUSES.finditer(text):
            if clause.start() <= index < clause.end():
                # Do not silently truncate a quote: its range must still refer
                # to the exact original text, including whitespace and negation.
                start, end = clause.start(), max(clause.end(), index + len(term))
                return {"text": text[start:end], "start": start, "end": end,
                        "source_sha256": digest, "reference_status": "verified"}
    return {"text": "", "start": None, "end": None,
            "source_sha256": digest, "reference_status": "unverified"}


def finalize_intake_evidence(text: str, result: dict) -> dict:
    fields = dict(result.get("case_fields") or {})
    candidates = [dict(item) for item in result.get("candidates", [])]
    corrected = []
    for field in STATUS_TERMS:
        value = reporting_status(text, field)
        if field in fields and (type(fields[field]) is not bool or fields[field] != value):
            corrected.append(field)
        if value is None:
            fields.pop(field, None)
            candidates = [item for item in candidates if item.get("field") != field]
        else:
            fields[field] = value
            matches = [item for item in candidates if item.get("field") == field]
            for item in matches:
                item["value"] = value
            if not matches:
                candidates.append({"field": field, "value": value,
                    "label": "是否报案" if field == "police_reported" else "是否立案",
                    "source": "原文肯否表达，仍需人工核对", "status": "candidate", "confidence": 0})
    if corrected:
        result["warnings"] = [*(result.get("warnings") or []),
            "报案/立案候选已按原文肯否核对；不确定或相互矛盾时保留未知。"]
        if result.get("model_status") == "llm_success":
            fields["description"] = text
            for item in candidates:
                if item.get("field") == "description":
                    item.update(value=text, source="保留原文，避免摘要改变报案/立案状态")
    anchors = []
    for index, item in enumerate(candidates, start=1):
        field = item.get("field")
        if not field or field == "title":
            continue
        ref = intake_anchor(text, field, item.get("value"))
        anchors.append({"id": f"anchor-{index}", "field": field,
                        "source": item.get("source", ""), **ref})
    result.update(case_fields=fields, candidates=candidates, evidence_anchors=anchors,
                  extraction_evidence_version="intake-evidence-7.1-1",
                  source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    return result
