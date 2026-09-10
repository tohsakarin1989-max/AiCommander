"""待核道路来源版本；提交只写派生资料，不发布或认定道路可通行。"""
from sqlalchemy import func, and_
from sqlalchemy.exc import IntegrityError

from app.database import AreaWriteAccessError, require_area_write_access
from app.models.internal_roads import InternalRoadImport, InternalRoadReview, InternalRoadFeatureVersion
from app.models.map_foundation import MapSource
from app.services.internal_road_import import preview_internal_roads


def authorized_source(db, source_id, *, write=False):
    if "authorized_area_ids" not in db.info:
        raise PermissionError("缺少有效数据范围")
    source = db.query(MapSource).filter_by(id=source_id, status="active").first()
    if source is None:
        raise LookupError("来源不存在或不可访问")
    if source.source_type == "public_map":
        raise ValueError("内部道路不能使用公共地图来源")
    if write:
        if "area_access_levels" not in db.info:
            raise AreaWriteAccessError("缺少明确写入范围")
        require_area_write_access(db, source.operational_area_id)
    return source


def describe_import(record):
    return {"id": record.id, "source_id": record.source_id,
            "operational_area_id": record.operational_area_id,
            "input_sha256": record.input_sha256, "schema_version": record.schema_version,
            "features": record.features, "warnings": record.warnings,
            "created_by": record.created_by,
            "created_at": record.created_at.isoformat(),
            "status": "pending_verification", "routing_available": False}


