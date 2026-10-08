"""Transactional execution and append-only row corrections for ledger plans."""
import hashlib
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    MapFeatureClaim, MapFieldDecision, MapIngestRun, MapSource, OperationalArea,
)
from app.services.facility_identity_service import FacilityIdentityService
from app.services.map_ingest_plan import make_plan, public_plan, resolve_asset, authority, _group_values, _set_values, promotion_target, normalize


def _service():
    from app.services.map_foundation_service import MapFoundationService
    return MapFoundationService


def source_for_write(db, source_id, actor_id=None):
    """Serialize facility mutations and re-read the current scoped source."""
    service = _service()
    source = service._get_source(db, source_id)
    area_query = db.query(OperationalArea).filter_by(id=source.operational_area_id)
    if db.bind.dialect.name == "postgresql":
        area_query = area_query.with_for_update()
    if area_query.populate_existing().first() is None:
        raise ValueError("operational_area_not_found")
    if actor_id is not None:
        from app.models.user import User
        actor = db.query(User).populate_existing().filter_by(id=actor_id).first()
        if actor is None or not actor.is_active or actor.role != "admin":
            raise PermissionError("map_admin_required|当前账户不再具有地图管理权限")
        if db.info.get("principal_user_id") not in {None, actor_id}:
            raise PermissionError("map_actor_mismatch|不能借用其他账号处理台账")
    from app.database import require_area_write_access
    # Legacy trusted service tests don't bind a request principal/scope.
    if "authorized_area_ids" in db.info or db.info.get("principal_user_id") is not None:
        require_area_write_access(db, source.operational_area_id)
    return service._get_source(db, source_id)


def get_run(db, run_id):
    row = db.query(MapIngestRun).join(MapSource, MapSource.id == MapIngestRun.source_id).filter(
        MapIngestRun.id == run_id).populate_existing().first()
    if row is None:
        raise ValueError("map_ingest_run_not_found")
    return row


def _execute(db, *, source, template, rows, plan, file_hash, filename, revision, key, created_by,
             content=None, parent=None, parents=None, note=None, request_sha256=None):
    service = _service()
    run = MapIngestRun(id=str(uuid.uuid4()), source_id=source.id, template_id=template.id,
        filename=filename[:255], source_revision=revision, file_hash=file_hash, idempotency_key=key,
        status="running", total_rows=len(rows), valid_rows=0, quarantined_rows=0, created_assets=0,
        updated_assets=0, created_by=created_by, table_metadata=plan["structure"],
        request_sha256=request_sha256,
        template_snapshot={key: service._json_safe(value) for key, value in service.template_to_dict(template).items()},
        classification_counts=plan["counts"], parent_run_id=parent.id if parent else None,
        original_evidence_object_id=parent.original_evidence_object_id if parent else None)
    db.add(run)
    db.flush()
    if content is not None:
        from app.services.map_ingest_originals import capture_original
        capture_original(db, run, content=content, filename=filename)
    errors = []
    for (number, raw), item in zip(rows, plan["rows"]):
        claim = MapFeatureClaim(run_id=run.id, source_id=source.id, row_number=number,
            source_record_id=service._clean_string(service._mapped_value(raw, template.field_mapping, "external_id")),
            source_revision=revision, raw_payload=deepcopy(raw), raw_hash=service._hash_json(raw),
            normalized_payload=deepcopy(item.get("normalized_payload")),
            plan={key: value for key, value in item.items() if key not in {"resolved_payload", "base_hash", "normalized_payload"}},
            parent_claim_id=(parents or {}).get(number), correction_note=note,
            status="quarantined" if item["classification"] == "failed" else item["classification"])
        db.add(claim)
        db.flush()
        if item["classification"] == "failed":
            claim.error_code = item["errors"][0]["code"]
            claim.error_message = item["errors"][0]["message"]
            errors.extend({"row": number, **error} for error in item["errors"])
            run.quarantined_rows += 1
            continue
        incoming = item["normalized_payload"]
        if item.get("promotion_parent_claim_id") is not None:
            parent_claim = db.query(MapFeatureClaim).filter_by(id=item["promotion_parent_claim_id"]).one()
            promoted = promotion_target(db, source, parent_claim, incoming)
            promoted.external_id = incoming["external_id"]
            promoted.canonical_key = incoming["canonical_key"]
            FacilityIdentityService.ensure_identity(db, source=source, asset=promoted, normalized=incoming)
            db.flush()
        asset, identity, decision = resolve_asset(db, source, incoming)
        changed = asset is None or bool(item["changes"])
        if changed:
            resolved = deepcopy(item["resolved_payload"])
            asset, created, _ = service._merge_asset(db, source=source, claim=claim,
                                                    normalized=incoming, resolved_payload=resolved)
            run.created_assets += int(created)
            run.updated_assets += int(not created)
        else:
            identity = identity or FacilityIdentityService.ensure_identity(db, source=source, asset=asset, normalized=incoming)
            claim.source_identity_id = identity.id
            claim.identity_decision_id = decision.id if decision else None
        claim.asset_id = asset.id
        # Every receipt has its own immutable adoption decisions, even when the
        # standard asset itself was unchanged. This preserves a new revision
        # without rewriting the facility or waking derived calculations.
        records = {}
        for group in item["groups"]:
            row = MapFieldDecision(asset_id=asset.id, source_id=source.id, claim_id=claim.id,
                group_key=group["group"], state=group["state"], outcome=group["status"],
                payload=deepcopy(group), previous_decision_id=group.get("previous_decision_id"),
                valid_from=_time(group["new"].get("production_valid_from", incoming.get("valid_from"))),
                valid_to=_time(group["new"].get("production_valid_to", incoming.get("valid_to"))))
            db.add(row)
            db.flush()
            records[group["group"]] = row
        if changed:
            resolved = deepcopy(item["resolved_payload"])
            metadata = resolved["attributes"].get("field_groups", {})
            for group in item["groups"]:
                if group["status"] == "accepted" or group["reason"] == "equal_priority":
                    metadata[group["group"]] = {**metadata.get(group["group"], {}),
                                               "claim_id": claim.id, "decision_id": records[group["group"]].id}
            resolved["attributes"]["field_groups"] = metadata
            # _merge_asset preserves the old flat projection for historical
            # observations. Only attach metadata to it when this observation is current.
            if _current(incoming):
                asset.attributes = {**(asset.attributes or {}), "field_groups": deepcopy(metadata)}
            original_normalized = claim.normalized_payload
            claim.normalized_payload = resolved
            service._record_asset_version(db, asset=asset, claim=claim,
                                          change_type="created" if item["asset_id"] is None else "updated")
            claim.normalized_payload = original_normalized
        if item["classification"] == "conflict":
            claim.status = "conflict"
            claim.error_code = "field_group_conflict"
            claim.error_message = "部分字段组有冲突；已保留来源，其他可用组独立处理"
            run.quarantined_rows += 1
            errors.append({"row": number, "field": "groups", "code": claim.error_code, "message": claim.error_message})
        else:
            claim.status = "published" if item["classification"] in {"new", "updated"} else item["classification"]
            run.valid_rows += 1
    run.errors = errors
    run.status = "completed_with_errors" if run.quarantined_rows else "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _current(value):
    now = datetime.now(timezone.utc)
    return (not value.get("valid_from") or _time(value["valid_from"]) <= now) and (
        not value.get("valid_to") or now < _time(value["valid_to"]))


