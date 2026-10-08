"""Read-only ledger plans shared by preview and execution.

No source row or facility is created while planning. A plan token binds the
complete file, template, source, boundary and every resolved object/version.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, MapFieldDecision, MapIngestRun, MapSource, OperationalArea
from app.services.facility_identity_service import FacilityIdentityService
from app.services.map_import_contract import GROUPS, VALUE_STATES, detect_drift


CATEGORIES = ("new", "updated", "unchanged", "identity_pending", "conflict", "failed")
PRODUCTION_DATES = ("production_valid_from", "production_valid_to")
DETAIL_FIELDS = ("oil_type", "owner_unit", "production_unit", "production_status", "facility_category", "is_high_production")
GEOMETRY_FIELDS = ("longitude", "latitude", "geometry", "coordinate_system", "accuracy_m")


def _service():
    from app.services.map_foundation_service import MapFoundationService
    return MapFoundationService


def _state(raw, template, group):
    mapping = template.field_mapping or {}
    value = raw.get(mapping.get(group + "_state"))
    if value not in (None, ""):
        value = str(value).strip()
        if value not in VALUE_STATES:
            raise ValueError(f"invalid_group_state|{group}_state 必须是 set/not_provided/unknown/clear/withdraw")
        return value
    if group == "geometry":
        return "set"  # Coordinates remain mandatory unless explicitly withheld.
    return "set" if any(raw.get(mapping.get(key)) not in (None, "") for key in GROUPS[group]) else "not_provided"


def normalize(source, template, raw, boundary):
    service = _service()
    states = {key: _state(raw, template, key) for key in GROUPS}
    clean = deepcopy(raw)
    for group, state in states.items():
        if state != "set":
            for key in GROUPS[group]:
                if key in template.field_mapping:
                    clean[template.field_mapping[key]] = None
    for key, expected in {"coordinate_system": template.coordinate_system, "coordinate_unit": template.coordinate_unit,
                          **(template.field_units or {})}.items():
        if key.startswith("coordinate_") and states["geometry"] != "set":
            continue
        declared = raw.get(template.field_mapping.get(key))
        if declared not in (None, "") and str(declared).strip() != expected:
            raise ValueError(f"field_declaration_drift|{key} 的声明与已确认模板不一致")
    value = service._normalize_row(source, template, clean,
                                  area_boundary=boundary, geometry_state=states["geometry"])
    if states["geometry"] != "set":
        for key in GEOMETRY_FIELDS:
            value[key] = None
        value["verified"] = False
        value["verification_state"] = "geometry_" + states["geometry"]
    return value, states


def resolve_asset(db, source, value):
    """Same identity rules as the existing importer, without ensure/create."""
    identity, decision, asset = FacilityIdentityService.resolve_import(db, source=source, normalized=value)
    if asset is None:
        asset = db.query(JurisdictionAsset).populate_existing().filter_by(canonical_key=value["canonical_key"]).first()
    if identity is None and asset is not None and (
        asset.external_id != value.get("external_id") or (asset.attributes or {}).get("source_id") != source.id
    ):
        raise ValueError("asset_identity_conflict|稳定标识与来源身份不一致")
    if asset is None:
        query = db.query(JurisdictionAsset).populate_existing().filter_by(
            operational_area_id=source.operational_area_id, external_id=value.get("external_id"))
        if not value.get("external_id"):
            query = query.filter_by(name=value["name"], asset_type=value["asset_type"],
                                   latitude=value["latitude"], longitude=value["longitude"])
        matches = [row for row in query.all() if (row.attributes or {}).get("source_id") == source.id]
        if len(matches) > 1:
            raise ValueError("ambiguous_asset_identity|来源内稳定标识重复，需人工核验")
        asset = matches[0] if matches else None
    if asset and asset.asset_type != value["asset_type"]:
        raise ValueError("facility_identity_type_or_area_changed|稳定编号的设施类型已变化，需人工核验")
    if asset and not value.get("external_id") and asset.verified:
        raise ValueError("asset_identity_requires_review|无稳定编号不能覆盖已核验设施")
    return asset, identity, decision


def _group_values(value, group, template=None):
    attrs = value.get("attributes") or {}
    if group == "geometry":
        return {**{key: value.get(key) for key in GEOMETRY_FIELDS},
                "original_coordinate_system": attrs.get("original_coordinate_system"),
                "coordinate_unit": template.coordinate_unit if template else attrs.get("original_coordinate_unit"),
                "transformation": template.transformation if template else attrs.get("coordinate_transformation")}
    if group == "details":
        return {"name": value.get("name"), "address": value.get("address"),
                **{key: attrs.get(key) for key in DETAIL_FIELDS}}
    return {key: attrs.get(key) for key in (*GROUPS[group], *PRODUCTION_DATES)}


def _set_values(value, group, values):
    attrs = value["attributes"]
    if group == "geometry":
        for key in GEOMETRY_FIELDS:
            value[key] = values.get(key)
        for target, key in (("original_coordinate_system", "original_coordinate_system"),
                            ("original_coordinate_unit", "coordinate_unit"), ("coordinate_transformation", "transformation")):
            attrs[target] = values.get(key)
    elif group == "details":
        for key in ("name", "address"):
            if values.get(key) is not None:
                value[key] = values[key]
        for key in DETAIL_FIELDS:
            if values.get(key) is not None:
                attrs[key] = values[key]
    else:
        for key in GROUPS[group]:
            attrs.pop(key, None)
        attrs.update({key: values[key] for key in GROUPS[group] if values.get(key) is not None})


def authority(db, asset, group, before, metadata, fallback_source, fallback_rank):
    """Same-value higher-trust receipts govern future adoption without touching assets."""
    if asset is None:
        return None, 0, None, False
    latest = {}
    for row in db.query(MapFieldDecision).filter_by(asset_id=asset.id, group_key=group).order_by(MapFieldDecision.id.desc()):
        if row.source_id in latest or row.outcome == "not_provided":
            continue
        latest[row.source_id] = row
    candidates = []
    for row in latest.values():
        if row.outcome not in {"accepted", "unchanged", "manual"} or row.state not in {"set", "unknown", "clear", "withdraw"}:
            continue
        def instant(value):
            return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
        now = datetime.now(timezone.utc)
        if (row.valid_from and instant(row.valid_from) > now) or (row.valid_to and instant(row.valid_to) <= now):
            continue
        if (row.payload or {}).get("new") != before:
            continue
        origin = db.query(MapSource).filter_by(id=row.source_id, status="active").first()
        if origin is None:
            continue
        candidates.append((bool(row.outcome == "manual" or row.payload.get("manual_override")),
                           int(row.payload.get("trust_rank", origin.trust_rank)), row.id, row.source_id))
    if candidates:
        manual, rank, identifier, source_id = max(candidates)
        if manual or rank >= fallback_rank:
            return source_id, rank, identifier, manual
    return fallback_source, fallback_rank, metadata.get("decision_id"), bool(metadata.get("manual_override"))


def group_plan(db, source, template, raw, incoming, states, asset):
    service = _service()
    old = service.asset_to_dict(asset) if asset else {}
    merged = deepcopy(incoming if asset is None else old)
    merged["attributes"] = deepcopy(merged.get("attributes") or {})
    previous = (old.get("attributes") or {}).get("field_groups") or {}
    group_meta = deepcopy(previous)
    groups, changes = [], []
    old_rank = int((old.get("attributes") or {}).get("source_trust_rank", 0))
    old_source = (old.get("attributes") or {}).get("source_id")
    for group in (*GROUPS, "details"):
        state = states.get(group, "set")
        before = _group_values(old, group)
        metadata = previous.get(group) or {}
        # Older records have a known original CRS but no unit field. No new
        # numeric conversion is inferred; use the same template only for its owner.
        if group == "geometry" and not metadata and old_source == source.id:
            before["coordinate_unit"] = before.get("coordinate_unit") or template.coordinate_unit
            before["transformation"] = before.get("transformation") or template.transformation
        after = _group_values(incoming, group, template)
        if group == "details" and asset:
            after = {key: after.get(key) if after.get(key) is not None else value for key, value in before.items()}
        if state in {"unknown", "clear", "withdraw"}:
            after = {key: None for key in after}
        rank = int(metadata.get("trust_rank", old_rank))
        origin = metadata.get("source_id", old_source)
        if group in GROUPS and not metadata and not any(before.get(key) is not None for key in GROUPS[group]):
            rank, origin = 0, None
        origin, rank, previous_decision_id, manual = authority(db, asset, group, before, metadata, origin, rank)
        old_state = metadata.get("state", "set" if any(v is not None for v in before.values()) else "not_provided")
        if asset and not metadata and old_state != "not_provided":
            # Persist a legacy group's incumbent when a different group changes;
            # changing the row-level source must not silently demote its owner.
            group_meta[group] = {"source_id": origin, "trust_rank": rank, "state": old_state,
                                 "decision_id": previous_decision_id, "manual_override": manual,
                                 "valid_from": before.get("production_valid_from", old.get("valid_from")),
                                 "valid_to": before.get("production_valid_to", old.get("valid_to"))}
        status, reason = "accepted", "same_source_update" if origin == source.id else "source_priority"
        if state == "not_provided":
            status, reason = "not_provided", "未提供不覆盖已有值"
        elif asset and before == after and state == old_state:
            status, reason = "unchanged", "same_values"
        elif manual and origin != source.id:
            status, reason = "conflict", "manual_group_decision"
        elif old_state == "conflict" and source.trust_rank <= rank:
            status, reason = "conflict", "unresolved_equal_priority"
        elif asset and source.trust_rank < rank and origin != source.id:
            status, reason = "conflict", "lower_priority"
        elif asset and source.trust_rank == rank and origin not in {None, source.id} and (before != after or state != old_state):
            status, reason = "conflict", "equal_priority"
        elif state == "withdraw" and origin not in {None, source.id}:
            status, reason = "conflict", "withdraw_other_source_forbidden"
        elif group in {"water_cut", "production"} and state == "set" and any(
            before.get(key) is not None and after.get(key) is not None and before[key] != after[key]
            for key in ("water_cut_unit", "water_cut_basis", "production_output_unit", "production_period", "production_basis")
        ):
            status, reason = "conflict", "unit_or_basis_changed_requires_confirmation"
        elif group in {"water_cut", "production"} and state == "set" and asset and any(
            before.get(key) is not None and after.get(key) is None for key in GROUPS[group]
        ):
            status, reason = "conflict", "incomplete_coupled_group"
        row = {"group": group, "state": state, "status": status, "reason": reason,
               "old": before, "new": after, "previous_decision_id": previous_decision_id,
               "previous_source_id": origin, "source_id": source.id, "trust_rank": source.trust_rank,
               "manual_override": manual and origin == source.id}
        groups.append(row)
        if status == "accepted":
            _set_values(merged, group, after)
            group_meta[group] = {"state": state, "source_id": source.id, "trust_rank": source.trust_rank,
                                 "manual_override": manual and origin == source.id,
                                 "valid_from": after.get("production_valid_from", incoming.get("valid_from")),
                                 "valid_to": after.get("production_valid_to", incoming.get("valid_to"))}
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    changes.append({"field": key, "group": group, "old": before.get(key), "new": after.get(key)})
            if state != old_state:
                changes.append({"field": group + "_state", "group": group, "old": old_state, "new": state})
        elif status == "conflict" and reason == "equal_priority":
            # Quarantine this disputed group only, never the rest of the object.
            if metadata.get("state") != "conflict":
                _set_values(merged, group, {key: None for key in before})
                group_meta[group] = {**metadata, "state": "conflict", "source_id": origin, "trust_rank": rank}
                changes.append({"field": group + "_state", "group": group, "old": old_state, "new": "conflict"})
    merged["attributes"]["field_groups"] = group_meta
    # Shared legacy dates must not claim one group's interval for another group.
    intervals = {(meta.get("valid_from"), meta.get("valid_to")) for key, meta in group_meta.items()
                 if key in {"water_cut", "production"} and meta.get("state") == "set"}
    for index, key in enumerate(PRODUCTION_DATES):
        value = next(iter(intervals))[index] if len(intervals) == 1 else None
        if value is not None:
            merged["attributes"][key] = value
        else:
            merged["attributes"].pop(key, None)
    geometry_state = group_meta.get("geometry", {}).get("state", "set")
    if geometry_state != "set":
        merged["verified"] = False
        merged["verification_state"] = "geometry_" + geometry_state
    elif any(row["group"] == "geometry" and row["status"] in {"accepted", "unchanged"} for row in groups):
        merged["verified"] = incoming["verified"]
        merged["verification_state"] = incoming["verification_state"]
    # Overall validity belongs to this observation, not the upload timestamp.
    for key in ("valid_from", "valid_to"):
        if asset is None or any(incoming.get(field) is not None for field in ("valid_from", "valid_to")):
            if old.get(key) != incoming.get(key):
                changes.append({"field": key, "group": "validity", "old": old.get(key), "new": incoming.get(key)})
            merged[key] = incoming.get(key)
    return merged, groups, changes


def promotion_target(db, source, parent, incoming):
    """Explicit correction lineage, not a name/coordinate identity guess."""
    if parent.source_id != source.id or parent.source_record_id or parent.status != "identity_pending":
        raise ValueError("retry_parent_stale|父行不是仍待补号的来源记录")
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=parent.asset_id).first()
    if (asset is None or asset.external_id is not None or asset.verified
            or asset.verification_state != "identity_pending"
            or (asset.attributes or {}).get("source_id") != source.id):
        raise ValueError("retry_parent_stale|父行对应设施已变更、补号或核验，请刷新后处理")
    _, _, target = FacilityIdentityService.resolve_import(db, source=source, normalized=parent.normalized_payload)
    if target is None or target.id != asset.id:
        raise ValueError("retry_parent_stale|父行来源身份已重新对应，不能补号")
    latest = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id).order_by(JurisdictionAssetVersion.version.desc()).first()
    if latest is None or latest.source_claim_id != parent.id:
        raise ValueError("retry_parent_stale|父行不再是当前设施的来源版本")
    from app.models.map_foundation import FacilitySourceIdentity
    key = "id:" + incoming["external_id"]
    if db.query(FacilitySourceIdentity.id).filter_by(source_id=source.id, identity_key=key).first():
        raise ValueError("retry_identifier_taken|该来源编号已经占用，不得自动合并")
    occupied, _, _ = resolve_asset(db, source, incoming)
    if occupied is not None:
        raise ValueError("retry_identifier_taken|该来源编号已经占用，不得自动合并")
    return asset


def make_plan(db, source, template, rows, structure, *, file_hash, promotions=None):
    service = _service()
    area = db.query(OperationalArea).populate_existing().filter_by(id=source.operational_area_id).first()
    drift = detect_drift(template, structure) if template else []
    if template and not template.expected_structure:
        previous = db.query(MapIngestRun).filter_by(source_id=source.id, template_id=template.id).filter(
            MapIngestRun.table_metadata.isnot(None)).order_by(MapIngestRun.started_at.desc(), MapIngestRun.id.desc()).first()
        if previous and previous.table_metadata != structure:
            drift.append({"field": "headers", "code": "header_drift", "message": "与该模板上次导入结构不同，请确认新模板",
                          "old": previous.table_metadata, "new": structure})
    entries = []
    identifiers = Counter(str(raw.get((template.field_mapping or {}).get("external_id"))).strip()
                          for _, raw in rows if template and raw.get((template.field_mapping or {}).get("external_id")) not in (None, ""))
    for number, raw in rows:
        entry = {"row_number": number, "classification": "failed", "asset_id": None, "asset_version": None,
                 "changes": [], "groups": [], "errors": []}
        try:
            if template is None:
                raise ValueError("coordinate_system_required|必须先由地图管理员确认字段和坐标系模板")
            if drift:
                raise ValueError("template_drift|文件结构发生变化，需重新确认模板")
            external = str(raw.get(template.field_mapping.get("external_id")) or "").strip()
            if external and identifiers[external] > 1:
                raise ValueError("duplicate_source_identity|同一批次稳定编号重复，需逐行核对，未按最后一行覆盖")
            incoming, states = normalize(source, template, raw, area.boundary if area else None)
            asset, identity, decision = resolve_asset(db, source, incoming)
            promotion = (promotions or {}).get(number)
            if promotion is not None:
                asset = promotion_target(db, source, promotion, incoming)
            latest = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id).order_by(
                JurisdictionAssetVersion.version.desc()).first() if asset else None
            resolved, groups, changes = group_plan(db, source, template, raw, incoming, states, asset)
            if promotion is not None:
                resolved["external_id"] = incoming["external_id"]
                resolved["canonical_key"] = incoming["canonical_key"]
                changes.append({"field": "external_id", "group": "identity", "old": None,
                                "new": incoming["external_id"], "reason": "沿明确父行对应的原设施补稳定编号"})
            category = ("conflict" if any(group["status"] == "conflict" for group in groups)
                        else "identity_pending" if not incoming.get("external_id")
                        else "new" if asset is None else "updated" if changes else "unchanged")
            entry.update(classification=category, asset_id=asset.id if asset else None,
                         asset_version=latest.version if latest else None,
                         source_identity_id=identity.id if identity else None, identity_decision_id=decision.id if decision else None,
                         changes=changes, groups=groups, normalized_payload=incoming, resolved_payload=resolved,
                         promotion_parent_claim_id=promotion.id if promotion is not None else None,
                         base_hash=service._hash_json(service.asset_to_dict(asset)) if asset else None)
        except (ValueError, LookupError) as exc:
            code, message = service._error_parts(exc)
            field = ("geometry" if "coordinate" in code or "outside_" in code else "water_cut" if "water_cut" in code
                     else "production_output" if "production_output" in code else "external_id" if "identity" in code else "row")
            field = {"missing_name": "name", "missing_asset_type": "asset_type",
                     "invalid_high_production": "is_high_production", "invalid_production_time": "production_validity"}.get(code, field)
            if code in {"field_declaration_drift", "invalid_group_state"}:
                field = message.split(" ", 1)[0]
            entry["errors"] = [{"field": field, "code": code, "message": message}]
        entries.append(entry)
    resolved_ids = Counter(row["asset_id"] for row in entries if row.get("asset_id") is not None)
    for row in entries:
        if row.get("asset_id") is not None and resolved_ids[row["asset_id"]] > 1:
            row["classification"] = "failed"
            row["errors"] = [{"field": "external_id", "code": "duplicate_resolved_facility",
                              "message": "多行来源编号指向同一设施，请分开核验后再导入"}]
    counts = {key: sum(row["classification"] == key for row in entries) for key in CATEGORIES}
    token = service._hash_json({"schema": "map-plan-7.2-1", "file_hash": file_hash,
        "template": service.template_to_dict(template) if template else None,
        "source": [source.id, source.source_key, source.source_type, source.trust_rank, source.status, source.configuration],
        "boundary": area.boundary if area else None, "structure": structure, "drift": drift, "rows": entries})
    return {"source_id": source.id, "template_id": template.id if template else None,
            "plan_token": token, "structure": structure, "drift": drift, "counts": counts, "rows": entries,
            "publishable": bool(entries) and not drift and counts["failed"] < len(entries),
            "total_rows": len(entries), "valid_rows": len(entries) - counts["failed"] - counts["conflict"],
            "quarantined_rows": counts["failed"] + counts["conflict"],
            "errors": [{"row": row["row_number"], **error} for row in entries for error in row["errors"]],
            "sample": [row.get("normalized_payload") for row in entries if row.get("normalized_payload")][:10]}


def public_plan(plan):
    return {**plan, "rows": [{key: value for key, value in row.items() if key not in {"resolved_payload", "normalized_payload", "base_hash"}}
                             for row in plan["rows"][:200]],
            "rows_complete": len(plan["rows"]) <= 200}
