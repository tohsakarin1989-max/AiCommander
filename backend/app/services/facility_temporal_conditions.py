"""Read existing facility versions and field decisions over a complete time window.

No historical store is created here. Unknown validity is not an open interval;
current source access is checked before returning values or segment counts.
"""
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import or_

from app.models.map_foundation import (
    FacilitySourceIdentity, JurisdictionAssetVersion, MapFeatureClaim, MapFieldDecision,
)
from app.services.facility_identity_service import _asset, _source, _utc, _iso, _latest_decision

VERSION = "facility-temporal-7.3-1"
GROUP_KEYS = ("geometry", "details", "water_cut", "production")
MAX_RECORDS = 1000
MAX_SEGMENTS = 128
BOUNDARY = "有效期按起点包含、终点不包含；案件不确定区间保留两个端点，不取中点。迟到资料仅在本次已知截止允许时使用；当前权限始终生效。"


def time_window(*, valid_at=None, valid_from=None, valid_to=None):
    if valid_at is not None and (valid_from is not None or valid_to is not None):
        raise ValueError("facility_time_point_and_interval_conflict")
    if (valid_from is None) != (valid_to is None):
        raise ValueError("facility_time_interval_incomplete")
    at, start, end = _utc(valid_at), _utc(valid_from), _utc(valid_to)
    if start is not None and start > end:
        raise ValueError("facility_time_interval_invalid")
    return {"valid_at": _iso(at), "valid_from": _iso(start), "valid_to": _iso(end),
            "time_precision": "exact" if at is not None else "interval" if start is not None else "unknown"}


def case_window(fields):
    precision = fields.get("time_precision")
    try:
        if precision in {"interval", "day"} or (precision is None and not fields.get("occurred_time")):
            return time_window(valid_from=_utc(fields.get("occurred_from"), stored=True), valid_to=_utc(fields.get("occurred_to"), stored=True))
        if precision == "exact" or "time_precision" not in fields:
            return time_window(valid_at=_utc(fields.get("occurred_time"), stored=True))
    except ValueError:
        pass
    return time_window()


def knowledge_context(*, known_at=None, knowledge_mode=None, frozen=False):
    now = datetime.now(timezone.utc)
    mode = knowledge_mode or ("as_known" if known_at is not None else "retrospective")
    if mode not in {"as_known", "retrospective"}:
        raise ValueError("facility_knowledge_mode_invalid")
    if mode == "as_known" and known_at is None:
        raise ValueError("facility_known_at_required")
    if mode == "retrospective" and known_at is not None and not frozen:
        raise ValueError("facility_retrospective_cutoff_is_server_assigned")
    cutoff = _utc(known_at) if known_at is not None else now
    if cutoff > now:
        raise ValueError("future_knowledge_is_not_available")
    return mode, cutoff


def _empty(state="unknown", gap="缺少明确有效期或完整案发时间，保留未知"):
    return {"state": state, "coverage": "unknown", "segments": [], "gaps": [gap]}


def _candidate(group, values, *, start, end, known, source_id, rank, refs, sequence,
               state="set", manual=False, version_id=None, identity_id=None, asset_id=None):
    return {"group": group, "values": values, "start": _utc(start, stored=True),
            "end": _utc(end, stored=True), "known": _utc(known, stored=True),
            "source": source_id, "rank": rank, "refs": refs, "sequence": sequence,
            "lane": ("identity", identity_id) if identity_id is not None else
                    ("source", source_id) if source_id is not None else ("manual", asset_id),
            "state": state, "manual": manual, "version_id": version_id}


