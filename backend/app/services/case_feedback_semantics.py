"""Police feedback is explicit source input, never inferred from a handover."""
from collections.abc import Mapping


FEEDBACK_FIELDS = frozenset({"police_reported", "case_filed"})


def _value(case, field):
    return case.get(field) if isinstance(case, Mapping) else getattr(case, field, None)


def feedback_state(case, field):
    """Distinguish confirmed yes/no, unknown, and unverified historical values."""
    if field not in FEEDBACK_FIELDS:
        raise ValueError("invalid_feedback_field")
    value = _value(case, field)
    declared = _value(case, "feedback_known_fields")
    if type(value) is bool and isinstance(declared, list) and field in declared:
        return "known"
    if value is not None and (not isinstance(declared, list) or field not in declared):
        return "legacy_unverified"
    return "unknown"


def known_feedback_value(case, field):
    return _value(case, field) if feedback_state(case, field) == "known" else None


def feedback_fields_after_input(existing, values):
    """Derive provenance from explicit scalar writes, not a client marker list."""
    if "feedback_known_fields" in values:
        raise ValueError("feedback_known_fields_is_read_only")
    previous = _value(existing, "feedback_known_fields") if existing is not None else []
    supplied = FEEDBACK_FIELDS.intersection(values)
    if existing is not None and not supplied:
        return previous
    known = set(previous or []).intersection(FEEDBACK_FIELDS)
    for field in supplied:
        value = values[field]
        if value is not None and type(value) is not bool:
            raise ValueError("feedback_requires_boolean_or_null")
        if value is None:
            known.discard(field)
        else:
            known.add(field)
    return sorted(known)
