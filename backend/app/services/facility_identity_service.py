"""Stable source identities and evidence-bounded, two-time facility reads.

Writes flush into the caller's transaction. Mapping never rewrites source rows,
old versions or old decisions; revoked identities require a new human decision.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import or_

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    FacilityIdentityDecision, FacilitySourceIdentity, JurisdictionAssetVersion,
    MapFeatureClaim, MapSource, OperationalArea,
)


def _now():
    return datetime.now(timezone.utc)


def _utc(value, *, stored=False):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("facility_time_invalid") from None
    if not isinstance(value, datetime) or (value.tzinfo is None and not stored):
        raise ValueError("facility_time_timezone_required")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value):
    return _utc(value, stored=True).isoformat() if value else None


def _scope(db, area_id, *, required=True):
    if "authorized_area_ids" not in db.info:
        if required or db.info.get("principal_user_id") is not None:
            raise PermissionError("facility_scope_required")
        return  # Existing trusted write services may use a service-only session.
    allowed = db.info["authorized_area_ids"]
    if allowed is not None and area_id not in allowed:
        raise PermissionError("facility_scope_denied")


def _asset(db, asset_id, *, required=True):
    asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=asset_id).first()
    if asset is None:
        raise LookupError("facility_not_found")
    _scope(db, asset.operational_area_id, required=required)
    return asset


def _source(db, source_id, *, required=True):
    source = db.query(MapSource).populate_existing().filter_by(id=source_id).first()
    if source is None or source.status != "active":
        raise LookupError("facility_source_unavailable")
    _scope(db, source.operational_area_id, required=required)
    return source


def _latest_decision(db, identity_id, known_at=None):
    query = db.query(FacilityIdentityDecision).filter_by(identity_id=identity_id)
    if known_at is not None:
        query = query.filter(FacilityIdentityDecision.created_at <= known_at)
    return query.order_by(FacilityIdentityDecision.sequence.desc()).first()


def _decision_dict(row, *, created=False):
    return {"id": row.id, "decision_id": row.id, "identity_id": row.identity_id,
            "target_asset_id": row.target_asset_id, "action": row.action,
            "status": "bound" if row.action == "bind" else "revoked",
            "sequence": row.sequence, "actor_id": row.actor_id, "note": row.note,
            "request_key": row.request_key, "known_at": _iso(row.created_at), "created": created}


class FacilityIdentityService:
    @staticmethod
    def ensure_identity(db, *, source, asset, normalized):
        """Called only after the existing exact-source identity guard succeeded."""
        _scope(db, source.operational_area_id, required=False)
        _scope(db, asset.operational_area_id, required=False)
        external = normalized.get("external_id")
        key = "id:" + external if external else "fingerprint:" + normalized["canonical_key"]
        identity = db.query(FacilitySourceIdentity).filter_by(source_id=source.id, identity_key=key).first()
        if identity is None:
            identity = FacilitySourceIdentity(source_id=source.id,
                operational_area_id=source.operational_area_id, native_asset_id=asset.id,
                identity_key=key, source_record_id=external, asset_type=normalized["asset_type"],
                identity_kind="exact_id" if external else "unidentified", created_at=_now())
            db.add(identity)
            db.flush()
        if identity.operational_area_id != source.operational_area_id or identity.asset_type != normalized["asset_type"]:
            raise ValueError("facility_identity_type_or_area_changed")
        return identity

    @staticmethod
    def resolve_import(db, *, source, normalized):
        _scope(db, source.operational_area_id, required=False)
        external = normalized.get("external_id")
        key = "id:" + external if external else "fingerprint:" + normalized["canonical_key"]
        identity = db.query(FacilitySourceIdentity).filter_by(source_id=source.id, identity_key=key).first()
        if identity is None:
            return None, None, None
        if identity.operational_area_id != source.operational_area_id or identity.asset_type != normalized["asset_type"]:
            raise ValueError("facility_identity_type_or_area_changed")
        decision = _latest_decision(db, identity.id)
        if decision is not None and decision.action == "revoke":
            raise ValueError("facility_identity_revoked|来源身份关联已撤销，需要重新人工决定")
        asset = _asset(db, decision.target_asset_id if decision else identity.native_asset_id, required=False)
        if asset.operational_area_id != source.operational_area_id or asset.asset_type != identity.asset_type:
            raise ValueError("facility_identity_type_or_area_changed")
        return identity, decision, asset

    @staticmethod
    def list_identity(db, *, asset_id=None, source_id=None):
        if asset_id is None and source_id is None:
            raise ValueError("facility_identity_scope_required")
        if asset_id is not None:
            _asset(db, asset_id)
        if source_id is not None:
            _source(db, source_id)
        query = db.query(FacilitySourceIdentity)
        if source_id is not None:
            query = query.filter_by(source_id=source_id)
        if asset_id is not None:
            linked = db.query(FacilityIdentityDecision.identity_id).filter_by(target_asset_id=asset_id)
            query = query.filter(or_(FacilitySourceIdentity.native_asset_id == asset_id,
                                    FacilitySourceIdentity.id.in_(linked)))
        items = []
        for identity in query.order_by(FacilitySourceIdentity.id):
            origin = _source(db, identity.source_id)
            native = _asset(db, identity.native_asset_id)
            decision = _latest_decision(db, identity.id)
            target = _asset(db, decision.target_asset_id) if decision else native
            claim = db.query(MapFeatureClaim).filter_by(source_identity_id=identity.id).order_by(MapFeatureClaim.id.desc()).first()
            items.append({"id": identity.id, "identity_id": identity.id, "source_id": origin.id,
                "source_name": origin.name, "source_record_id": identity.source_record_id,
                "record_name": (claim.normalized_payload or {}).get("name", native.name) if claim else native.name,
                "native_asset_id": native.id, "target_asset_id": target.id, "target_asset_name": target.name,
                "asset_type": identity.asset_type, "identity_kind": identity.identity_kind,
                "decision_id": decision.id if decision else None,
                "status": "revoked" if decision and decision.action == "revoke" else "bound" if decision else "source_identified",
                "history": [_decision_dict(row) for row in db.query(FacilityIdentityDecision)
                            .filter_by(identity_id=identity.id).order_by(FacilityIdentityDecision.sequence)]})
        return {"items": items}

    @staticmethod
    def bind(db, identity_id, asset_id, *, actor_id, note, request_key, previous_decision_id=None):
        return FacilityIdentityService._decide(db, identity_id, asset_id, action="bind", actor_id=actor_id,
            note=note, request_key=request_key, previous_decision_id=previous_decision_id)

    @staticmethod
    def revoke(db, identity_id, *, actor_id, note, request_key, previous_decision_id):
        return FacilityIdentityService._decide(db, identity_id, None, action="revoke", actor_id=actor_id,
            note=note, request_key=request_key, previous_decision_id=previous_decision_id)

    @staticmethod
    def _decide(db, identity_id, asset_id, *, action, actor_id, note, request_key, previous_decision_id):
        from app.database import require_area_write_access
        if not 1 <= len(str(note or "").strip()) <= 2000 or not 1 <= len(str(request_key or "")) <= 80:
            raise ValueError("facility_identity_reason_and_request_required")
        query = db.query(FacilitySourceIdentity).filter_by(id=identity_id)
        identity = query.first()
        if identity is None:
            raise LookupError("facility_identity_not_found")
        _scope(db, identity.operational_area_id)
        # Ingest holds this same area lock before resolving a mapping. Keep one
        # Area -> Identity lock order so revoke cannot race an old-bound import.
        if db.bind.dialect.name == "postgresql":
            area = db.query(OperationalArea).populate_existing().filter_by(
                id=identity.operational_area_id).with_for_update().first()
            if area is None or area.status != "active":
                raise LookupError("facility_area_unavailable")
            identity = query.populate_existing().with_for_update().one()
        from app.models.user import User
        actor = db.query(User).populate_existing().filter_by(id=actor_id).first()
        if actor is None or not actor.is_active or actor.role != "admin":
            raise PermissionError("facility_identity_admin_required")
        origin = _source(db, identity.source_id)
        native = _asset(db, identity.native_asset_id)
        _scope(db, identity.operational_area_id)
        if origin.operational_area_id != identity.operational_area_id or native.operational_area_id != identity.operational_area_id:
            raise ValueError("facility_identity_type_or_area_changed")
        require_area_write_access(db, identity.operational_area_id)
        if db.info.get("principal_user_id") not in {None, actor_id}:
            raise PermissionError("facility_identity_actor_mismatch")
        current = _latest_decision(db, identity_id)
        previous = db.query(FacilityIdentityDecision).filter_by(identity_id=identity_id, request_key=request_key).first()
        target_id = asset_id if action == "bind" else previous.target_asset_id if previous else (
            current.target_asset_id if current else identity.native_asset_id)
        target = _asset(db, target_id)
        require_area_write_access(db, target.operational_area_id)
        if target.operational_area_id != identity.operational_area_id:
            raise ValueError("facility_identity_cross_area_forbidden")
        if target.asset_type != identity.asset_type or native.asset_type != identity.asset_type:
            raise ValueError("facility_identity_cross_type_forbidden")
        if (origin.source_type == "public_map") != (target.source == "public_map"):
            raise ValueError("facility_public_reference_cannot_be_production_fact")
        if previous is not None:
            if (previous.action, previous.target_asset_id, previous.actor_id, previous.note) != (action, target_id, actor_id, note.strip()):
                raise ValueError("facility_identity_request_conflict")
            return _decision_dict(previous)
        if (current.id if current else None) != previous_decision_id:
            raise ValueError("facility_identity_decision_changed")
        if action == "revoke" and current is not None and current.action == "revoke":
            raise ValueError("facility_identity_already_revoked")
        record = FacilityIdentityDecision(identity_id=identity.id, operational_area_id=identity.operational_area_id,
            target_asset_id=target.id, sequence=(current.sequence + 1) if current else 1, action=action,
            actor_id=actor_id, note=note.strip(), request_key=request_key, created_at=_now())
        db.add(record)
        if action == "revoke" and (target.attributes or {}).get("source_identity_id") == identity.id:
            target.verified = False
            target.verification_state = "identity_revoked"
        db.flush()
        return _decision_dict(record, created=True)

    @staticmethod
    def record_asset_version(db, *, asset, claim=None, change_type, valid_from=None, valid_to=None, validity=None):
        """Internal write seam; only explicit validity can establish history."""
        from app.services.map_foundation_service import MapFoundationService
        _scope(db, asset.operational_area_id, required=False)
        db.flush()
        latest = db.query(JurisdictionAssetVersion).filter_by(asset_id=asset.id).order_by(JurisdictionAssetVersion.version.desc()).first()
        snapshot = deepcopy(MapFoundationService.asset_to_dict(asset))
        if claim is not None and claim.normalized_payload:
            # A historic/future source observation must not borrow current values.
            snapshot.update(deepcopy(claim.normalized_payload))
            snapshot["id"] = asset.id
            source = _source(db, claim.source_id, required=False)
            snapshot["attributes"] = {**(snapshot.get("attributes") or {}), "source_id": source.id,
                "source_key": source.source_key, "source_trust_rank": source.trust_rank,
                "source_revision": claim.source_revision, "source_identity_id": claim.source_identity_id,
                "identity_decision_id": claim.identity_decision_id}
        if change_type == "baseline_observed":
            valid_from = valid_to = None
        elif claim is not None:
            valid_from, valid_to = _utc(snapshot.get("valid_from")), _utc(snapshot.get("valid_to"))
        elif validity is not None or valid_from is not None or valid_to is not None:
            supplied = validity if validity is not None else {"valid_from": valid_from, "valid_to": valid_to}
            valid_from = _utc(supplied["valid_from"]) if "valid_from" in supplied else (
                _utc(latest.valid_from, stored=True) if latest and latest.temporal_status == "declared" else None)
            valid_to = _utc(supplied["valid_to"]) if "valid_to" in supplied else (
                _utc(latest.valid_to, stored=True) if latest and latest.temporal_status == "declared" else None)
        elif latest and latest.temporal_status == "declared":
            valid_from, valid_to = _utc(latest.valid_from, stored=True), _utc(latest.valid_to, stored=True)
        else:
            valid_from = valid_to = None
        if valid_to is not None and (valid_from is None or valid_to <= valid_from):
            raise ValueError("facility_valid_interval_invalid")
        snapshot["valid_from"], snapshot["valid_to"] = _iso(valid_from), _iso(valid_to)
        version = JurisdictionAssetVersion(asset_id=asset.id, version=(latest.version + 1) if latest else 1,
            source_claim_id=claim.id if claim else None, snapshot=snapshot, change_type=change_type,
            valid_from=valid_from, valid_to=valid_to, known_at=_now(),
            temporal_status="declared" if valid_from is not None else "observed_only",
            source_identity_id=claim.source_identity_id if claim else None,
            identity_decision_id=claim.identity_decision_id if claim else None)
        db.add(version)
        db.flush()
        return version

    @staticmethod
    def get_asset_at(db, asset_id, *, valid_at, known_at=None):
        asset = _asset(db, asset_id)
        valid_at = _utc(valid_at)
        known_at = _utc(known_at) if known_at is not None else _now()
        if valid_at is None:
            raise ValueError("facility_valid_at_required")
        identity_rows = db.query(FacilitySourceIdentity).filter(
            FacilitySourceIdentity.operational_area_id == asset.operational_area_id).all()
        active, decisions = {}, {}
        for identity in identity_rows:
            if _utc(identity.created_at, stored=True) > known_at:
                continue
            decision = _latest_decision(db, identity.id, known_at)
            target = decision.target_asset_id if decision else identity.native_asset_id
            if target == asset_id and not (decision and decision.action == "revoke"):
                active[identity.id] = _source(db, identity.source_id)
                decisions[identity.id] = decision.id if decision else None
        query = db.query(JurisdictionAssetVersion).filter(or_(
            JurisdictionAssetVersion.asset_id == asset_id,
            JurisdictionAssetVersion.source_identity_id.in_(active)))
        periods = {}
        for row in query.order_by(JurisdictionAssetVersion.version, JurisdictionAssetVersion.id):
            if row.source_identity_id is not None and row.source_identity_id not in active:
                continue
            snapshot_area = (row.snapshot or {}).get("operational_area_id")
            _scope(db, snapshot_area)
            if row.temporal_status != "declared" or row.known_at is None or row.valid_from is None:
                continue
            if _utc(row.known_at, stored=True) > known_at or _utc(row.valid_from, stored=True) > valid_at:
                continue
            source_id = (row.snapshot.get("attributes") or {}).get("source_id")
            origin = _source(db, source_id) if source_id is not None else None
            lane = ("identity", row.source_identity_id) if row.source_identity_id else ("manual", row.asset_id)
            period = (lane, _utc(row.valid_from, stored=True))
            previous = periods.get(period)
            if previous is None or (_utc(row.known_at, stored=True), row.id) > (_utc(previous[0].known_at, stored=True), previous[0].id):
                rank = int((row.snapshot.get("attributes") or {}).get("source_trust_rank", 90)) if row.source_claim_id is not None else 90
                periods[period] = (row, rank)
        lanes = {}
        for (lane, start), (row, rank) in periods.items():
            if row.valid_to is not None and valid_at >= _utc(row.valid_to, stored=True):
                continue
            # Resolve same-period corrections before testing validity. A newer
            # explicitly closed period must not resurrect an older open value.
            closed_later = any(other_lane == lane and other_start >= start
                and other.valid_to is not None and valid_at >= _utc(other.valid_to, stored=True)
                and _utc(other.known_at, stored=True) >= _utc(row.known_at, stored=True)
                for (other_lane, other_start), (other, _) in periods.items())
            if closed_later:
                continue
            previous = lanes.get(lane)
            if previous is None or (_utc(row.known_at, stored=True), row.id) > (_utc(previous[0].known_at, stored=True), previous[0].id):
                lanes[lane] = (row, rank)
        result = {"state": "unknown", "asset_id": asset_id, "valid_at": _iso(valid_at), "known_at": _iso(known_at),
                  "version_id": None, "snapshot": None, "source_claim_id": None,
                  "source_identity_id": None, "identity_decision_id": None,
                  "gaps": ["缺少当时已知且覆盖该业务时点的明确有效期资料"]}
        if not lanes:
            return result
        highest = max(value[1] for value in lanes.values())
        choices = [value[0] for value in lanes.values() if value[1] == highest]
        def material(row):
            values = row.snapshot
            attrs = values.get("attributes") or {}
            return {key: values.get(key) for key in ("asset_type", "geometry", "latitude", "longitude", "status")}, {
                key: value for key, value in attrs.items() if key not in {"source_id", "source_key", "source_revision", "source_trust_rank", "source_identity_id", "identity_decision_id"}}
        if any(material(row) != material(choices[0]) for row in choices[1:]):
            return {**result, "state": "conflict", "gaps": ["同等可信来源在该时点的资料存在冲突，未自动选为事实"]}
        selected = max(choices, key=lambda row: (_utc(row.known_at, stored=True), row.id))
        return {**result, "state": "ready", "version_id": selected.id,
                "snapshot": deepcopy(selected.snapshot), "source_claim_id": selected.source_claim_id,
                "source_identity_id": selected.source_identity_id,
                "identity_decision_id": decisions.get(selected.source_identity_id), "gaps": [],
                "supporting_version_ids": [row.id for row, _ in lanes.values()]}
