"""Finite process projection from frozen sources, without resolving unknown links."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from app.services.case_event_fragments import UNCERTAIN, action_kind
from app.services.case_process_contract import PROCESS_VERSION, canonical, digest, validate_process
from app.services.case_semantic_evidence import SourceText, snapshot_payload, text_hash


MAX_EVENTS = 100
CLAUSES = re.compile(r"[^，,。；;！!？?\n]+[，,。；;！!？?]?")
PLACE = r"[\u4e00-\u9fff0-9A-Za-z-]{0,20}?(?:井场|村屯|仓房|仓库|油井|路口|装卸点)"
TRANSFER = re.compile(rf"从(?P<source>{PLACE})(?:转运|运送|装运|运)(?:至|到)(?P<destination>{PLACE})")
MEASUREMENT = re.compile(r"(?P<oil>原油|凝析油|柴油)\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>吨|千克|公斤|升|立方米)")
UNIT = {"吨": "tonne", "千克": "kg", "公斤": "kg", "升": "liter", "立方米": "m3"}
LOCATION_FIELDS = ("role", "description", "precision", "geometry", "source_note")
MEASUREMENT_FIELDS = ("value", "unit", "stage", "method", "measured_at", "water_cut", "water_cut_basis", "source_note")


def _text_reference(ref: dict, revision_id: int | None) -> dict:
    return {**deepcopy(ref), "kind": "text", "source_revision_id": revision_id,
            "snapshot_path": ["case", ref["field"]]}


def _span(source: SourceText, start: int, end: int, revision_id: int | None) -> dict:
    return _text_reference({"field": source.field, "source_sha256": source.sha256,
                            "start": start, "end": end, "quote": source.text[start:end]}, revision_id)


def _inside(ref: dict, start: int, end: int) -> bool:
    return start <= ref["start"] and ref["end"] <= end


def _context(source_payload: dict, revision_id: int | None) -> dict:
    context = {"snapshots": [], "locations": [], "measurements": []}
    for field, names in (("locations", LOCATION_FIELDS), ("measurements", MEASUREMENT_FIELDS)):
        rows = deepcopy(source_payload.get(field, []))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid_process_structured_source")
        signature = digest(rows)
        context["snapshots"].append({"field": field, "sha256": signature, "value": rows})
        for index, row in enumerate(rows):
            context[field].append({**{name: row.get(name) for name in names},
                "reference": {"kind": "structured", "source_revision_id": revision_id,
                              "source_sha256": signature, "snapshot_path": [field, index], "value": deepcopy(row)},
                "binding_status": "case_context_only"})
    return context


def _locations(source: SourceText, ref: dict, assertions: list[dict], revision_id: int | None) -> list[dict]:
    result = [{"value": item["value"], "kind": item["kind"], "role": "unknown",
               "reference": _text_reference(item["reference"], revision_id), "is_official_fact": False}
              for item in assertions if item["category"] in {"facility", "place_condition"}]
    for match in TRANSFER.finditer(ref["quote"]):
        role_ref = _span(source, ref["start"] + match.start(), ref["start"] + match.end(), revision_id)
        kind = "uncertain" if UNCERTAIN.search(ref["quote"]) else action_kind(ref["quote"], match.start())
        for role in ("source", "destination"):
            place_ref = _span(source, ref["start"] + match.start(role), ref["start"] + match.end(role), revision_id)
            result.append({"value": place_ref["quote"], "kind": kind, "role": role,
                           "reference": place_ref, "role_reference": role_ref, "is_official_fact": False})
    return result


def _measurements(source: SourceText, ref: dict, revision_id: int | None) -> list[dict]:
    result = []
    for match in MEASUREMENT.finditer(ref["quote"]):
        value = float(match["value"])
        if not math.isfinite(value):
            continue
        kind = "uncertain" if UNCERTAIN.search(ref["quote"]) else action_kind(ref["quote"], match.start())
        result.append({"value": value, "unit": UNIT[match["unit"]], "stage": "unknown",
                       "oil_type": match["oil"], "kind": kind, "binding_status": "sentence_expression_only",
                       "reference": _span(source, ref["start"] + match.start(), ref["start"] + match.end(), revision_id),
                       "is_official_fact": False})
    return result


def _relations(events: list[dict], sources: dict, revision_id: int | None) -> list[dict]:
    relations = []
    for left, right in zip(events, events[1:]):
        a, b = left["reference"], right["reference"]
        if a["field"] != b["field"] or not left["actions"] or not right["actions"]:
            continue
        source = sources[a["field"]]
        if source.text[a["end"]:b["start"]].strip():
            continue
        if not re.match(r"\s*(?:首先|先)", a["quote"]) or not re.match(r"\s*(?:随后|然后|之后|再)", b["quote"]):
            continue
        kind = "stated" if left["statement_kind"] == right["statement_kind"] == "stated" else "uncertain"
        ref = _span(source, a["start"], b["end"], revision_id)
        relations.append({"id": text_hash(f"{left['id']}:{right['id']}:precedes"), "type": "precedes",
                          "from_event_id": left["id"], "to_event_id": right["id"], "kind": kind,
                          "reference": ref, "judgment_status": "rule_candidate", "is_official_fact": False})
    return relations


def _conflicts(events: list[dict]) -> list[dict]:
    groups = {}
    for event in events:
        for item in [*[{**item, "category": "action"} for item in event["actions"]], *event["objects"]]:
            if item["kind"] in {"stated", "negated"}:
                groups.setdefault((item["category"], item["value"]), []).append((event["id"], item, event["reference"]))
    conflicts = []
    for (category, value), records in sorted(groups.items()):
        if {item["kind"] for _, item, _ in records} != {"stated", "negated"}:
            continue
        conflicts.append({"id": text_hash(canonical([category, value, [key for key, _, _ in records]])),
                          "category": category, "value": value,
                          "event_ids": list(dict.fromkeys(key for key, _, _ in records)),
                          "references": [deepcopy(reference) for _, _, reference in records],
                          "status": "needs_context_review"})
    return conflicts


def build_process(sources: tuple[SourceText, ...], assertions: list[dict], time_intervals: list[dict],
                  fragments: dict, information_gaps: list[dict], *, source_revision_id: int | None = None,
                  source_hash: str | None = None, source_payload: dict | None = None) -> dict:
    """Keep each clause's known conditions separate; no cross-clause completion."""
    if source_revision_id is not None:
        if source_payload is None or digest(source_payload) != source_hash:
            raise ValueError("process_revision_payload_hash_mismatch")
        if any(source_payload.get("case", {}).get(item.field) != item.text for item in sources):
            raise ValueError("process_revision_text_mismatch")
    by_field = {item.field: item for item in sources}
    events, gaps = [], []
    omitted = fragments["coverage"]["omitted_fragments"]
    for fragment in fragments["items"]:
        original = fragment["reference"]
        source = by_field[original["field"]]
        for clause in CLAUSES.finditer(original["quote"]):
            start, end = original["start"] + clause.start(), original["start"] + clause.end()
            ref = _span(source, start, end, source_revision_id)
            actions = [{**deepcopy(item), "reference": _text_reference(item["reference"], source_revision_id)}
                       for item in fragment["actions"] if _inside(item["reference"], start, end)]
            local = [assertions[index] for index in fragment["assertion_indices"]
                     if _inside(assertions[index]["reference"], start, end)]
            times = [{**{key: item[key] for key in ("start", "end", "start_precision", "end_precision", "timezone")},
                      "reference": _text_reference(item["reference"], source_revision_id)}
                     for index in fragment["time_interval_indices"]
                     if _inside((item := time_intervals[index])["reference"], start, end)]
            locations = _locations(source, ref, local, source_revision_id)
            measurements = _measurements(source, ref, source_revision_id)
            if not actions and not local and not times and not measurements and not locations:
                continue
            if len(events) >= MAX_EVENTS:
                omitted += 1
                continue
            kinds = {item["kind"] for item in actions or local}
            missing = []
            objects = [{key: deepcopy(item[key]) for key in ("category", "value", "kind", "is_official_fact")}
                       | {"reference": _text_reference(item["reference"], source_revision_id)}
                       for item in local if item["category"] in {"oil", "vehicle", "tool", "facility"}]
            for dimension, present in (("action", bool(actions)), ("time", bool(times)), ("object", bool(objects)),
                                       ("place_role", any(item["role"] != "unknown" for item in locations)),
                                       ("measurement", bool(measurements))):
                if not present:
                    missing.append(dimension)
            event_id = text_hash(f"{PROCESS_VERSION}:{source_revision_id}:{source.field}:{source.sha256}:{start}:{end}")
            events.append({"id": event_id, "actions": actions, "statement_kind": next(iter(kinds)) if len(kinds) == 1 else "mixed" if kinds else "uncertain",
                           "judgment_status": "rule_candidate", "objects": objects, "time_intervals": times,
                           "locations": locations, "measurements": measurements, "reference": ref,
                           "relation_status": "sentence_cooccurrence_only", "missing_dimensions": missing,
                           "is_official_fact": False})
            gaps.extend({"code": "process_dimension_unknown", "event_id": event_id, "dimension": name,
                         "reference": deepcopy(ref)} for name in missing)
    for gap in information_gaps:
        enriched = deepcopy(gap)
        if enriched.get("reference"):
            enriched["reference"] = _text_reference(enriched["reference"], source_revision_id)
        gaps.append(enriched)
    if source_revision_id is None:
        gaps.append({"code": "source_revision_unavailable"})
    coverage = {**fragments["coverage"], "limit": MAX_EVENTS, "omitted_fragments": omitted,
                "state": "partial" if omitted or fragments["coverage"]["state"] == "partial" else "rule_scan_complete"}
    process = {"version": PROCESS_VERSION, "source_revision_id": source_revision_id, "source_hash": source_hash,
               "events": events, "relations": _relations(events, by_field, source_revision_id),
               "conflicts": _conflicts(events), "gaps": gaps,
               "structured_context": _context(source_payload or {}, source_revision_id), "coverage": coverage,
               "boundary": "过程仅整理有出处的原文表述与候选关系；引用及类型校验不等于事实核实。案件地点和测量背景不自动归属某个事件，未交代的主体、时间和去向保持未知。"}
    validate_process(process, snapshot_payload(sources))
    return process