def ingest_file(db, *, source_id, template_id, filename, content, source_revision, created_by, plan_token=None, ledger_declaration=None):
    service = _service()
    from app.services.map_ledger_completeness import declare_plan, parse_declaration
    source = source_for_write(db, source_id, created_by)
    template = service._get_template(db, source.id, template_id)
    digest = hashlib.sha256(content).hexdigest()
    revision = (source_revision or "unspecified").strip()[:200] or "unspecified"
    key = hashlib.sha256(f"{source.id}:{template.id}:{template.version}:{revision}:{digest}".encode()).hexdigest()
    declaration = parse_declaration(ledger_declaration)
    if declaration is not None:
        key = service._hash_json({"file_key": key, "ledger_declaration": declaration})
    existing = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
    if existing:
        return existing, True
    metadata = {}
    rows = service.parse_table(filename, content, template=template, metadata=metadata)
    plan = make_plan(db, source, template, rows, metadata, file_hash=digest)
    plan = declare_plan(db, source, template, plan, declaration)
    if declaration is not None and not plan_token:
        raise ValueError("plan_stale|台账范围声明须先预览，再按同一声明和凭证提交")
    if plan_token and plan_token != plan["plan_token"]:
        raise ValueError("plan_stale|数据、来源或模板已变化，请重新预览")
    if plan["drift"]:
        raise ValueError("template_drift|结构与已确认模板不同，请另存确认新模板后再导入")
    return _execute(db, source=source, template=template, rows=rows, plan=plan, file_hash=digest,
        filename=filename, revision=revision, key=key, created_by=created_by, content=content), False