def _load(db, asset, known):
    from app.services.map_ingest_plan import _group_values
    active = {}
    for identity in db.query(FacilitySourceIdentity).filter_by(operational_area_id=asset.operational_area_id):
        if _utc(identity.created_at, stored=True) > known:
            continue
        decision = _latest_decision(db, identity.id, known)
        target = decision.target_asset_id if decision else identity.native_asset_id
        if target == asset.id and not (decision and decision.action == "revoke"):
            active[identity.id] = decision.id if decision else None
    versions = db.query(JurisdictionAssetVersion).filter(or_(
        JurisdictionAssetVersion.asset_id == asset.id,
        JurisdictionAssetVersion.source_identity_id.in_(active)),
        JurisdictionAssetVersion.known_at <= known).order_by(JurisdictionAssetVersion.id).limit(MAX_RECORDS + 1).all()
    rows = db.query(MapFieldDecision, MapFeatureClaim).join(
        MapFeatureClaim, MapFeatureClaim.id == MapFieldDecision.claim_id).filter(or_(
            MapFieldDecision.asset_id == asset.id, MapFeatureClaim.source_identity_id.in_(active)),
            MapFieldDecision.known_at <= known).order_by(MapFieldDecision.id).limit(MAX_RECORDS + 1).all()
    if len(versions) > MAX_RECORDS or len(rows) > MAX_RECORDS:
        return None, set()
    candidates, restricted = {key: [] for key in GROUP_KEYS}, set()
    claims_by_id = {claim.id: claim for _, claim in rows}

    def visible(source_id, group):
        if source_id is None:
            return True
        try:
            source = _source(db, source_id)
            if source.operational_area_id != asset.operational_area_id:
                raise PermissionError("facility_scope_denied")
        except (PermissionError, LookupError):
            restricted.add(group)
            return False
        return True

    # Current projection references must not become an ACL side-channel merely
    # because the ORM filtered out the corresponding historical decisions.
    attrs = asset.attributes or {}
    for group in GROUP_KEYS:
        metadata = attrs.get("field_groups", {}).get(group, {})
        visible(metadata.get("source_id", attrs.get("source_id")), group)
    for row in versions:
        if row.source_identity_id is not None and row.source_identity_id not in active:
            continue
        snapshot = row.snapshot or {}
        allowed = db.info.get("authorized_area_ids")
        if allowed is not None and snapshot.get("operational_area_id") not in allowed:
            restricted.update(GROUP_KEYS)
            continue
        attrs = snapshot.get("attributes") or {}
        for group in GROUP_KEYS:
            metadata = attrs.get("field_groups", {}).get(group, {})
            source_id = metadata.get("source_id", attrs.get("source_id"))
            if not visible(source_id, group):
                continue
            # A materialized asset version may carry an unchanged group from
            # another source identity. Keep that group's own provenance lane.
            group_claim = claims_by_id.get(metadata.get("claim_id"))
            identity_id = group_claim.source_identity_id if group_claim is not None else row.source_identity_id
            if identity_id is not None and identity_id not in active:
                continue
            values = _group_values(snapshot, group)
            if group in {"water_cut", "production"} and not metadata and not any(
                    value is not None for key, value in values.items() if not key.startswith("production_valid_")):
                continue
            if group == "details":
                values.update(asset_type=snapshot.get("asset_type"), status=snapshot.get("status"),
                              verified=snapshot.get("verified"))
            if metadata:
                start, end = metadata.get("valid_from"), metadata.get("valid_to")
            elif group in {"water_cut", "production"}:
                start, end = attrs.get("production_valid_from"), attrs.get("production_valid_to")
            else:
                start, end = row.valid_from, row.valid_to
            candidates[group].append(_candidate(group, values, start=start, end=end,
                known=row.known_at, source_id=source_id, rank=metadata.get("trust_rank", attrs.get("source_trust_rank", 90)),
                refs=[f"asset_version:{row.id}"], sequence=(0, row.id), state=metadata.get("state", "set"),
                manual=metadata.get("manual_override", False), version_id=row.id,
                identity_id=identity_id, asset_id=row.asset_id))
    for row, claim in rows:
        if claim.source_identity_id is not None and claim.source_identity_id not in active:
            continue
        group, data = row.group_key, row.payload or {}
        if group not in candidates or row.outcome == "not_provided" or not visible(row.source_id, group):
            continue
        if row.outcome == "conflict" and data.get("reason") != "equal_priority":
            continue  # A rejected proposal is not an adopted historical fact.
        if row.outcome not in {"accepted", "unchanged", "manual", "conflict"}:
            continue
        values = deepcopy(data.get("new") or {})
        if group == "details":
            incoming = claim.normalized_payload or {}
            values.update({key: incoming.get(key) for key in ("asset_type", "status", "verified")})
        refs = [f"map_field_decision:{row.id}", f"map_claim:{claim.id}"]
        if claim.source_identity_id:
            refs.append(f"facility_identity:{claim.source_identity_id}")
        if active.get(claim.source_identity_id):
            refs.append(f"facility_identity_decision:{active[claim.source_identity_id]}")
        candidates[group].append(_candidate(group, values, start=row.valid_from, end=row.valid_to,
            known=row.known_at, source_id=row.source_id, rank=data.get("trust_rank", 0), refs=refs,
            sequence=(1, row.id), state="conflict" if row.outcome == "conflict" else row.state,
            manual=row.outcome == "manual" or data.get("manual_override", False),
            identity_id=claim.source_identity_id, asset_id=row.asset_id))
    return candidates, restricted


