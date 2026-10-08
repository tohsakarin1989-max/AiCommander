"""Explicit polarity comparisons over existing indexed source fragments."""
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.models.case_history_index import CaseHistoryFragment, CaseHistoryPosting
from app.services.case_history_fragments import condition_term, fragment_reference
from app.services.case_semantic_evidence import text_hash

CONTRAST_VERSION = "history-contrast-8.1-1"
POLARITY = {"stated": "negated", "negated": "stated"}


def explicit_conditions(conditions):
    """Uncertainty/conflicting statements cannot support a polarity contrast."""
    groups = {}
    for category, value, kind in conditions:
        groups.setdefault((category, value), set()).add(kind)
    return {(category, value, next(iter(kinds))) for (category, value), kinds in groups.items()
            if len(kinds) == 1 and next(iter(kinds)) in POLARITY and category != "action"}


def opposite_conditions(conditions):
    return {(category, value, POLARITY[kind]) for category, value, kind in explicit_conditions(conditions)}


def recall_clauses(fragment, conditions):
    """Independent reverse-polarity posting lookup with source-level commonality.

    An opposite clause need not itself mention the shared background; another
    current fragment of the same source may provide it. Never borrow from a
    different case/experience source or from a source's older revision.
    """
    common = aliased(CaseHistoryFragment)
    postings = aliased(CaseHistoryPosting)
    shared_terms = {condition_term(item) for item in explicit_conditions(conditions)}
    opposite_terms = {condition_term(item) for item in opposite_conditions(conditions)}
    return [fragment.id.in_(select(CaseHistoryPosting.fragment_id).where(
        CaseHistoryPosting.branch == "structural", CaseHistoryPosting.term.in_(opposite_terms))),
        select(common.id).join(postings, postings.fragment_id == common.id).where(
            common.case_id == fragment.case_id, common.source_type == fragment.source_type,
            common.source_id == fragment.source_id, common.source_hash == fragment.source_hash,
            common.rule_version == fragment.rule_version,
            postings.branch == "structural", postings.term.in_(shared_terms)).correlate(fragment).exists()]


def build_evidence(query_semantics, query_conditions, historical_conditions, historical_fragments,
                   *, current_source):
    current = explicit_conditions(query_conditions)
    historic = explicit_conditions(historical_conditions)
    shared = current & historic
    differences = historic & opposite_conditions(current)
    if not shared or not differences:
        return None
    current_refs = {}
    for row in query_semantics.get("assertions", []):
        key = (row["category"], row["value"], row["kind"])
        if row.get("reference_verified") and key in current:
            current_refs.setdefault(key, row["reference"])
    historical_refs = {}
    for fragment in sorted(historical_fragments, key=lambda item: (item.field, item.start, item.end)):
        for condition in fragment.conditions:
            historical_refs.setdefault(tuple(condition), fragment_reference(fragment))
    pairs = []
    for condition in sorted(shared):
        if condition in current_refs and condition in historical_refs:
            pairs.append({"condition": list(condition), "current_reference": current_refs[condition],
                          "historical_reference": historical_refs[condition]})
    oppositions = []
    for condition in sorted(differences):
        counterpart = (*condition[:2], POLARITY[condition[2]])
        if counterpart in current_refs and condition in historical_refs:
            oppositions.append({"current_condition": list(counterpart), "historical_condition": list(condition),
                "current_reference": current_refs[counterpart], "historical_reference": historical_refs[condition]})
    if not pairs or not oppositions:
        return None
    return {"version": CONTRAST_VERSION, "current_source": current_source,
            "shared_conditions": pairs, "different_conditions": oppositions,
            "boundary": "共同背景与明确相反表述用于对照，不代表同一过程、事实冲突或正式案件关系；未提及和不确定不作反例。"}


def _validate_reference(values, reference, condition):
    from app.services.case_history_retrieval import business_conditions
    from app.services.case_semantic_service import build_semantic_profile

    field, start, end = reference["field"], reference["start"], reference["end"]
    text = values.get(field)
    if (not isinstance(text, str) or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(text) or text_hash(text) != reference["source_sha256"]
            or text[start:end] != reference["quote"]):
        raise ValueError("history_contrast_reference_changed")
    # Recheck the few cited clauses only; never re-extract the historical corpus.
    grounded = explicit_conditions(business_conditions(build_semantic_profile({field: reference["quote"]})))
    if tuple(condition) not in grounded:
        raise ValueError("history_contrast_assertion_changed")


def validate_evidence(db, item, historical_values, *, source_case_id=None):
    from sqlalchemy import func
    from app.models.case import Case
    from app.models.case_source import CaseRevision
    from app.services.case_history_retrieval import source_values
    from app.services.case_semantic_evidence import freeze_sources, snapshot_payload

    evidence = item.get("contrast_evidence")
    if not isinstance(evidence, dict) or evidence.get("version") != CONTRAST_VERSION:
        raise ValueError("history_contrast_evidence_missing")
    binding = evidence["current_source"]
    if binding.get("case_id") is not None:
        if binding["case_id"] != source_case_id:
            raise ValueError("history_contrast_source_changed")
        current = db.scalar(select(Case).where(Case.id == source_case_id).execution_options(populate_existing=True))
        if current is None:
            raise ValueError("history_contrast_source_unavailable")
        values = source_values(current)
        revision = db.scalar(select(func.max(CaseRevision.id)).where(CaseRevision.case_id == current.id))
        if (revision != binding["source_revision_id"]
                or snapshot_payload(freeze_sources(values))["sha256"] != binding["source_text_hash"]):
            raise ValueError("history_contrast_source_changed")
    else:
        query = binding["query"]
        if not isinstance(query, str) or text_hash(query) != binding["query_sha256"]:
            raise ValueError("history_contrast_query_changed")
        values = {"description": query}
    shared, differences = evidence["shared_conditions"], evidence["different_conditions"]
    if not shared or not differences:
        raise ValueError("history_contrast_conditions_missing")
    for row in shared:
        condition = row["condition"]
        if len(condition) != 3 or condition[2] not in POLARITY:
            raise ValueError("history_contrast_condition_invalid")
        _validate_reference(values, row["current_reference"], condition)
        _validate_reference(historical_values, row["historical_reference"], condition)
    for row in differences:
        current, history = row["current_condition"], row["historical_condition"]
        if (len(current) != 3 or len(history) != 3 or current[:2] != history[:2]
                or POLARITY.get(current[2]) != history[2]):
            raise ValueError("history_contrast_condition_invalid")
        _validate_reference(values, row["current_reference"], current)
        _validate_reference(historical_values, row["historical_reference"], history)
    if (item["shared_conditions"] != [row["condition"] for row in shared]
            or item["different_conditions"] != [row["historical_condition"] for row in differences]):
        raise ValueError("history_contrast_summary_changed")