def retry_rows(db, run_id, data, *, created_by=None, preview=False):
    service = _service()
    parent = get_run(db, run_id)
    source = service._get_source(db, parent.source_id) if preview else source_for_write(db, parent.source_id, created_by)
    template = service._get_template(db, source.id, data.get("template_id") or parent.template_id)
    key = service._hash_json({"parent": parent.id, "request": data["request_id"]})
    request_digest = service._hash_json({"template": template.id, "rows": data["rows"], "note": data.get("note")})
    if not preview:
        existing = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
        if existing:
            if existing.request_sha256 != request_digest:
                raise ValueError("retry_request_conflict|重试标识已用于不同的行修订")
            return existing, True
    rows, parents, promotions = [], {}, {}
    seen = set()
    for correction in data["rows"]:
        identifier = correction["claim_id"]
        claim = db.query(MapFeatureClaim).filter_by(id=identifier, run_id=parent.id).first()
        if not claim or identifier in seen:
            raise ValueError("retry_claim_not_found|异常行不存在或重复选择")
        seen.add(identifier)
        if claim.status not in {"quarantined", "conflict", "awaiting_reingest", "identity_pending"}:
            raise ValueError("retry_successful_row_forbidden|已成功处理的行不能作为异常行重试")
        # A successful descendant consumes this attempt; a failed descendant
        # must be corrected from that newer batch, never fork the old raw row.
        if db.query(MapFeatureClaim.id).filter_by(parent_claim_id=claim.id).first():
            raise ValueError("retry_row_superseded|该行已有修订，请打开最新修订批次继续")
        raw = correction["values"]
        if set(raw) - set((parent.table_metadata or {}).get("headers", raw)):
            raise ValueError("retry_column_unknown|修订不得新增原表中不存在的列")
        if len(raw) > 200 or any(not isinstance(key, str) or len(key) > 200 or
                               isinstance(value, (dict, list)) or len(str(value)) > 10000 for key, value in raw.items()):
            raise ValueError("invalid_row_correction|行修订字段无效或超出限制")
        rows.append((claim.row_number, deepcopy(raw)))
        parents[claim.row_number] = claim.id
        if claim.status == "identity_pending" and not claim.source_record_id and raw.get(template.field_mapping.get("external_id")):
            area = db.query(OperationalArea).filter_by(id=source.operational_area_id).one()
            incoming, _ = normalize(source, template, raw, area.boundary)
            promotion_target(db, source, claim, incoming)
            promotions[claim.row_number] = claim
    from app.services.map_ledger_completeness import correction_metadata
    structure = correction_metadata(parent.table_metadata or {"headers": list(rows[0][1]), "sheet_name": template.sheet_name, "header_row": template.header_row})
    plan = make_plan(db, source, template, rows, structure, file_hash=request_digest, promotions=promotions)
    if preview:
        return public_plan(plan)
    if not data.get("plan_token") or data["plan_token"] != plan["plan_token"]:
        raise ValueError("plan_stale|请先预览本次异常行修订；数据变化后须重新预览")
    if plan["drift"]:
        raise ValueError("template_drift|修订模板与原表结构不同")
    result = _execute(db, source=source, template=template, rows=rows, plan=plan, file_hash=parent.file_hash,
        filename=parent.filename, revision=(parent.source_revision[:120] + ":correction:" + data["request_id"][:60]),
        key=key, created_by=created_by, parent=parent, parents=parents, note=data.get("note"), request_sha256=request_digest)
    return result, False


def list_runs(db, *, source_id=None, offset=0, limit=20):
    query = db.query(MapIngestRun).join(MapSource, MapSource.id == MapIngestRun.source_id)
    if source_id is not None:
        query = query.filter(MapIngestRun.source_id == source_id)
    return {"items": [_service().run_to_dict(row) for row in query.order_by(
        MapIngestRun.started_at.desc(), MapIngestRun.id.desc()).offset(offset).limit(limit)],
        "total": query.count(), "offset": offset, "limit": limit}


def list_claims(db, run_id, *, classification=None, offset=0, limit=50):
    get_run(db, run_id)
    query = db.query(MapFeatureClaim).filter_by(run_id=run_id)
    if classification:
        query = query.filter(MapFeatureClaim.plan["classification"].as_string() == classification)
    rows = query.order_by(MapFeatureClaim.row_number, MapFeatureClaim.id).offset(offset).limit(limit).all()
    # Only disclose whether the currently readable row was consumed. Successor
    # identifiers and data are not exposed by this receipt endpoint.
    superseded = {parent_id for (parent_id,) in db.query(MapFeatureClaim.parent_claim_id).filter(
        MapFeatureClaim.parent_claim_id.in_([row.id for row in rows])).distinct()} if rows else set()
    return {"items": [{**_service().claim_to_dict(row), "retry_superseded": row.id in superseded} for row in rows],
        "total": query.count(), "offset": offset, "limit": limit}