def _at(records, at):
    periods = {}
    for row in records:
        if row["start"] is not None and row["start"] > at:
            continue
        key = (row["lane"], row["start"])
        if key not in periods or (row["known"], row["sequence"]) > (periods[key]["known"], periods[key]["sequence"]):
            periods[key] = row
    lanes = {}
    for (lane, start), row in periods.items():
        if row["end"] is not None and at >= row["end"]:
            continue
        if any(other_lane == lane and other_start is not None and start is not None and other_start >= start
               and other["end"] is not None and at >= other["end"] and other["known"] >= row["known"]
               for (other_lane, other_start), other in periods.items()):
            continue
        if lane not in lanes or (row["known"], row["sequence"]) > (lanes[lane]["known"], lanes[lane]["sequence"]):
            lanes[lane] = row
    if not lanes:
        return "unknown", None, []
    priority = max((bool(row["manual"]), row["rank"]) for row in lanes.values())
    choices = [row for row in lanes.values() if (bool(row["manual"]), row["rank"]) == priority]
    if any(row["start"] is None or row["state"] in {"unknown", "clear", "withdraw", "not_provided"} for row in choices):
        return "unknown", None, choices
    if any(row["state"] == "conflict" or row["values"] != choices[0]["values"] for row in choices):
        return "conflict", None, choices
    selected = max(choices, key=lambda row: (row["known"], row["sequence"]))
    return "ready", selected["values"], choices


def _segments(records, start, end):
    boundaries = sorted({start, end, *[value for row in records for value in (row["start"], row["end"])
                                     if value is not None and start < value < end]})
    if len(boundaries) > MAX_SEGMENTS:
        return _empty(gap="历史条件变更超过本次分段预算，未宣称全区间覆盖")
    pieces = [(left, right, False) for left, right in zip(boundaries, boundaries[1:])]
    pieces.append((end, end, True))  # Closed uncertainty interval includes its endpoint.
    segments = []
    for left, right, inclusive in pieces:
        state, values, evidence = _at(records, left)
        segment = {"from": _iso(left), "to": _iso(right), "end_inclusive": inclusive,
                   "state": state, "values": deepcopy(values),
                   "evidence_refs": sorted({ref for row in evidence for ref in row["refs"]}),
                   "source_ids": sorted({row["source"] for row in evidence if row["source"] is not None}),
                   "known_at": _iso(max((row["known"] for row in evidence), default=None)),
                   "late_supplement": any(row["known"] > end for row in evidence),
                   "version_ids": sorted({row["version_id"] for row in evidence if row["version_id"] is not None})}
        segments.append(segment)
    states = {row["state"] for row in segments}
    coverage = "full" if states == {"ready"} else "partial" if "ready" in states else "unknown"
    state = "ready" if coverage == "full" else "partial" if coverage == "partial" else "conflict" if "conflict" in states else "unknown"
    return {"state": state, "coverage": coverage, "segments": segments,
            "gaps": [] if coverage == "full" else ["部分时段无适用资料或存在冲突；不把已覆盖片段当成全案事实"]}


