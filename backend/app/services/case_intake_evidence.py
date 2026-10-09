"""Literal intake references and conservative reporting-status candidates.

These are editable suggestions, never official case facts. A verified reference
means only that the quoted characters exist, not that a model interpretation is
correct. Missing references stay missing instead of citing unrelated text.
"""
import hashlib
import math
import re
from datetime import datetime


CLAUSES = re.compile(r"[^，,。；;！？!?\n]+[，,。；;！？!?\n]?")
STATUS_TERMS = {
    "police_reported": ("报案", "报警"),
    "case_filed": ("立案",),
}
UNIT_TERMS = {"tonne": ("吨",), "liter": ("升",), "kg": ("千克", "公斤"), "m3": ("立方米", "方")}
ROLE_FIELDS = {"occurred_time", "discovered_at", "report_time", "oil_volume", "oil_volume_unit",
               "person_handling", "vehicle_handling", "oil_handling"}
EXACT_TIME = re.compile(
    r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})[日号]?\s*[T ]?"
    r"(凌晨|上午|下午|晚上)?\s*(\d{1,2})[时:](\d{1,2})(?:分)?")
TIME_ROLE = re.compile(
    r"(?P<occurred_time>案发|发生时间|盗取时间|被盗时间)|"
    r"(?P<discovered_at>发现|查获|抓获)|(?P<report_time>接报|报送|上报|报案时间)")
NEW_TIME_CONTEXT = re.compile(
    r"[次翌明昨今后前][日天晚晨夜]|[0-9一二两三四五六七八九十]+(?:年|月|日|天|小时|分钟|时|点)")
OIL_MATERIAL = re.compile(r"原油|油品|柴油|汽油|成品油|落地油|涉油|拉油|载油|装油|盗油")
CAPACITY = re.compile(r"载重|核载|载荷|容积|容量|空重|自重|毛重|总重|罐体|罐容|油罐车|水罐")
UNCERTAIN_ACTION = re.compile(r"未|没有|不予|不曾|不是|并非|不详|待核|待定|是否|拟|准备|计划|可能|尚无")
HANDLING_NOT_COMPLETED = re.compile(r"建议|拒绝|拒不|不愿|不能|无法|要求|应当|应该|预计|明日|明天|将于|尚需|尚待")
UNKNOWN_TIME_TAIL = re.compile(
    r"^\s*(?:[，,]\s*)?(?:时间|时刻)?(?:为|是)?[：:\s]*"
    r"(?:未知|不详|不明确|待核|待定|未核实|未确认|不确定|尚未确认|无法确认|不清楚)")
UNKNOWN_HANDLING_TAIL = re.compile(
    r"^\s*(?:(?:给|至|向)?公安(?:机关|部门)?)?(?:的)?(?:情况|状态|结果|申请|与否)?"
    r"(?:未知|不详|待核|待定|未确认|未核实|尚未|未完成|不明确|不清楚|被拒绝|了吗|了么)")
HANDLING_OBJECT = re.compile(
    r"(?P<person_handling>人员|嫌疑人|驾驶员|司机|[一二两俩三四五六七八九十\d]+(?:名人员|人))|"
    r"(?P<vehicle_handling>车辆|机动车|汽车|货车|油罐车|罐车|卡车|槽车)|(?P<oil_handling>原油|油品|涉案油|油)")
HANDLING_ACTION = re.compile(r"移交|交公安|治安拘留|行政拘留|刑事拘留|刑拘|扣押|查扣|检斤入库|回收入库|入库|暂存|收缴")
# Exact numeric fields accept only a small positive grammar. Unrecognised
# qualifiers remain in the narrative instead of relying on an endless list of
# approximation/range expressions to reject.
EXACT_QUANTITY_BRIDGE = re.compile(r"\s*(?:(?:共|计|合计|数量|净重|重量|检斤|为|重|：|:)\s*)*")
EXACT_QUANTITY_TAIL = re.compile(r"\s*(?:(?:的)?(?:原油|油品|柴油|汽油|成品油))?\s*[，,。；;！!\n]*")
INEXACT_QUANTITY_CONTEXT = re.compile(r"约|估|[上下]限|[大小少多]于|不[足满到]|至[多少]|近(?:有|为|计)?\s*$")
TRANSFER_COMPLETION_TAIL = re.compile(
    r"\s*(?:(?:给|至|向)?公安(?:机关|部门)?)?(?:处理)?(?:了|完成|完毕)?\s*")


def _record(value, start, end):
    return {"value": value, "start": start, "end": end}


