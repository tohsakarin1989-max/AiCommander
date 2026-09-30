"""Typed, source-bound case process candidates; validation never verifies facts."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.case_semantic_evidence import SourceText, TextReference


PROCESS_VERSION = "case-process-6.3-1"
Kind = Literal["stated", "negated", "uncertain", "inferred"]


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TextSource(StrictRecord):
    kind: Literal["text"]
    source_revision_id: int | None
    snapshot_path: list[str | int]
    field: str
    source_sha256: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class StructuredSource(StrictRecord):
    kind: Literal["structured"]
    source_revision_id: int | None
    source_sha256: str
    snapshot_path: list[str | int]
    value: Any


Reference = Annotated[TextSource | StructuredSource, Field(discriminator="kind")]


class Assertion(StrictRecord):
    value: str
    kind: Kind
    reference: TextSource
    is_official_fact: Literal[False]


class ObjectAssertion(Assertion):
    category: str


class PlaceAssertion(Assertion):
    role: Literal["unknown", "source", "destination"]
    role_reference: TextSource | None = None


class TimeInterval(StrictRecord):
    start: str
    end: str
    start_precision: str
    end_precision: str
    timezone: str | None
    reference: TextSource


class TextMeasurement(StrictRecord):
    value: float = Field(ge=0)
    unit: Literal["tonne", "liter", "kg", "m3"]
    stage: Literal["unknown"]
    oil_type: str
    kind: Kind
    reference: TextSource
    binding_status: Literal["sentence_expression_only"]
    is_official_fact: Literal[False]


class ProcessEvent(StrictRecord):
    id: str
    actions: list[Assertion]
    statement_kind: Literal["stated", "negated", "uncertain", "inferred", "mixed"]
    judgment_status: Literal["rule_candidate"]
    objects: list[ObjectAssertion]
    time_intervals: list[TimeInterval]
    locations: list[PlaceAssertion]
    measurements: list[TextMeasurement]
    reference: TextSource
    relation_status: Literal["sentence_cooccurrence_only"]
    missing_dimensions: list[str]
    is_official_fact: Literal[False]


class ProcessRelation(StrictRecord):
    id: str
    type: Literal["precedes"]
    from_event_id: str
    to_event_id: str
    kind: Kind
    reference: TextSource
    judgment_status: Literal["rule_candidate"]
    is_official_fact: Literal[False]


class ProcessConflict(StrictRecord):
    id: str
    category: str
    value: str
    event_ids: list[str]
    references: list[TextSource]
    status: Literal["needs_context_review"]


class ProcessGap(StrictRecord):
    code: str
    event_id: str | None = None
    dimension: str | None = None
    field: str | None = None
    reference: Reference | None = None


class ContextLocation(StrictRecord):
    role: Literal["incident", "discovery", "mentioned", "source_candidate", "custody"]
    description: str | None
    precision: Literal["exact", "area", "unknown"]
    geometry: dict | None
    source_note: str | None
    reference: StructuredSource
    binding_status: Literal["case_context_only"]


class ContextMeasurement(StrictRecord):
    value: float = Field(ge=0)
    unit: Literal["tonne", "liter", "kg", "m3", "unknown"]
    stage: Literal["involved", "seized", "transferred", "recovered", "unknown"]
    method: str | None
    measured_at: str | None
    water_cut: float | None
    water_cut_basis: str | None
    source_note: str | None
    reference: StructuredSource
    binding_status: Literal["case_context_only"]


class StructuredSnapshot(StrictRecord):
    field: Literal["locations", "measurements"]
    sha256: str
    value: list[dict]


class StructuredContext(StrictRecord):
    snapshots: list[StructuredSnapshot]
    locations: list[ContextLocation]
    measurements: list[ContextMeasurement]


class Coverage(StrictRecord):
    state: Literal["partial", "rule_scan_complete"]
    limit: int = Field(gt=0)
    omitted_fragments: int = Field(ge=0)
    input_assertions_partial: bool


class CaseProcess(StrictRecord):
    version: Literal["case-process-6.3-1"]
    source_revision_id: int | None
    source_hash: str | None
    events: list[ProcessEvent] = Field(max_length=100)
    relations: list[ProcessRelation] = Field(max_length=100)
    conflicts: list[ProcessConflict] = Field(max_length=300)
    gaps: list[ProcessGap]
    structured_context: StructuredContext
    coverage: Coverage
    boundary: str


def validate_process(process: dict, source_snapshot: dict) -> None:
    """Reject changed types, spans, hashes, bindings and dangling event links.

    The caller supplies the frozen semantic source snapshot. A valid quote and
    type establish provenance only, never the truth of a relationship.
    """
    try:
        def require_nonfact(value: Any) -> None:
            if isinstance(value, dict):
                if "is_official_fact" in value and value["is_official_fact"] is not False:
                    raise ValueError("process_fact_promotion_forbidden")
                for child in value.values():
                    require_nonfact(child)
            elif isinstance(value, list):
                for child in value:
                    require_nonfact(child)

        require_nonfact(process)
        parsed = CaseProcess.model_validate(process)
        if (parsed.source_revision_id is None) != (parsed.source_hash is None):
            raise ValueError("incomplete_process_source_version")
        if parsed.source_revision_id is not None and parsed.source_revision_id <= 0:
            raise ValueError("invalid_process_source_revision")
        if parsed.source_hash is not None and (len(parsed.source_hash) != 64
                or any(char not in "0123456789abcdef" for char in parsed.source_hash)):
            raise ValueError("invalid_process_source_hash")
        records = source_snapshot["fields"]
        if source_snapshot.get("schema_version") != "semantic-source-1":
            raise ValueError("unsupported_process_source_snapshot")
        if digest(records) != source_snapshot["sha256"]:
            raise ValueError("process_source_snapshot_hash_mismatch")
        sources = {item["field"]: SourceText(**item) for item in records}
        if len(sources) != len(records):
            raise ValueError("duplicate_process_source_field")
        snapshots = {item.field: item for item in parsed.structured_context.snapshots}
        if len(snapshots) != len(parsed.structured_context.snapshots):
            raise ValueError("duplicate_process_structured_source")
        for snapshot in snapshots.values():
            if digest(snapshot.value) != snapshot.sha256:
                raise ValueError("process_structured_snapshot_hash_mismatch")

        def reference(ref: Reference) -> None:
            if ref.source_revision_id != parsed.source_revision_id:
                raise ValueError("process_reference_revision_mismatch")
            if isinstance(ref, TextSource):
                if ref.snapshot_path != ["case", ref.field]:
                    raise ValueError("process_text_path_mismatch")
                TextReference(ref.field, ref.source_sha256, ref.start, ref.end, ref.quote).validate(sources[ref.field])
            else:
                path = ref.snapshot_path
                if len(path) != 2 or not isinstance(path[0], str) or type(path[1]) is not int:
                    raise ValueError("invalid_process_structured_path")
                snapshot = snapshots[path[0]]
                if ref.source_sha256 != snapshot.sha256 or not 0 <= path[1] < len(snapshot.value):
                    raise ValueError("process_structured_reference_mismatch")
                if canonical(ref.value) != canonical(snapshot.value[path[1]]):
                    raise ValueError("process_structured_value_mismatch")

        def walk(value: Any) -> None:
            if isinstance(value, (TextSource, StructuredSource)):
                reference(value)
            elif isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    walk(getattr(value, name))
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(parsed)
        events = {item.id: item for item in parsed.events}
        if len(events) != len(parsed.events):
            raise ValueError("duplicate_process_event_id")
        for event in events.values():
            for item in [*event.actions, *event.objects, *event.time_intervals, *event.locations, *event.measurements]:
                ref = item.reference
                if (ref.field != event.reference.field or ref.start < event.reference.start
                        or ref.end > event.reference.end):
                    raise ValueError("process_event_reference_outside_context")
            for location in event.locations:
                if location.role != "unknown" and location.role_reference is None:
                    raise ValueError("process_place_role_without_evidence")
                role_ref = location.role_reference
                if role_ref is not None and (role_ref.field != event.reference.field
                        or role_ref.start < event.reference.start or role_ref.end > event.reference.end):
                    raise ValueError("process_place_role_outside_context")
        for relation in parsed.relations:
            left, right = events[relation.from_event_id], events[relation.to_event_id]
            ref = relation.reference
            if (left.id == right.id or left.reference.field != ref.field or right.reference.field != ref.field
                    or ref.start != left.reference.start or ref.end != right.reference.end
                    or left.reference.end > right.reference.start):
                raise ValueError("invalid_process_relation_context")
            if (not left.actions or not right.actions
                    or not re.match(r"\s*(?:首先|先)", left.reference.quote)
                    or not re.match(r"\s*(?:随后|然后|之后|再)", right.reference.quote)
                    or sources[ref.field].text[left.reference.end:right.reference.start].strip()):
                raise ValueError("process_relation_without_explicit_sequence")
        for conflict in parsed.conflicts:
            if not conflict.references or any(event_id not in events for event_id in conflict.event_ids):
                raise ValueError("invalid_process_conflict_context")
            contexts = {canonical(events[event_id].reference.model_dump()) for event_id in conflict.event_ids}
            if any(canonical(ref.model_dump()) not in contexts for ref in conflict.references):
                raise ValueError("process_conflict_reference_outside_context")
        for gap in parsed.gaps:
            if gap.event_id is not None and gap.event_id not in events:
                raise ValueError("invalid_process_gap_event")
        for field in ("locations", "measurements"):
            for item, raw_item in zip(getattr(parsed.structured_context, field), process["structured_context"][field]):
                if item.reference.snapshot_path[0] != field:
                    raise ValueError("process_context_field_mismatch")
                recorded = item.reference.value
                for name in type(item).model_fields:
                    if name not in {"reference", "binding_status"} and canonical(raw_item[name]) != canonical(recorded.get(name)):
                        raise ValueError("process_context_value_mismatch")
    except (ValidationError, KeyError, TypeError, IndexError) as error:
        raise ValueError("invalid_case_process") from error