def field_decision_preview(db, claim_id, group):
    service = _service()
    claim = db.query(MapFeatureClaim).filter_by(id=claim_id).first()
    if claim is None or claim.asset_id is None:
        raise ValueError("conflict_not_found")
    parent = get_run(db, claim.run_id)
    source = service._get_source(db, claim.source_id)
    incoming = claim.normalized_payload or {}
    asset, identity, decision = resolve_asset(db, source, incoming)
    if asset is None or asset.id != claim.asset_id:
        raise ValueError("plan_stale|来源身份已变化，不能沿用旧行裁决")
    template = service._get_template(db, source.id, parent.template_id)
    row = next((item for item in (claim.plan or {}).get("groups", []) if item["group"] == group), None)
    if row is None or row["state"] == "not_provided":
        raise ValueError("group_candidate_missing|该行没有可采用的字段组")
    from app.models.map_foundation import JurisdictionAssetVersion
    version = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id).order_by(JurisdictionAssetVersion.version.desc()).first()
    current = _group_values(service.asset_to_dict(asset), group)
    metadata = (asset.attributes or {}).get("field_groups", {}).get(group, {})
    origin, rank, identifier, manual = authority(db, asset, group, current, metadata,
        (asset.attributes or {}).get("source_id"), int((asset.attributes or {}).get("source_trust_rank", 0)))
    return {"asset_id": asset.id, "asset_version": version.version if version else 0,
            "decision_id": identifier, "group": group, "state": row["state"], "candidate": row["new"],
            "current": current, "source_id": source.id, "can_resolve": _current(incoming),
            "boundary": "只采用该来源的一组完整资料；不修改原导入行，其他字段不重新采用"}


def decide_field_group(db, claim_id, data, *, actor_id):
    service = _service()
    claim = db.query(MapFeatureClaim).filter_by(id=claim_id).first()
    if claim is None:
        raise ValueError("conflict_not_found")
    source = source_for_write(db, claim.source_id, actor_id)
    parent = get_run(db, claim.run_id)
    key = service._hash_json({"field_decision": claim.id, "request": data["request_id"]})
    digest = service._hash_json(data)
    previous = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
    if previous:
        if previous.request_sha256 != digest:
            raise ValueError("retry_request_conflict|裁决标识已用于不同内容")
        return previous, True
    view = field_decision_preview(db, claim_id, data["group"])
    if not view["can_resolve"]:
        raise ValueError("historic_group_requires_review|历史或未来有效资料不能直接作为当前字段采用")
    if (view["asset_version"], view["decision_id"]) != (data["expected_asset_version"], data["expected_decision_id"]):
        raise ValueError("plan_stale|字段或来源决定已变化，请刷新后确认")
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=view["asset_id"]).one()
    resolved = service.asset_to_dict(asset)
    resolved["attributes"] = deepcopy(resolved.get("attributes") or {})
    group = data["group"]
    _set_values(resolved, group, view["candidate"])
    if group == "geometry":
        resolved["verified"] = bool(asset.external_id) and source.source_type != "public_map" and view["state"] == "set"
        resolved["verification_state"] = "source_verified" if resolved["verified"] else "geometry_" + view["state"]
    field_group = {"group": group, "state": view["state"], "status": "accepted", "reason": "manual_selection",
        "old": view["current"], "new": view["candidate"], "previous_decision_id": view["decision_id"],
        "source_id": source.id, "trust_rank": source.trust_rank, "manual_override": True,
        "actor_id": actor_id, "note": data["note"]}
    metadata = resolved["attributes"].setdefault("field_groups", {})
    metadata[group] = {"source_id": source.id, "trust_rank": source.trust_rank, "state": view["state"],
                       "manual_override": True, "valid_from": view["candidate"].get("production_valid_from"),
                       "valid_to": view["candidate"].get("production_valid_to")}
    item = {"row_number": claim.row_number, "asset_id": asset.id, "asset_version": view["asset_version"],
            "classification": "updated", "normalized_payload": deepcopy(claim.normalized_payload),
            "resolved_payload": resolved, "groups": [field_group], "errors": [],
            "changes": [{"field": group + "_decision", "group": group, "old": view["decision_id"], "new": "manual_selection"}]}
    from app.services.map_ledger_completeness import correction_metadata
    plan = {"structure": correction_metadata(parent.table_metadata), "rows": [item], "counts": {
        "new": 0, "updated": 1, "unchanged": 0, "identity_pending": 0, "conflict": 0, "failed": 0}}
    template = service._get_template(db, source.id, parent.template_id)
    run = _execute(db, source=source, template=template, rows=[(claim.row_number, claim.raw_payload)], plan=plan,
        file_hash=parent.file_hash, filename=parent.filename, revision=parent.source_revision[:180] + ":field-decision",
        key=key, created_by=actor_id, parent=parent, parents={claim.row_number: claim.id}, note=data["note"], request_sha256=digest)
    return run, False
