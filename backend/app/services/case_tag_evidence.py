"""Ground legacy tags in literal fields; keep JSON paths and polarity intact."""
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload
from app.services.case_semantic_mentions import extract_term_assertions, mention_kind
from app.services.case_semantic_structured import extract_structured_sources


TAG_RULE_VERSION = "source-polarity-2026-09-27-1"
TAG_TEXT_FIELDS = (
    "description", "location", "case_type", "modus_operandi", "facility_type",
    "oil_type", "oil_nature", "source_detail", "vehicle_handling", "oil_handling",
)
# These JSON fields carry literal descriptions. Unknown container/status schemas
# stay uncertain rather than discarding their context and promoting a leaf.
LITERAL_KEYS = frozenset({
    "vehicle_type", "type", "description", "name", "items", "vehicles",
    "说明", "描述", "类型", "车辆类型", "名称", "物品名称", "车辆", "物品",
})


def _structured_context(reference, entries):
    path = reference["path"]
    ambiguous_path = any(isinstance(part, str) and part not in LITERAL_KEYS for part in path)
    context_refs = []
    for entry in entries:
        other = entry["reference"]
        if other["field"] != reference["field"] or other == reference:
            continue
        other_path = other["path"]
        # Scalar status fields in the same object or an ancestor constrain this
        # leaf. Vehicle IDs are metadata, never assertion status.
        parent = other_path[:-1]
        if other_path and path[:len(parent)] == parent:
            key = other_path[-1]
            value = other["value"]
            constrained_text = isinstance(value, str) and mention_kind(
                value + "\ufffc", len(value), len(value) + 1,
            ) != "stated"
            if constrained_text or (isinstance(key, str) and key not in LITERAL_KEYS
                                    and key not in {"id", "plate_number"}):
                context_refs.append(other)
    return ambiguous_path or bool(context_refs), context_refs


def collect_tag_evidence(case, terms):
    values = {field: getattr(case, field, None) for field in TAG_TEXT_FIELDS}
    result = extract_term_assertions(values, terms)
    assertions = result["assertions"]
    gaps = result["information_gaps"]
    if case.security_level:
        values["security_level"] = case.security_level
        if len(assertions) >= 200:
            gaps.append({"code": "extraction_limit", "field": "security_level"})
        else:
            security = extract_term_assertions({"security_level": case.security_level}, {
                "defense": {word: "weakness_low_security" for word in ("低", "薄弱", "差")},
            }, limit=200 - len(assertions))
            assertions.extend(security["assertions"])
            gaps.extend(security["information_gaps"])
    structured = extract_structured_sources({
        "vehicle_info": case.vehicle_info,
        "involved_items": case.involved_items,
        "case_vehicles": [
            {"id": vehicle.id, "vehicle_type": vehicle.vehicle_type}
            for vehicle in (case.vehicles or [])
        ],
    })
    gaps.extend(structured["information_gaps"])
    for entry in structured["entries"]:
        reference = entry["reference"]
        value = reference["value"]
        # Keys, booleans, IDs and counts are not affirmative prose. In particular,
        # {"套牌": false} must not become a positive vehicle label.
        if not isinstance(value, str) or not value.strip():
            continue
        remaining = max(0, 200 - len(assertions))
        if not remaining:
            gaps.append({"code": "extraction_limit", "field": reference["field"]})
            break
        extracted = extract_term_assertions({"vehicle_info": value}, terms, limit=remaining)
        gaps.extend(extracted["information_gaps"])
        for assertion in extracted["assertions"]:
            # The source is a JSON leaf, not a substring of serialized JSON.
            assertion["reference"] = reference
            assertion.pop("mention_span", None)
            ambiguous, context_refs = _structured_context(reference, structured["entries"])
            if ambiguous:
                assertion["kind"] = "uncertain"
                assertion["context_references"] = context_refs
            assertions.append(assertion)
    return {
        "assertions": assertions, "information_gaps": gaps,
        "source_snapshot": snapshot_payload(freeze_sources(values)),
        "structured_sources": structured,
    }
