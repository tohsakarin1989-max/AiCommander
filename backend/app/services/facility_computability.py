"""Read-only input readiness, not a route calculation or a claim of reachability."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math

from sqlalchemy import or_, select

from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport, InternalRoadReview
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, MapSnapshot, MapSnapshotFeature, OperationalArea, UserAreaScope
from app.models.road_network import RoadAccessGrant, RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.services.road_access_policy import InternalRoadConditions, VehicleAssumption, internal_road_eligibility
from app.services.road_network_contracts import RoadNetworkUnavailable
from app.services.road_network_service import resolve_network
from app.services.facility_execution_context import FacilityExecutionContext, freeze_facility_context
from app.services.facility_identity_service import FacilityIdentityService
from app.services.scorers.dual_domain_v34 import SOURCE_TYPES
from app.services.vehicle_router import ENGINE_VERSION
from app.utils.datetimes import utc_datetime


VERSION = "facility-computability-6.2-1"
BOUNDARY = "仅检查当前授权下的计算资料，不发起路由或更新数据。资料就绪不等于道路连通、允许通行或存在实际路径；未知资料不作肯定推断。"
CATALOG_LIMIT = 10000
_REASONS = {
    "traversal_permission_denied": ("restricted", "没有当前有效的道路通行许可"),
    "source_unverified": ("unverified", "道路或入口来源尚未核验"),
    "explicitly_closed": ("restricted", "条件明确关闭或禁止通行"),
    "conditions_expired": ("expired", "通行条件已过有效期"),
    "conditions_not_yet_valid": ("unavailable", "通行条件尚未生效"),
    "conditions_unknown": ("missing", "门禁、方向或通行条件未知"),
    "vehicle_dimensions_missing": ("missing", "受限道路需要车辆尺寸或重量资料"),
    "vehicle_limit_exceeded": ("restricted", "参考车辆超过已知通行限制"),
    "eligible_not_connectivity_confirmation": ("ready", "已登记条件允许；未计算实际连通与路径"),
}


def _instant(value, default):
    if value is None:
        return default
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("facility_readiness_timezone_required")
    return value.astimezone(timezone.utc)


def _scope(db):
    actor = db.info.get("principal_user_id")
    if type(actor) is not int or actor <= 0 or "authorized_area_ids" not in db.info:
        raise PermissionError("facility_readiness_scope_required")
    role = db.scalar(select(User.role).where(User.id == actor, User.is_active.is_(True)))
    if role is None:
        raise PermissionError("facility_readiness_scope_required")
    ceiling = db.info["authorized_area_ids"]
    if ceiling is not None and (not isinstance(ceiling, (tuple, list, set))
            or any(type(value) is not int or value <= 0 for value in ceiling)):
        raise PermissionError("facility_readiness_scope_required")
    active = set(db.scalars(select(OperationalArea.id).where(OperationalArea.status == "active")))
    if role != "admin":
        active &= set(db.scalars(select(UserAreaScope.operational_area_id).where(
            UserAreaScope.user_id == actor, UserAreaScope.access_level.in_(("read", "write", "manage")))))
    return actor, active if ceiling is None else active.intersection(ceiling)


def _check(key, label, state, detail, refs=(), **extra):
    return {"key": key, "label": label, "state": state, "detail": detail,
            "evidence_refs": sorted(set(refs)), **extra}


def _context(db, *, area_id=None, at=None, known_at=None, context=None):
    if context is not None:
        if not isinstance(context, FacilityExecutionContext):
            raise PermissionError("facility_readiness_context_invalid")
        if area_id is not None and context.operational_area_id not in (None, area_id):
            raise PermissionError("facility_readiness_context_invalid")
        if at is not None and _instant(at, None) != context.valid_at:
            raise ValueError("facility_readiness_time_context_mismatch")
        if known_at is not None and _instant(known_at, None) != context.known_at:
            raise ValueError("facility_readiness_time_context_mismatch")
        current = freeze_facility_context(db, area_id=context.operational_area_id,
                                         valid_at=context.valid_at, known_at=context.known_at)
        if current.user_id != context.user_id or current.policy_version != context.policy_version:
            raise PermissionError("facility_readiness_context_changed")
        return context  # Preserve the already frozen knowledge mode/cutoff.
    if at is not None:
        _instant(at, None)
    if known_at is not None:
        _instant(known_at, None)
    return freeze_facility_context(db, area_id=area_id, valid_at=at, known_at=known_at)


def _catalog(db, area_id, cutoff):
    """Latest known record per stable source ID; keep unverified/disconnected rows."""
    rows = db.query(InternalRoadFeatureVersion, InternalRoadImport).join(
        InternalRoadImport, InternalRoadImport.id == InternalRoadFeatureVersion.import_id).join(
        MapSource, MapSource.id == InternalRoadImport.source_id).filter(
            InternalRoadImport.operational_area_id == area_id, MapSource.status == "active",
            MapSource.operational_area_id == area_id, MapSource.source_type != "public_map",
            InternalRoadImport.created_at <= cutoff).order_by(
                InternalRoadImport.created_at.desc(), InternalRoadImport.id.desc(),
                InternalRoadFeatureVersion.id.desc()).limit(CATALOG_LIMIT + 1).all()
    if len(rows) > CATALOG_LIMIT:
        return None
    latest = {}
    for version, batch in rows:
        key = (version.source_id, version.feature_id)
        if key in latest:
            continue
        feature = next((row for row in (batch.features or []) if row.get("id") == version.feature_id), None)
        latest[key] = {"version": version, "batch": batch, "feature": feature, "review": None}
    ids = {row["batch"].id for row in latest.values()}
    by_review = {(row["batch"].id, row["version"].feature_id): row for row in latest.values()}
    if ids:
        for review in db.query(InternalRoadReview).filter(
            InternalRoadReview.import_id.in_(ids), InternalRoadReview.created_at <= cutoff).order_by(
                InternalRoadReview.sequence).all():
            row = by_review.get((review.import_id, review.feature_id))
            if row is not None:
                row["review"] = review
    return latest


def _groups(db, actor, now):
    return dict(db.execute(select(RoadAccessGroup.id, RoadAccessGroup.policy_revision).join(
        RoadAccessMembership, RoadAccessMembership.group_id == RoadAccessGroup.id).where(
            RoadAccessMembership.user_id == actor, RoadAccessMembership.valid_from <= now,
            or_(RoadAccessMembership.valid_until.is_(None), RoadAccessMembership.valid_until > now))).all())


def _grant(db, groups, source_id, feature_id):
    rows = db.query(RoadAccessGrant).filter(RoadAccessGrant.group_id.in_(groups),
        RoadAccessGrant.source_id == source_id, RoadAccessGrant.feature_id == feature_id).all() if groups else []
    return [row for row in rows if row.policy_revision == groups[row.group_id] and row.decision == "allow"]


def _entry(db, row, catalog, groups, at, vehicle):
    version, batch, feature, review = (row[key] for key in ("version", "batch", "feature", "review"))
    refs = [f"internal_road_entrance:{batch.id}:{version.feature_id}"]
    props = feature.get("properties", {}) if feature else {}
    props = props if isinstance(props, dict) else {}
    road = catalog.get((version.source_id, props.get("road_id")))
    state = {"source_id": version.source_id, "feature_id": version.feature_id,
             "import_id": batch.id, "evidence_refs": refs,
             "review_state": "unverified", "connection_state": "not_checked",
             "passage_state": "not_checked", "reason": "入口尚未核验"}
    geometry = feature.get("geometry") if feature else None
    point = geometry.get("coordinates") if isinstance(geometry, dict) and geometry.get("type") == "Point" else None
    if (not isinstance(point, list) or len(point) != 2
            or any(type(value) not in (float, int) or not math.isfinite(value) for value in point)
            or not -180 <= point[0] <= 180 or not -85 <= point[1] <= 85):
        return {**state, "review_state": "unavailable", "reason": "入口来源记录不完整"}
    if road is None or road["version"].kind != "road" or road["feature"] is None:
        return {**state, "connection_state": "missing", "reason": "声明的道路编号没有可用来源记录"}
    state["road_id"] = props.get("road_id")
    state["road_import_id"] = road["batch"].id
    if not review or review.decision != "verified":
        return state
    refs.append(f"internal_road_review:{review.id}")
    state["review_state"] = "ready"
    connection = review.connection_evidence or {}
    if connection.get("status") == "disconnected":
        return {**state, "connection_state": "disconnected", "reason": "已有核验记录明确未连接"}
    if (connection.get("status") != "connected"
            or connection.get("facility_asset_id") != props.get("facility_asset_id")
            or connection.get("road_import_id") != road["batch"].id
            or connection.get("road_source_sha256") != road["batch"].input_sha256):
        return {**state, "connection_state": "unverified", "reason": "入口与当前已知路段的连接证据缺失或过期"}
    state["connection_state"] = "ready"
    grants = _grant(db, groups, version.source_id, props.get("road_id"))
    refs.extend(f"road_access_grant:{grant.id}" for grant in grants)
    road_review = road["review"]
    if not road_review or road_review.decision != "verified":
        return {**state, "passage_state": "unverified", "reason": "所连道路来源尚未核验"}
    refs.append(f"internal_road_review:{road_review.id}")
    for properties in (props, road["feature"].get("properties", {})):
        try:
            conditions = InternalRoadConditions.model_validate_json(json.dumps(properties.get("conditions", {})))
            result = internal_road_eligibility(conditions=conditions, vehicle=vehicle, at=at,
                                              verified=True, traversal_permitted=bool(grants))
        except (ValueError, TypeError):
            return {**state, "passage_state": "unavailable", "reason": "通行条件格式无效，未作允许判断"}
        status, reason = _REASONS[result.reason]
        if not result.include:
            return {**state, "passage_state": status, "reason": reason}
    return {**state, "passage_state": "ready", "reason": _REASONS["eligible_not_connectivity_confirmation"][1]}


def _graph_connection(db, binding, entries):
    """Inclusion in compiler inputs is still not a routing/connectivity result."""
    if binding is None:
        return _check("graph_connection", "设施路段入网", "not_checked", "缺少可用路网，未检查设施声明路段是否入网")
    network = db.query(RoadNetworkVersion).populate_existing().filter_by(id=binding.network_id).one()
    inputs = ((network.source_manifest or {}).get("governance_plan") or {}).get("inputs") or {}
    included = inputs.get("included")
    refs = [f"road_network:{binding.network_id}"]
    if not isinstance(included, list):
        return _check("graph_connection", "设施路段入网", "not_checked", "该路网未提供可核对的内部设施路段编译清单", refs)
    for entry in entries:
        if entry["passage_state"] != "ready":
            continue
        for row in included:
            if (isinstance(row, dict) and row.get("source_id") == entry["source_id"]
                    and row.get("feature_id") == entry.get("road_id")
                    and row.get("import_id") == entry.get("road_import_id")):
                return _check("graph_connection", "设施路段入网", "ready",
                              "声明路段的对应来源版本已进入有效路网编译清单；未执行设施路径计算", refs + entry["evidence_refs"])
    return _check("graph_connection", "设施路段入网", "unavailable", "没有已就绪入口的声明路段进入此有效路网，需补齐连接或重新构建", refs)


def _aggregate(entries, field):
    if not entries:
        return "missing"
    states = {entry[field] for entry in entries}
    if "ready" in states:
        return "ready"  # At least one suitable entry; other gaps remain in details.
    for state in ("unavailable", "expired", "restricted", "disconnected", "unverified", "missing", "not_checked"):
        if state in states:
            return state
    return "not_checked"


def _network(db, actor, groups, at, known_at, vehicle):
    if not groups:
        return _check("network", "已授权计算路网", "restricted", "没有当前有效的道路通行授权组"), None
    rows = db.query(RoadNetworkVersion).filter(RoadNetworkVersion.group_id.in_(groups),
        RoadNetworkVersion.created_at <= known_at, RoadNetworkVersion.engine_version == ENGINE_VERSION).order_by(
            RoadNetworkVersion.valid_from.desc(), RoadNetworkVersion.created_at.desc()).all()
    failure = "missing"
    for row in rows:
        if row.policy_revision != groups[row.group_id]:
            failure = "unavailable"
            continue
        if at < utc_datetime(row.valid_from):
            continue
        if row.valid_until is not None and at >= utc_datetime(row.valid_until):
            failure = "expired"
            continue
        try:
            binding = resolve_network(db, row.id, analysis_at=at, vehicle=vehicle)
        except RoadNetworkUnavailable:
            failure = "unavailable"
            continue
        return _check("network", "已授权计算路网", "ready", "路网目录与权限有效；未检查引擎运行或计算设施路径",
                      [f"road_network:{row.id}"]), binding
    return _check("network", "已授权计算路网", failure,
                  "未找到适用于所选时刻、当前权限和参考车型的有效路网；不回退为直线距离"), None


def _readiness(db, asset, *, actor, scope, at, known_at, now, vehicle, catalog):
    refs = [f"asset:{asset.id}"]
    try:
        temporal = FacilityIdentityService.get_asset_at(db, asset.id, valid_at=at, known_at=known_at)
    except LookupError:
        raise PermissionError("facility_source_unavailable") from None
    recorded = temporal.get("snapshot") or {}
    attributes = recorded.get("attributes", asset.attributes)
    attributes = attributes if isinstance(attributes, dict) else {}
    source_id = attributes.get("source_id")
    source = db.query(MapSource).filter_by(id=source_id, operational_area_id=asset.operational_area_id,
                                         status="active").first() if type(source_id) is int else None
    source_state = "restricted" if source_id is not None and source is None else "ready" if source else "missing"
    coords = (recorded.get("latitude", asset.latitude), recorded.get("longitude", asset.longitude))
    geometry_ok = all(type(value) in (int, float) and math.isfinite(value) for value in coords)
    geometry_ok = geometry_ok and -85 <= coords[0] <= 85 and -180 <= coords[1] <= 180
    verified = bool(recorded.get("verified", asset.verified))
    geometry_state = ("missing" if not geometry_ok else "not_checked" if temporal["state"] != "ready"
                      else "ready" if verified else "unverified")
    received = utc_datetime(asset.updated_at or asset.created_at) if (asset.updated_at or asset.created_at) else None
    checks = [
        _check("identity", "稳定设施标识", "ready" if asset.external_id else "unverified",
               "已登记来源内编号；不按同名合并" if asset.external_id else "尚缺稳定来源编号，名称和距离不能证明同一设施", refs),
        _check("source", "资料来源", source_state,
               "来源已登记" if source_state == "ready" else "资料来源不可访问" if source_state == "restricted" else "缺少可追溯的登记来源", refs),
        _check("geometry", "计算位置", geometry_state,
               "已核验设施坐标；不是可信入口" if geometry_state == "ready" else
               "现有位置不能证明适用于所选资料时点，未作为该时点计算坐标" if geometry_state == "not_checked" else
               "位置缺失或尚未核验；不自动吸附公共道路", refs),
    ]
    if source_state == "restricted":
        entries = []
        catalog = None
    else:
        entries = [_entry(db, row, catalog, _groups(db, actor, now), at, vehicle)
                   for row in (catalog or {}).values() if row["version"].kind == "entrance"
                   and row["feature"] and (row["feature"].get("properties") or {}).get("facility_asset_id") == asset.id]
    entry_refs = [ref for entry in entries for ref in entry["evidence_refs"]]
    for key, label, field in (("entrance", "设施入口核验", "review_state"),
                               ("connection", "入口道路连接", "connection_state"),
                               ("passage", "当前许可与时点条件", "passage_state")):
        state = ("restricted" if source_state == "restricted" else "unavailable") if catalog is None else _aggregate(entries, field)
        detail = "；".join(sorted({entry["reason"] for entry in entries})) if entries else (
            "入口资料不可访问" if source_state == "restricted" else "来源目录超出单次检查预算" if catalog is None else "未登记明确设施入口；不猜测最近入口")
        checks.append(_check(key, label, state, detail, entry_refs, details=entries))
    groups = _groups(db, actor, now)
    network, binding = _network(db, actor, groups, at, known_at, vehicle)
    checks.append(network)
    checks.append(_graph_connection(db, binding, entries))
    snapshot = db.query(MapSnapshot).join(MapSnapshotFeature, MapSnapshotFeature.snapshot_id == MapSnapshot.id).filter(
        MapSnapshotFeature.asset_id == asset.id, MapSnapshot.operational_area_id == asset.operational_area_id,
        MapSnapshot.status.in_(("current", "superseded")), MapSnapshot.published_at <= min(at, known_at)).order_by(
            MapSnapshot.published_at.desc(), MapSnapshot.id).first()
    checks.append(_check("snapshot", "已发布地图快照", "ready" if snapshot else "missing",
                         "已有发布快照，未检查瓦片服务运行状态" if snapshot else "没有可用于所选时点的已发布设施快照",
                         [f"map_snapshot:{snapshot.id}"] if snapshot else []))
    checks.append(_check("history", "资料时点适用性",
                         "ready" if temporal["state"] == "ready" else "unavailable" if temporal["state"] == "conflict" else "not_checked",
                         "来源资料覆盖所选业务时点与知悉时点" if temporal["state"] == "ready" else "；".join(temporal["gaps"]),
                         [f"asset_version:{temporal['version_id']}"] if temporal.get("version_id") else refs))
    ready = all(check["state"] == "ready" for check in checks)
    return {"asset_id": asset.id, "name": asset.name, "asset_type": asset.asset_type,
            "state": "ready" if ready else "missing" if not entries and not geometry_ok else "partial",
            "checks": checks, "boundary": BOUNDARY, "route_state": "not_checked",
            "versions": {"schema_version": VERSION, "at": at.isoformat(), "known_at": known_at.isoformat(),
                         "asset_updated_at": received.isoformat() if received else None,
                         "principal_user_id": actor, "scope": sorted(scope), "vehicle": vehicle.model_dump(),
                         "network_id": binding.network_id if binding else None,
                         "policy_revision": binding.policy_revision if binding else None,
                         "asset_version_id": temporal.get("version_id"),
                         "map_snapshot_id": snapshot.id if snapshot else None}}


def facility_readiness(db, asset_id, *, at=None, known_at=None, vehicle=None, context=None):
    with db.no_autoflush:
        context = _context(db, at=at, known_at=known_at, context=context)
        actor, scope = _scope(db)
        asset = db.query(JurisdictionAsset).populate_existing().filter(
            JurisdictionAsset.id == asset_id, JurisdictionAsset.operational_area_id.in_(scope),
            JurisdictionAsset.asset_type.in_(SOURCE_TYPES)).first()
        if asset is None:
            raise PermissionError("facility_unavailable")
        if context.operational_area_id is not None and context.operational_area_id != asset.operational_area_id:
            raise PermissionError("facility_unavailable")
        now = datetime.now(timezone.utc)
        at, known_at = context.valid_at, context.known_at
        vehicle = vehicle or VehicleAssumption(kind="auto", source="explicit_reference_assumption")
        if not isinstance(vehicle, VehicleAssumption):
            vehicle = VehicleAssumption.model_validate(vehicle)
        value = _readiness(db, asset, actor=actor, scope=scope, at=at, known_at=known_at, now=now,
                          vehicle=vehicle, catalog=_catalog(db, asset.operational_area_id, min(at, known_at)))
        value["context"] = context.public()
        return value


def list_readiness(db, area_id=None, page=1, page_size=20, at=None, context=None):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("facility_readiness_pagination_invalid")
    with db.no_autoflush:
        context = _context(db, area_id=area_id, at=at, context=context)
        actor, scope = _scope(db)
        if area_id is None:
            area_id = context.operational_area_id
        if area_id is not None and (type(area_id) is not int or area_id not in scope):
            raise PermissionError("facility_unavailable")
        query = db.query(JurisdictionAsset).filter(JurisdictionAsset.operational_area_id.in_(scope),
            JurisdictionAsset.asset_type.in_(SOURCE_TYPES), JurisdictionAsset.status == "active")
        if area_id is not None:
            query = query.filter(JurisdictionAsset.operational_area_id == area_id)
        total = query.count()
        assets = query.order_by(JurisdictionAsset.id).offset((page - 1) * page_size).limit(page_size).all()
        now = datetime.now(timezone.utc)
        at, known_at = context.valid_at, context.known_at
        vehicle = VehicleAssumption(kind="auto", source="explicit_reference_assumption")
        catalogs = {area: _catalog(db, area, min(at, known_at)) for area in {asset.operational_area_id for asset in assets}}
        items = [_readiness(db, asset, actor=actor, scope=scope, at=at, known_at=known_at, now=now,
                            vehicle=vehicle, catalog=catalogs[asset.operational_area_id]) for asset in assets]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "boundary": BOUNDARY, "context": context.public()}
