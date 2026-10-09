"""Administrator-declared ledger coverage, never an inferred facility lifecycle."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapIngestRun, OperationalArea


class LedgerDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["full", "incremental"]
    scope_key: str = Field(min_length=1, max_length=100)
    scope_description: str = Field(min_length=1, max_length=300)
    valid_from: AwareDatetime
    valid_to: AwareDatetime

    @model_validator(mode="after")
    def ordered_period(self):
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


def parse_declaration(value):
    if value is None:
        return None
    try:
        data = LedgerDeclaration.model_validate_json(value) if isinstance(value, str) else LedgerDeclaration.model_validate(value)
    except (ValidationError, ValueError):
        raise ValueError("invalid_ledger_declaration|台账声明须明确完整或增量、稳定范围编号、范围说明及带时区的有效起止时间") from None
    return {**data.model_dump(mode="json"), "valid_from": data.valid_from.astimezone(timezone.utc).isoformat(),
            "valid_to": data.valid_to.astimezone(timezone.utc).isoformat()}


def _status(reason, *, phase="preview"):
    return {"schema_version": "ledger-comparison-8.1-1", "status": "not_comparable", "reason": reason,
            "phase": phase, "boundary": "未出现仅待核，不表示停产、撤销或删除；完整性来自管理员声明，不是单元格原文"}


def _scope(declaration):
    return tuple(declaration.get(key) for key in ("source_id", "operational_area_id", "scope_key", "scope_description"))


def _instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _received_order(run):
    value = run.completed_at or run.started_at
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _accessible_assets(db, identifiers):
    identifiers = set(identifiers)
    if not identifiers or None in identifiers:
        return False
    visible = {identifier for (identifier,) in db.query(JurisdictionAsset.id).filter(JurisdictionAsset.id.in_(identifiers))}
    return visible == identifiers


def _compare(db, source, plan, declaration):
    if declaration is None:
        return _status("coverage_unknown")
    if declaration["mode"] != "full":
        return _status("incremental")
    rows = plan["rows"]
    allowed = {"new", "updated", "unchanged"}
    identifiers = [(row.get("normalized_payload") or {}).get("external_id") for row in rows]
    if not rows or any(row["classification"] not in allowed for row in rows) or not all(identifiers) or len(set(identifiers)) != len(rows):
        return _status("current_rows_incomplete")
    roots = db.query(MapIngestRun).filter_by(source_id=source.id, parent_run_id=None).filter(
        MapIngestRun.status.in_(['completed', 'completed_with_errors'])).all()
    declared = [(run, (run.table_metadata or {}).get("ledger_declaration")) for run in roots]
    same = [(run, previous) for run, previous in declared if previous and _scope(previous) == _scope(declaration)]
    start = _instant(declaration["valid_from"])
    if any(_instant(previous["valid_from"]) <= start < _instant(previous["valid_to"]) for _, previous in same):
        return _status("overlapping_period")
    preceding = [(run, previous) for run, previous in same if _instant(previous["valid_to"]) <= start]
    if not preceding:
        return _status("no_previous_comparable_ledger")
    last_end = max(_instant(previous["valid_to"]) for _, previous in preceding)
    preceding = [(run, previous) for run, previous in preceding if _instant(previous["valid_to"]) == last_end]
    if len(preceding) != 1:
        return _status("ambiguous_previous_period")
    previous_run, previous = preceding[0]
    if last_end != start:
        return _status("period_gap")
    if previous["mode"] != "full":
        return _status("previous_not_full")
    if any(not old and _received_order(run) > _received_order(previous_run) for run, old in declared):
        return _status("intervening_coverage_unknown")
    if previous_run.status != "completed" or previous_run.quarantined_rows:
        return _status("previous_rows_incomplete")
    if previous.get("identity_column") != declaration.get("identity_column"):
        return _status("identity_mapping_changed")
    claims = db.query(MapFeatureClaim).filter_by(run_id=previous_run.id).order_by(MapFeatureClaim.row_number).all()
    old_ids = [claim.source_record_id for claim in claims]
    if not claims or len(claims) != previous_run.total_rows or not all(old_ids) or len(set(old_ids)) != len(claims) or any(
            (claim.plan or {}).get("classification") not in allowed for claim in claims):
        return _status("previous_rows_incomplete")
    if not _accessible_assets(db, [claim.asset_id for claim in claims]):
        return _status("data_restricted_or_unavailable")
    current_identifiers = set(identifiers)
    missing = [{"source_record_id": claim.source_record_id, "claim_id": claim.id, "asset_id": claim.asset_id,
                "row_number": claim.row_number} for claim in claims if claim.source_record_id not in current_identifiers]
    return {**_status("adjacent_full_ledgers"), "status": "comparable", "basis_area_id": source.operational_area_id,
            "baseline_run_id": previous_run.id, "baseline_source_revision": previous_run.source_revision,
            "baseline_declaration": previous, "missing": missing, "missing_count": len(missing),
            "previous_count": len(claims), "current_count": len(rows)}


def declare_plan(db, source, template, plan, value):
    """Bind comparison and declaration into the exact same preview / write token."""
    declaration = parse_declaration(value)
    if declaration is None:
        return plan
    area = db.query(OperationalArea).filter_by(id=source.operational_area_id, status="active").first()
    if area is None:
        raise ValueError("operational_area_not_found")
    declaration = {**declaration, "schema_version": "ledger-declaration-8.1-1", "origin": "administrator_declaration",
                   "source_id": source.id, "operational_area_id": source.operational_area_id,
                   "identity_column": (template.field_mapping or {}).get("external_id") if template else None}
    comparison = _compare(db, source, plan, declaration)
    plan["structure"] = {**plan["structure"], "ledger_declaration": declaration, "ledger_comparison": comparison}
    from app.services.map_foundation_service import MapFoundationService
    plan["plan_token"] = MapFoundationService._hash_json({"base": plan["plan_token"], "declaration": declaration, "comparison": comparison})
    plan["ledger_declaration"] = declaration
    plan["ledger_comparison"] = public_comparison(comparison)
    return plan


def public_comparison(value):
    value = deepcopy(value)
    if "missing" in value:
        value["missing"] = value["missing"][:200]
        value["rows_complete"] = value["missing_count"] <= 200
    return value


def correction_metadata(metadata):
    """Corrected subsets must never inherit a complete-ledger declaration."""
    return {key: deepcopy(value) for key, value in (metadata or {}).items() if key not in {"ledger_declaration", "ledger_comparison"}}


def read_comparison(db, run_id):
    from app.services.map_foundation_service import MapFoundationService
    from app.services.map_ingest_execution import get_run
    run = get_run(db, run_id)
    source = MapFoundationService._get_source(db, run.source_id)
    area = db.query(OperationalArea).filter_by(id=source.operational_area_id, status="active").first()
    if area is None:
        raise ValueError("operational_area_not_found")
    if run.parent_run_id:
        return _status("correction_subset", phase="executed")
    value = deepcopy((run.table_metadata or {}).get("ledger_comparison") or _status("coverage_unknown"))
    value["phase"] = "executed"
    if value.get("status") != "comparable":
        return public_comparison(value)
    if run.status != "completed" or run.quarantined_rows:
        return _status("current_rows_incomplete", phase="executed")
    if value.get("basis_area_id") != source.operational_area_id:
        return _status("scope_changed", phase="executed")
    try:
        baseline = get_run(db, value["baseline_run_id"])
    except ValueError:
        return _status("data_restricted_or_unavailable", phase="executed")
    if baseline.source_id != source.id:
        return _status("data_restricted_or_unavailable", phase="executed")
    # Re-authorize all source facilities, not only the first 200 displayed rows.
    ids = [identifier for (identifier,) in db.query(MapFeatureClaim.asset_id).filter(
        MapFeatureClaim.run_id.in_([run.id, baseline.id]))]
    if not _accessible_assets(db, ids):
        return _status("data_restricted_or_unavailable", phase="executed")
    return public_comparison(value)