def resolve_conditions(db, asset_id, *, valid_at=None, valid_from=None, valid_to=None,
                       known_at=None, knowledge_mode=None, frozen=False):
    with db.no_autoflush:
        asset = _asset(db, asset_id)
        window = time_window(valid_at=valid_at, valid_from=valid_from, valid_to=valid_to)
        mode, known = knowledge_context(known_at=known_at, knowledge_mode=knowledge_mode, frozen=frozen)
        base = {"schema_version": VERSION, "asset_id": asset_id, **window,
                "query_interval": {"from": window["valid_from"], "to": window["valid_to"]} if window["valid_from"] else None,
                "valid_from": None, "valid_to": None, "known_at": _iso(known),
                "knowledge_mode": mode, "version_id": None, "snapshot": None, "source_claim_id": None,
                "source_identity_id": None, "identity_decision_id": None, "late_supplement": False,
                "boundary": BOUNDARY}
        if window["time_precision"] == "unknown":
            return {**base, "state": "unknown", "coverage": "unknown", "groups": {key: _empty() for key in GROUP_KEYS},
                    "gaps": ["案发时间未知，未默认使用当前或中点资料"]}
        candidates, restricted = _load(db, asset, known)
        if candidates is None:
            return {**base, "state": "unknown", "coverage": "unknown", "groups": {},
                    "gaps": ["历史来源超过本次读取预算，未宣称完整"]}
        start = _utc(valid_at if valid_at is not None else valid_from)
        end = _utc(valid_at if valid_at is not None else valid_to)
        groups = {key: _empty("restricted", "当前来源不可访问，不返回值或分段数量") if key in restricted else
                  _segments(records, start, end) for key, records in candidates.items()}
        relevant = [groups[key] for key in GROUP_KEYS if candidates[key] or key in {"geometry", "details"}]
        full = all(row["coverage"] == "full" for row in relevant)
        any_ready = any(row["coverage"] in {"full", "partial"} for row in relevant)
        state = "conflict" if any(row["state"] == "conflict" for row in relevant) else "ready" if full else "partial" if any_ready else "restricted" if restricted else "unknown"
        snapshot = None
        version_ids = set()
        if valid_at is not None:
            from app.services.map_ingest_plan import _set_values
            snapshot = {"id": asset_id, "operational_area_id": asset.operational_area_id, "attributes": {}}
            for key, group in groups.items():
                if group["coverage"] != "full":
                    continue
                values = group["segments"][0]["values"]
                _set_values(snapshot, key, values)
                if key == "details":
                    snapshot.update({field: values.get(field) for field in ("asset_type", "status", "verified")})
                if key in {"water_cut", "production"}:
                    snapshot["attributes"]["field_groups"] = {**snapshot["attributes"].get("field_groups", {}),
                        key: {"valid_from": values.get("production_valid_from"), "valid_to": values.get("production_valid_to")}}
                version_ids.update(group["segments"][0]["version_ids"])
            if not any_ready:
                snapshot = None
        return {**base, "state": state, "snapshot": snapshot,
                "version_id": next(iter(version_ids)) if len(version_ids) == 1 else None,
                "supporting_version_ids": sorted(version_ids),
                "coverage": "full" if full else "partial" if any_ready else "unknown", "groups": groups,
                "late_supplement": any(segment["late_supplement"] for group in groups.values() for segment in group["segments"]),
                "gaps": sorted({gap for group in relevant for gap in group["gaps"]})}


def group_match(context, group, predicate):
    """Only uniform evidence over the whole interval supplies a positive/negative match."""
    value = context.get("groups", {}).get(group, {})
    if value.get("coverage") != "full":
        return "unknown"
    results = {predicate(row["values"]) for row in value["segments"]}
    return "matched" if results == {True} else "different" if results == {False} else "unknown"


def validate_temporal_access(db, context):
    """Frozen values remain frozen, but their current read permission does not."""
    import re
    from app.services.facility_source_access import attributes_sources_visible
    asset = _asset(db, context["asset_id"])
    for group in context.get("groups", {}).values():
        for segment in group.get("segments", []):
            for ref in segment.get("evidence_refs", []):
                match = re.fullmatch(r"(map_field_decision|map_claim|asset_version|facility_identity|facility_identity_decision):([1-9][0-9]*)", ref)
                if not match:
                    raise PermissionError("facility_temporal_reference_invalid")
                kind, identifier = match[1], int(match[2])
                if kind == "map_field_decision":
                    row = db.query(MapFieldDecision).populate_existing().filter_by(id=identifier).first()
                    if row is None:
                        raise PermissionError("facility_temporal_source_unavailable")
                    _source(db, row.source_id)
                elif kind == "map_claim":
                    row = db.query(MapFeatureClaim).populate_existing().filter_by(id=identifier).first()
                    if row is None:
                        raise PermissionError("facility_temporal_source_unavailable")
                    _source(db, row.source_id)
                elif kind == "asset_version":
                    row = db.query(JurisdictionAssetVersion).populate_existing().filter_by(id=identifier).first()
                    allowed = db.info.get("authorized_area_ids")
                    if (row is None or (allowed is not None and (row.snapshot or {}).get("operational_area_id") not in allowed)
                            or not attributes_sources_visible(db, (row.snapshot or {}).get("attributes") or {}, asset.operational_area_id)):
                        raise PermissionError("facility_temporal_source_unavailable")
                else:
                    from app.models.map_foundation import FacilityIdentityDecision
                    model = FacilitySourceIdentity if kind == "facility_identity" else FacilityIdentityDecision
                    row = db.query(model).filter_by(id=identifier).first()
                    if row is None:
                        raise PermissionError("facility_temporal_source_unavailable")