def _time_roles(text):
    found = {}
    dates = list(EXACT_TIME.finditer(text))
    for index, match in enumerate(dates):
        year, month, day, period, hour, minute = match.groups()
        try:
            hour = int(hour)
            if period in {"下午", "晚上"} and hour < 12:
                hour += 12
            value = datetime(int(year), int(month), int(day), hour, int(minute)).isoformat()
        except ValueError:
            continue
        # Only an adjacent role label or the first following event binds a date.
        # A discovery of theft is still a discovery, not the theft timestamp.
        prefix_start = max([text.rfind(delimiter, 0, match.start()) + 1
                            for delimiter in "，,。；;！？!?\n"])
        prefix = text[prefix_start:match.start()]
        labels = list(TIME_ROLE.finditer(prefix))
        role = labels[-1] if labels and re.fullmatch(r"(?:时间)?[为于是在：:\s]*", prefix[labels[-1].end():]) else None
        anchor_start, anchor_end = prefix_start, match.end()
        if role is None:
            end = dates[index + 1].start() if index + 1 < len(dates) else len(text)
            suffix = text[match.end():min(end, match.end() + 100)]
            # A comma immediately after a timestamp is formatting. A later
            # comma terminates its event clause: do not lend the timestamp to
            # a subsequent discovery/report (which may be on another day).
            leading = re.match(r"\s*[，,]?\s*", suffix).end()
            suffix = suffix[:leading] + re.split(r"[，,。；;！？!?\n]", suffix[leading:], 1)[0]
            role = TIME_ROLE.search(suffix)
            if (role is None or UNCERTAIN_ACTION.search(suffix[:role.start()])
                    or NEW_TIME_CONTEXT.search(suffix[:role.start()])
                    or UNKNOWN_TIME_TAIL.match(suffix[role.end():])):
                continue
            anchor_start, anchor_end = match.start(), match.end() + len(suffix)
        elif UNCERTAIN_ACTION.search(prefix[:role.start()]):
            continue
        elif UNKNOWN_TIME_TAIL.match(text[match.end():]):
            continue
        found.setdefault(role.lastgroup, []).append(_record(value, anchor_start, anchor_end))
    return {key: items[0] for key, items in found.items()
            if len({item["value"] for item in items}) == 1}


def oil_measurement_evidence(text):
    """Select one material-bound quantity, never a vehicle/tank capacity."""
    units = {"吨": "tonne", "t": "tonne", "公斤": "kg", "千克": "kg", "kg": "kg",
             "升": "liter", "l": "liter", "立方米": "m3", "m3": "m3", "m³": "m3"}
    amounts = re.compile(r"(\d+(?:\.\d+)?)\s*(立方米|公斤|千克|kg|吨|升|m3|m³|t|l)(?![A-Za-z])", re.I)
    found = []
    previous = None
    for clause in CLAUSES.finditer(text):
        fragment = clause.group()
        for match in amounts.finditer(fragment):
            before, after = fragment[:match.start()], fragment[match.end():]
            materials = list(OIL_MATERIAL.finditer(before))
            material = materials[-1] if materials else None
            bridge = before[material.end():] if material else before
            if (before.rstrip().endswith(("-", "−")) or not math.isfinite(float(match.group(1)))
                    or CAPACITY.search(bridge) or re.match(r"\s*(?:以上|以下|载重|机动车|卡车|油罐车)", after)
                    or UNCERTAIN_ACTION.search(bridge)):
                continue
            bound = bool(material and EXACT_QUANTITY_BRIDGE.fullmatch(bridge))
            if material and (UNCERTAIN_ACTION.search(before[:material.start()])
                             or INEXACT_QUANTITY_CONTEXT.search(before[:material.start()])):
                bound = False
            reversed_binding = bool(re.match(r"\s*(?:的)?(?:原油|油品|柴油|汽油|成品油)", after))
            if reversed_binding:
                # With material after the number, require an adjacent literal
                # measurement/action rather than accepting "约2吨原油".
                bound = bound or (not UNCERTAIN_ACTION.search(before)
                    and not INEXACT_QUANTITY_CONTEXT.search(before)
                    and (not before.strip() or bool(re.search(
                        r"(?:发现|查获|收缴|装有|载有|扣押|盗取|盗运|共计)\s*$", before))))
            if not EXACT_QUANTITY_TAIL.fullmatch(after):
                continue
            start = clause.start()
            # Short exact continuation such as “拉油，共1.5吨” retains a local
            # material reference; a new vehicle/object clause never inherits it.
            if (not bound and previous is not None and OIL_MATERIAL.search(previous.group())
                    and not CAPACITY.search(previous.group())
                    and not re.search(r"\d", previous.group())
                    and not UNCERTAIN_ACTION.search(previous.group())
                    and not INEXACT_QUANTITY_CONTEXT.search(previous.group())
                    and previous.group().rstrip().endswith(("，", ","))
                    and EXACT_QUANTITY_BRIDGE.fullmatch(before)):
                bound, start = True, previous.start()
            if bound:
                stage_specific = bool(re.search(r"回收|移交|移送|入库|返还", text[start:clause.end()]))
                found.append((_record((float(match.group(1)), units[match.group(2).lower()]),
                                      start, clause.end()), stage_specific))
        previous = clause
    # Preserve stage-specific amounts in the original narrative/observations;
    # never promote them into the generic case quantity or select among stages.
    return found[0][0] if len(found) == 1 and not found[0][1] else None