def ingest_roads(db, source_id, payload, actor_id):
    source = authorized_source(db, source_id, write=True)
    preview = preview_internal_roads(payload)
    if preview["valid"] != preview["total"]:
        raise ValueError("批次包含无效行，请修正后提交；未保存任何记录")
    existing = db.query(InternalRoadImport).filter_by(
        source_id=source_id, input_sha256=preview["input_sha256"]).first()
    if existing:
        return describe_import(existing), False
    record = InternalRoadImport(
        source_id=source_id, operational_area_id=source.operational_area_id,
        input_sha256=preview["input_sha256"], schema_version=preview["schema_version"],
        features=[row["feature"] for row in preview["rows"]],
        warnings=[{"source_feature_id": row["source_feature_id"], "warnings": row["warnings"]}
                  for row in preview["rows"]], created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
            db.add_all([InternalRoadFeatureVersion(import_id=record.id, source_id=source_id,
                operational_area_id=source.operational_area_id, feature_id=feature["id"],
                name=feature["properties"]["name"], kind=feature["properties"]["kind"])
                for feature in record.features])
            db.flush()
    except IntegrityError:
        # 同一来源并发提交由唯一约束兜底；其他约束失败不可伪装成成功。
        existing = db.query(InternalRoadImport).filter_by(
            source_id=source_id, input_sha256=preview["input_sha256"]).first()
        if existing is None:
            raise
        return describe_import(existing), False
    return describe_import(record), True


def read_import(db, source_id, import_id):
    authorized_source(db, source_id)
    record = db.query(InternalRoadImport).filter_by(id=import_id, source_id=source_id).first()
    if record is None:
        raise LookupError("道路版本不存在或不可访问")
    result = describe_import(record)
    reviews = db.query(InternalRoadReview).filter_by(import_id=import_id).order_by(InternalRoadReview.id).all()
    latest = {review.feature_id: review for review in reviews}
    result["feature_reviews"] = {
        feature["id"]: describe_review(latest[feature["id"]]) if feature["id"] in latest else None
        for feature in record.features
    }
    result["entrance_checks"] = entrance_checks(db, record)
    return result


def entrance_checks(db, record):
    """只检查声明的关联，不搜索/吸附最近道路，不借用未来来源资料。"""
    entrances = [feature for feature in record.features if feature["properties"]["kind"] == "entrance"]
    if not entrances:
        return []
    ids = {feature["properties"]["road_id"] for feature in entrances}
    version = InternalRoadFeatureVersion
    latest = db.query(version.feature_id.label("feature_id"), func.max(version.import_id).label("import_id"))\
        .filter(version.source_id == record.source_id, version.import_id <= record.id, version.feature_id.in_(ids))\
        .group_by(version.feature_id).subquery()
    versions = db.query(version).join(latest, and_(version.feature_id == latest.c.feature_id,
                                                 version.import_id == latest.c.import_id)).all()
    by_id = {item.feature_id: item for item in versions}
    batches = {item.id: item for item in db.query(InternalRoadImport).filter(
        InternalRoadImport.source_id == record.source_id,
        InternalRoadImport.id.in_({item.import_id for item in versions})).all()}
    output = []
    for entrance in entrances:
        identifier = entrance["properties"]["road_id"]
        target_version = by_id.get(identifier)
        batch = batches.get(target_version.import_id) if target_version else None
        target = next((feature for feature in batch.features if feature["id"] == identifier), None) if batch else None
        if target is None:
            status = "declared_road_missing"
        elif target["properties"]["kind"] != "road":
            status = "declared_target_not_road"
        else:
            geometry = target["geometry"]
            lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
            point = entrance["geometry"]["coordinates"]
            status = "coincident_endpoint_pending_verification" if any(point in (line[0], line[-1]) for line in lines)\
                else "coincident_vertex_pending_verification" if any(point in line for line in lines)\
                else "connection_geometry_pending_verification"
        output.append({"entrance_id": entrance["id"], "declared_road_id": identifier,
                       "road_import_id": batch.id if batch else None,
                       "road_source_sha256": batch.input_sha256 if batch else None,
                       "status": status, "connected": None, "routing_available": False,
                       "boundary": "只核对来源编号和节点位置；重合不代表实际连通，缺少节点匹配不代表不可达。未生成连接线。"})
    return output


class RoadReviewConflict(ValueError):
    pass


def road_catalog(db, source_id, after_feature=None, limit=20):
    """最新来源与仍有效的历史核验并列；不是可通行道路发布表。"""
    authorized_source(db, source_id)
    version = InternalRoadFeatureVersion
    latest = db.query(version.feature_id.label("feature_id"), func.max(version.import_id).label("import_id"))\
        .filter(version.source_id == source_id).group_by(version.feature_id).subquery()
    query = db.query(version).join(latest, and_(version.feature_id == latest.c.feature_id,
                                               version.import_id == latest.c.import_id))
    if after_feature is not None:
        query = query.filter(version.feature_id > after_feature)
    rows = query.order_by(version.feature_id).limit(limit + 1).all()
    selected = rows[:limit]
    ids = [row.feature_id for row in selected]
    # 每个历史来源版本只取最后决定；已撤回的核验不得复活。
    last_review = db.query(InternalRoadReview.import_id.label("import_id"), InternalRoadReview.feature_id.label("feature_id"),
                          func.max(InternalRoadReview.sequence).label("sequence"))\
        .join(InternalRoadImport, InternalRoadImport.id == InternalRoadReview.import_id)\
        .filter(InternalRoadImport.source_id == source_id, InternalRoadReview.feature_id.in_(ids))\
        .group_by(InternalRoadReview.import_id, InternalRoadReview.feature_id).subquery()
    reviews = db.query(InternalRoadReview).join(last_review, and_(
        InternalRoadReview.import_id == last_review.c.import_id,
        InternalRoadReview.feature_id == last_review.c.feature_id,
        InternalRoadReview.sequence == last_review.c.sequence)).all()
    by_version = {(review.import_id, review.feature_id): review for review in reviews}
    verified = {}
    for review in reviews:
        if review.decision == "verified" and (review.feature_id not in verified
                or review.import_id > verified[review.feature_id].import_id):
            verified[review.feature_id] = review
    items = []
    for row in selected:
        current = by_version.get((row.import_id, row.feature_id))
        historical = verified.get(row.feature_id)
        items.append({"source_feature_id": row.feature_id, "name": row.name, "kind": row.kind,
                      "latest_import_id": row.import_id,
                      "latest_review": describe_review(current) if current else None,
                      "last_verified_import_id": historical.import_id if historical else None,
                      "pending_update": bool(historical and historical.import_id != row.import_id),
                      "routing_available": False})
    return {"source_id": source_id, "items": items,
            "next_after_feature": selected[-1].feature_id if len(rows) > limit else None,
            "boundary": "来源资料目录，不代表已发布道路或通行许可；最新批次缺失的历史道路不自动删除"}


def compare_imports(db, source_id, before_id, after_id):
    """显式比较两个授权版本；缺失不代表删除，核验状态不跨版本继承。"""
    before = read_import(db, source_id, before_id)
    after = read_import(db, source_id, after_id)
    old = {feature["id"]: feature for feature in before["features"]}
    new = {feature["id"]: feature for feature in after["features"]}
    items = []
    counts = {"added": 0, "changed": 0, "unchanged": 0, "not_provided": 0}
    for identifier in sorted(old.keys() | new.keys()):
        left, right = old.get(identifier), new.get(identifier)
        state = "added" if left is None else "not_provided" if right is None else "unchanged" if left == right else "changed"
        fields = []
        if left is not None and right is not None:
            if left["geometry"] != right["geometry"]:
                fields.append("geometry")
            for key in sorted(left["properties"].keys() | right["properties"].keys()):
                if (key not in left["properties"] or key not in right["properties"]
                        or left["properties"][key] != right["properties"][key]):
                    fields.append(f"properties.{key}")
            # 保留未知来源扩展属性的变化，不丢弃顶层来源标记。
            for key in sorted((left.keys() | right.keys()) - {"id", "geometry", "properties"}):
                if key not in left or key not in right or left[key] != right[key]:
                    fields.append(key)
        old_review = before["feature_reviews"].get(identifier)
        counts[state] += 1
        items.append({"source_feature_id": identifier, "change": state, "changed_fields": fields,
                      "before": left, "after": right,
                      "before_review": old_review, "after_review": after["feature_reviews"].get(identifier),
                      "affects_verified_source": bool(old_review and old_review["decision"] == "verified"
                                                      and state in ("changed", "not_provided"))})
    return {"source_id": source_id, "before_id": before_id, "after_id": after_id,
            "before_sha256": before["input_sha256"], "after_sha256": after["input_sha256"],
            "items": items, "summary": counts, "mutations_applied": False, "routing_available": False,
            "boundary": "仅比较所选来源版本；未提供不代表删除，来源核验不代表通行许可"}


def list_imports(db, source_id, before_id=None, limit=20):
    authorized_source(db, source_id)
    query = db.query(InternalRoadImport).filter_by(source_id=source_id)
    if before_id is not None:
        query = query.filter(InternalRoadImport.id < before_id)
    rows = query.order_by(InternalRoadImport.id.desc()).limit(limit + 1).all()
    return {"items": [{"id": row.id, "source_id": row.source_id, "input_sha256": row.input_sha256,
                       "feature_count": len(row.features), "created_by": row.created_by,
                       "created_at": row.created_at.isoformat()} for row in rows[:limit]],
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


def review_history(db, source_id, import_id, feature_id, before_id=None, limit=20):
    authorized_source(db, source_id)
    record = db.query(InternalRoadImport).filter_by(id=import_id, source_id=source_id).first()
    if record is None or not any(f["id"] == feature_id for f in record.features):
        raise LookupError("道路版本或要素不存在")
    query = db.query(InternalRoadReview).filter_by(import_id=import_id, feature_id=feature_id)
    if before_id is not None:
        query = query.filter(InternalRoadReview.id < before_id)
    rows = query.order_by(InternalRoadReview.id.desc()).limit(limit + 1).all()
    return {"items": [describe_review(row) for row in rows[:limit]],
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


def describe_review(record):
    return {"id": record.id, "import_id": record.import_id, "feature_id": record.feature_id,
            "sequence": record.sequence, "decision": record.decision, "note": record.note,
            "evidence_reference": record.evidence_reference, "created_by": record.created_by,
            "created_at": record.created_at.isoformat(), "routing_available": False,
            "boundary": "仅核验来源资料，不代表已连接路网或拥有通行许可"}


def review_feature(db, source_id, import_id, feature_id, data, actor_id):
    authorized_source(db, source_id, write=True)
    record = db.query(InternalRoadImport).filter_by(id=import_id, source_id=source_id).with_for_update().first()
    if record is None or not any(f["id"] == feature_id for f in record.features):
        raise LookupError("道路版本或要素不存在")
    if data["input_sha256"] != record.input_sha256:
        raise RoadReviewConflict("来源版本已变化，请重新读取后核验")
    query = db.query(InternalRoadReview).filter_by(import_id=import_id, feature_id=feature_id)
    repeated = query.filter_by(request_key=data["request_key"]).first()
    if repeated:
        if (repeated.created_by != actor_id or any(getattr(repeated, key) != data[key]
                for key in ("decision", "note", "evidence_reference"))):
            raise RoadReviewConflict("重复请求标识对应不同决定")
        return describe_review(repeated), False
    previous = query.order_by(InternalRoadReview.sequence.desc()).first()
    if data["previous_review_id"] != (previous.id if previous else None):
        raise RoadReviewConflict("核验状态已变化，请刷新后重试")
    review = InternalRoadReview(
        import_id=import_id, operational_area_id=record.operational_area_id, feature_id=feature_id,
        sequence=(previous.sequence if previous else 0) + 1,
        request_key=data["request_key"], decision=data["decision"], note=data["note"],
        evidence_reference=data["evidence_reference"], created_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(review)
            db.flush()
    except IntegrityError:
        raise RoadReviewConflict("核验同时发生变化，请刷新后确认") from None
    return describe_review(review), True
