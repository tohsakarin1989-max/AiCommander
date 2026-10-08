"""Conservative authorized-input fingerprint, including objects not recalled.

This is a streamed metadata pass, not a precise spatial dependency index. No
source text or fingerprint component is returned by the progress endpoint.
"""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy.orm import load_only

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_history_index import CaseHistoryIndex, CaseHistoryFragment
from app.models.case_source import CaseRevision
from app.models.internal_roads import InternalRoadImport, InternalRoadReview
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (FacilityIdentityDecision, FacilitySourceIdentity,
    JurisdictionAssetVersion, MapFieldDecision, MapSnapshot, MapSource)
from app.models.road_network import RoadNetworkVersion

VERSION = "facility-dependencies-7.5-1"


def _now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False, default=lambda item: utc(item).isoformat()).encode()


def dependency_signature(db, *, now=None):
    if "authorized_area_ids" not in db.info or type(db.info.get("principal_user_id")) is not int:
        raise PermissionError("facility_dependency_scope_required")
    now = utc(now or _now())
    scope = db.info["authorized_area_ids"]
    scope = None if scope is None else sorted(scope)
    hasher, next_dates = hashlib.sha256(), []

    def time_states(value, path=""):
        states = []
        if isinstance(value, dict):
            for key, item in sorted(value.items()):
                # Real interval boundaries only; created/received/known timestamps
                # do not make a new dependency revision every polling minute.
                if key.endswith(("valid_from", "valid_to", "valid_until", "closed_from", "closed_until")) and item:
                    try:
                        instant = utc(item if isinstance(item, datetime) else datetime.fromisoformat(item.replace("Z", "+00:00")))
                    except (ValueError, TypeError, AttributeError):
                        continue  # The business validator reports invalid conditions.
                    states.append([path + key, instant <= now])
                    if instant > now:
                        next_dates.append(instant)
                states.extend(time_states(item, path + key + "/"))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                states.extend(time_states(item, path + str(index) + "/"))
        return states

    # Entity queries deliberately retain the session's area/source ACL criteria.
    # Immutable rows are represented by identity/version; mutable inputs include
    # their actual fields. All authorized facilities are included, not only top N.
    definitions = (
        (JurisdictionAsset, ("id", "operational_area_id", "asset_type", "latitude", "longitude", "source", "status",
                             "verified", "valid_from", "valid_to", "attributes", "updated_at")),
        (MapSource, ("id", "operational_area_id", "source_type", "status", "updated_at")),
        (JurisdictionAssetVersion, ("id", "asset_id", "version", "valid_from", "valid_to", "known_at", "snapshot")),
        (MapFieldDecision, ("id", "asset_id", "source_id", "state", "outcome", "valid_from", "valid_to", "payload")),
        (FacilitySourceIdentity, ("id", "native_asset_id", "source_id", "identity_key")),
        (FacilityIdentityDecision, tuple(column.key for column in FacilityIdentityDecision.__table__.columns)),
        (MapSnapshot, ("id", "operational_area_id", "status", "feature_watermark", "published_at")),
        (Case, ("id", "operational_area_id", "updated_at")),
        (CaseRevision, ("id", "case_id", "source_hash")),
        (CaseAnalysisProfile, ("id", "case_id", "source_hash", "is_current", "profile_version")),
        (CaseHistoryIndex, ("case_id", "source_type", "source_id", "source_hash", "rule_version", "updated_at")),
        (CaseHistoryFragment, ("id", "case_id", "source_hash", "rule_version", "model_version", "dimension", "embedding_state")),
        (InternalRoadImport, ("id", "source_id", "input_sha256", "features")),
        (InternalRoadReview, ("id", "import_id", "sequence", "decision", "connection_evidence")),
        (RoadNetworkVersion, ("id", "group_id", "status", "graph_sha256", "policy_revision", "conditions_sha256",
                              "valid_from", "valid_until")),
    )
    components = {}
    for model, fields in definitions:
        part = hashlib.sha256()
        query = db.query(model).populate_existing().options(load_only(*(getattr(model, name) for name in fields)))
        if model is RoadNetworkVersion:
            # Graphs have passage groups rather than area ownership. Hash only
            # the actor's groups, including future graph versions/new shortcuts.
            from app.models.road_network import RoadAccessMembership
            query = query.filter(model.group_id.in_(db.query(RoadAccessMembership.group_id).filter_by(
                user_id=db.info["principal_user_id"])))
        count = 0
        for row in query.order_by(*model.__table__.primary_key.columns).yield_per(100):
            data = {name: getattr(row, name) for name in fields}
            part.update(encoded([data, time_states(data)]))
            count += 1
        components[model.__tablename__] = {"sha256": part.hexdigest(), "count": count}
    hasher.update(encoded({"schema": VERSION, "user_id": db.info["principal_user_id"], "scope": scope,
                          "components": components}))
    return {"schema": VERSION, "sha256": hasher.hexdigest(), "scope": scope,
            "user_id": db.info["principal_user_id"], "components": components,
            "next_transition_at": min(next_dates).isoformat() if next_dates else None,
            "policy": "whole_authorized_scope_conservative",
            "boundary": "覆盖当前授权范围的设施、检索来源与兼容路网；非精准空间增量，范围变化保守重算。"}


def require_dependencies(db, frozen):
    current = dependency_signature(db)
    if current["sha256"] != frozen["sha256"]:
        raise ValueError("facility_job_dependencies_changed")
    return current