def _handling_roles(text):
    found, uncertain = {}, set()
    for clause in re.finditer(r"[^，,。；;！？!?\n但]+", text):
        fragment = clause.group()
        objects = list(HANDLING_OBJECT.finditer(fragment))
        for action in HANDLING_ACTION.finditer(fragment):
            prior = [item for item in objects if item.end() <= action.start()]
            obj = prior[-1] if prior else next((item for item in objects
                    if action.end() <= item.start() <= action.end() + 4), None)
            if obj is None:
                continue
            coordinated = [obj]
            for previous in reversed(prior[:-1]):
                if not re.fullmatch(r"\s*(?:及|和|与|、)\s*", fragment[previous.end():coordinated[0].start()]):
                    break
                coordinated.insert(0, previous)
            fields = {item.lastgroup for item in coordinated}
            boundary = max((item.end() for item in objects if item.end() <= coordinated[0].start()), default=0)
            scope = fragment[boundary:action.start()]
            following = fragment[action.end():]
            if (UNCERTAIN_ACTION.search(scope) or HANDLING_NOT_COMPLETED.search(scope)
                    or re.search(r"(?:将(?:要|被|会)?|待)\s*$", fragment[obj.end():action.start()])
                    or UNKNOWN_HANDLING_TAIL.match(following)
                    or text[clause.end():clause.end() + 1] in {"?", "？"}):
                uncertain.update(fields)
                continue
            if len(coordinated) > 1 and not re.fullmatch(
                    r"\s*(?:(?:已|均|都|全部|一并|共同|被|予以)\s*)*", fragment[obj.end():action.start()]):
                # “车辆及人员名单已移交” transfers a document, not the listed
                # objects. Only adjacent explicit coordination shares a verb.
                uncertain.update(fields)
                continue
            verb = action.group()
            transfer = None
            if verb in {"移交", "交公安"} and ("公安" in following[:12] or verb == "交公安"):
                tail = following
                if obj.start() >= action.end():
                    tail = fragment[obj.end():]
                if not TRANSFER_COMPLETION_TAIL.fullmatch(tail):
                    uncertain.update(fields)
                    continue
                transfer = "移交公安"
            for field in fields:
                value = transfer
                if field == "person_handling" and verb in {"治安拘留", "行政拘留", "刑事拘留", "刑拘"}:
                    value = verb
                elif field == "vehicle_handling" and verb in {"扣押", "查扣"}:
                    value = "扣押停放"
                elif field == "oil_handling" and verb in {"检斤入库", "回收入库", "入库", "暂存"}:
                    value = "检斤入库" if "入库" in verb else "暂存"
                if value:
                    found.setdefault(field, []).append(_record(value, clause.start(), clause.end()))
    return {key: items[0] for key, items in found.items() if key not in uncertain
            and len({item["value"] for item in items}) == 1}


def intake_role_evidence(text):
    result = {**_time_roles(text), **_handling_roles(text)}
    measurement = oil_measurement_evidence(text)
    if measurement:
        quantity, unit = measurement["value"]
        for key, value in (("oil_volume", quantity), ("oil_volume_unit", unit)):
            result[key] = {**measurement, "value": value}
    return result


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
    roles = intake_role_evidence(text)
    source_fields = dict(result.get("field_sources") or {})
    corrected = []
    for field in ROLE_FIELDS:
        expected = roles.get(field, {}).get("value")
        existing = [item for item in candidates if item.get("field") == field]
        if ((field in fields and fields[field] != expected)
                or any(item.get("value") != expected for item in existing)):
            corrected.append(field)
        if expected is None:
            fields.pop(field, None)
            source_fields.pop(field, None)
            candidates = [item for item in candidates if item.get("field") != field]
        else:
            fields[field] = expected
            source_fields[field] = "原文对象、动作和时间角色核对，仍需人工确认"
            for item in existing:
                item.update(value=expected, source=source_fields[field])
            if not existing:
                candidates.append({"field": field, "value": expected, "label": field,
                                   "source": source_fields[field], "status": "candidate", "confidence": 0})
    description = fields.get("description")
    if isinstance(description, str) and result.get("model_status") == "llm_success":
        described = {key: item["value"] for key, item in intake_role_evidence(description).items()}
        if described != {key: item["value"] for key, item in roles.items()}:
            corrected.append("description")
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
            "时间角色、涉油数量及处置/报案候选已按原文对象和肯否核对；不确定或矛盾时保留未知。"]
        if result.get("model_status") == "llm_success":
            fields["description"] = text
            for item in candidates:
                if item.get("field") == "description":
                    item.update(value=text, source="保留原文，避免摘要改变时间、数量或对象处置")
    anchors = []
    for index, item in enumerate(candidates, start=1):
        field = item.get("field")
        if not field or field == "title":
            continue
        if field in roles:
            start, end = roles[field]["start"], roles[field]["end"]
            ref = {"text": text[start:end], "start": start, "end": end,
                   "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   "reference_status": "verified"}
        else:
            ref = intake_anchor(text, field, item.get("value"))
        anchors.append({"id": f"anchor-{index}", "field": field,
                        "source": item.get("source", ""), **ref})
    result.update(case_fields=fields, candidates=candidates, evidence_anchors=anchors,
                  field_sources=source_fields, extraction_evidence_version="intake-evidence-field-roles-3",
                  source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    return result
