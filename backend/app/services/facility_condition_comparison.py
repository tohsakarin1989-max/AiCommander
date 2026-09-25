"""Read-only facility comparisons using saved, currently valid case profiles."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math

from sqlalchemy import or_, select

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSource, OperationalArea
from app.services.case_pipeline_service import ANALYSIS_RELEVANT_FIELDS, CasePipelineService
from app.services.facility_candidate_pool import FACILITY_TERMS, SOURCE_EXCLUDED
from app.services.facility_production_conditions import _instant, production_comparison
from app.services.profile_aggregate import checked_profile
from app.services.scorers.dual_domain_v34 import SOURCE_TYPES
from app.utils.datetimes import utc_datetime


SCHEMA_VERSION = "facility-conditions-5.4-1"
MAP_LIMIT = 500
REFERENCE_LIMIT = 5
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))
BOUNDARY = "仅对照授权范围内已有生产资料与有效案件画像；条件相似不证明实际涉案，不预测发案或形成风险评分。"


def require_scope(db):
    if "authorized_area_ids" not in db.info:
        raise PermissionError("facility_scope_required")


def iso(value):
    if isinstance(value, datetime):
        return utc_datetime(value).isoformat()
    return value.isoformat() if value is not None else None


def window_values(start_date=None, end_date=None):
    def parse(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, date):
            result = datetime.combine(value, time.min)
        else:
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("facility_window_invalid") from None
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    start, end = parse(start_date), parse(end_date)
    if start and end and start >= end:
        raise ValueError("facility_window_invalid")
    return start, end


def in_window(query, column, start, end):
    if start:
        query = query.filter(column >= start)
    if end:
        query = query.filter(column < end)
    return query


def case_brief(case):
    return {"id": case.id, "case_id": case.id, "case_number": case.case_number,
            "title": case.case_number, "case_type": case.case_type, "location": case.location,
            "occurred_time": iso(case.occurred_time), "latitude": case.latitude,
            "longitude": case.longitude, "operational_area_id": case.operational_area_id}


def event_brief(event):
    return {"id": event.id, "event_id": event.id, "event_number": event.event_number,
            "title": event.title or event.event_number, "event_type": event.event_type,
            "occurred_time": iso(event.occurred_time), "latitude": event.latitude,
            "longitude": event.longitude, "operational_area_id": event.operational_area_id,
            "related_case_id": event.related_case_id, "related_asset_id": event.related_asset_id,
            "review_status": event.review_status or "pending_review"}


def facility_brief(asset):
    return {"id": asset.id, "name": asset.name, "type": asset.asset_type,
            "asset_type": asset.asset_type, "operational_area_id": asset.operational_area_id,
            "external_id": asset.external_id, "latitude": asset.latitude,
            "longitude": asset.longitude, "verified": bool(asset.verified), "status": asset.status,
            "verification_state": asset.verification_state, "source": asset.source,
            "canonical_key": asset.canonical_key, "valid_from": iso(asset.valid_from), "valid_to": iso(asset.valid_to)}


HASH_DETAIL_FIELDS = (
    ("vehicles", CaseVehicle, ("vehicle_type", "road_vehicle_kind", "height_m", "gross_weight_t", "color", "brand", "model", "plate_number", "oil_volume", "water_cut", "custody_location", "current_location", "handling_status", "transferred_to_police", "transfer_time", "transfer_document_no")),
    ("persons", CasePerson, ("name", "gender", "id_number", "home_address", "phone", "role", "handling_status")),
    ("evidence", CaseEvidence, ("evidence_type", "title", "file_path", "requirement_key", "captured_at", "latitude", "longitude", "is_sensitive", "meta")),
    ("oil_recovery", OilRecoveryRecord, ("oil_nature", "volume_tons", "water_cut", "source", "receiver", "handled_at", "handling_method")),
)


def current_source_hashes(db, cases):
    """Same canonical source contract as the pipeline, with four batched reads.

    A regression test compares hashes against source_hash(), including all
    detail tables. No source text is extracted or analyzed here.
    """
    ids = [case.id for case in cases]
    details = {identifier: {name: [] for name, _, _ in HASH_DETAIL_FIELDS} for identifier in ids}
    for offset in range(0, len(ids), 400):
        for name, model, fields in HASH_DETAIL_FIELDS:
            for row in db.query(model).populate_existing().filter(model.case_id.in_(ids[offset:offset + 400])).order_by(model.id):
                details[row.case_id][name].append(CasePipelineService._model_values(row, fields))
    hashes = {}
    for case in cases:
        payload = {"case": {key: CasePipelineService._json_value(getattr(case, key))
                    for key in sorted(ANALYSIS_RELEVANT_FIELDS)
                    if key not in {"vehicles", "persons", "evidence", "oil_recovery"}}, **details[case.id]}
        hashes[case.id] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return hashes


def profile_catalog(db, cases):
    """Scan every authorized case; checking a hash does not re-extract its text."""
    ids = [case.id for case in cases]
    profiles = {}
    # Batches avoid database parameter limits without imposing a history cutoff.
    for offset in range(0, len(ids), 400):
        for profile in db.query(CaseAnalysisProfile).populate_existing().filter(
                CaseAnalysisProfile.case_id.in_(ids[offset:offset + 400]),
                CaseAnalysisProfile.is_current.is_(True)).order_by(
                    CaseAnalysisProfile.profile_version.desc(), CaseAnalysisProfile.id):
            profiles.setdefault(profile.case_id, profile)
    hashes = current_source_hashes(db, [case for case in cases if case.id in profiles])
    records, stale, missing, invalid, partial = [], 0, 0, 0, 0
    for case in cases:
        profile = profiles.get(case.id)
        if profile is None:
            missing += 1
            continue
        payload = profile.payload if isinstance(profile.payload, dict) else {}
        if (payload.get("source_hash") != profile.source_hash
                or payload.get("case_id", case.id) != case.id
                or profile.source_hash != hashes[case.id]):
            stale += 1
            continue
        assertions, state = checked_profile(db, case, profile, current_hash=hashes[case.id])
        if state not in {"ready", "partial"}:
            invalid += 1
            continue
        partial += state == "partial"
        records.append((case, profile, assertions))
    return records, {"profiles_scanned": len(cases), "profiles_current": len(records),
                     "profiles_stale": stale, "profiles_missing": missing,
                     "profiles_invalid": invalid, "profiles_partial": partial}


def production_validity(attributes, *, at=None):
    """Explicit periods describe historical applicability, not timeless truth."""
    start = _instant(attributes.get("production_valid_from"), require_timezone=True)
    end = _instant(attributes.get("production_valid_to"), require_timezone=True)
    now = datetime.now(timezone.utc)
    invalid = (attributes.get("production_valid_from") is not None and start is None
               or attributes.get("production_valid_to") is not None and end is None
               or start is not None and end is not None and start >= end)
    current = ("invalid" if invalid else "expired" if end is not None and end <= now else
               "not_yet_valid" if start is not None and start > now else
               "current" if start is not None and end is not None else "unknown")
    incident = "unknown"
    if not invalid and start is not None and end is not None and at is not None:
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
        incident = "covered" if start <= at < end else "outside"
    return {"current_state": current, "incident_state": incident, "valid_from": iso(start), "valid_to": iso(end)}


def compare_facility(asset, records, coverage):
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    gaps = []
    validity = production_validity(attributes)
    validity_gap = {
        "expired": "生产资料当前已过期；仅在明确覆盖旧案时段时保留历史参照，不作为当前有效条件",
        "not_yet_valid": "生产资料尚未生效，不作为当前有效生产条件",
        "unknown": "登记生产属性未提供完整有效期，时效未知；标签对照不证明案发时或当前条件",
        "invalid": "生产资料有效期不完整或无效，未据此推断历史适用范围",
    }.get(validity["current_state"])
    if validity_gap:
        gaps.append(validity_gap)
    if not asset.verified:
        gaps.append("设施资料尚未核验，不能形成肯定条件对照")
    if not attributes.get("oil_type"):
        gaps.append("设施油品资料未知")
    if coverage["profiles_missing"]:
        gaps.append("部分案件尚无保存画像，未重新抽取原文")
    if coverage["profiles_stale"]:
        gaps.append("部分画像与当前案件版本不一致，已排除过期画像")
    if coverage["profiles_invalid"]:
        gaps.append("部分画像原文引用校验失败，未用于条件对照")
    if coverage["profiles_partial"]:
        gaps.append("部分画像提取范围不完整，仅使用已验证的保存条件")
    references = []
    counts = Counter()
    for case, profile, assertions in records:
        payload = profile.payload
        standard = payload.get("standard") or {}
        similar, different, unknown, historical = [], [], [], []
        historical_production = False
        incident_validity = production_validity(attributes, at=case.occurred_time)
        kinds = {}
        for assertion in assertions:
            kinds.setdefault((assertion["category"], assertion["value"]), set()).add(assertion["kind"])
        conflicts = {key for key, values in kinds.items() if {"stated", "negated"} <= values}
        # Do not promote negated/uncertain assertions, even if a standard field
        # happens to contain the same label.
        for category, field, expected, label in (
            ("facility", "facility_type", FACILITY_TERMS.get(asset.asset_type, set()), "设施类型"),
            ("oil", "oil_type", {attributes["oil_type"]} if attributes.get("oil_type") else set(), "油品"),
        ):
            value = standard.get(field)
            opposing = any(item.get("category") == category and item.get("kind") != "stated"
                           for item in assertions if isinstance(item, dict))
            if opposing:
                unknown.append(f"历史{label}含否定或不确定表述，未作为相似证据")
            elif not asset.verified or not expected or not value:
                unknown.append(f"{label}资料不完整")
            elif category == "oil" and incident_validity["incident_state"] == "outside":
                unknown.append("台账生产有效期不覆盖该案发时段，未用登记油品作比较")
            elif category == "oil" and validity["current_state"] in {"expired", "not_yet_valid", "invalid"}:
                if incident_validity["incident_state"] == "covered":
                    historical.append(f"历史台账有效期覆盖该案发时段，油品{'相同' if value in expected else '不同'}：{value}；不表示当前油品条件")
                    historical_production = True
                else:
                    unknown.append("生产油品资料当前不可作为有效条件，历史适用时间亦未确认")
            elif category == "oil" and validity["current_state"] == "unknown":
                (similar if value in expected else different).append(f"登记油品{'相同' if value in expected else '不同'}（时效未知）：{value}")
                unknown.append("油品仅作登记标签对照，未确认当前及案发时有效性")
            elif value in expected:
                similar.append(f"{label}相符：{value}")
            else:
                different.append(f"历史{label}为{value}，与设施已知条件不同")
        for category, key, label in (("place_condition", "place_conditions", "地点条件"),
                                     ("method", "historical_methods", "历史手法条件")):
            expected = attributes.get(key)
            expected = set(expected) if isinstance(expected, list) and all(isinstance(x, str) for x in expected) else set()
            for item in assertions:
                if not isinstance(item, dict) or item.get("category") != category:
                    continue
                value = item.get("value")
                if (category, value) in conflicts:
                    unknown.append(f"历史{label}“{value}”肯定与否定并存，未作为相似证据")
                elif item.get("kind") != "stated":
                    unknown.append(f"历史{label}存在非肯定或未核验表述")
                elif expected and asset.verified:
                    (similar if value in expected else different).append(f"{label}：{value}")
                else:
                    historical.append(f"{label}参考：{value}")
                    unknown.append(f"历史记录{label}“{value}”；设施资料没有对应条件可核对")
        production = production_comparison(attributes=attributes, verified=asset.verified,
            case_fields=standard, case_facts=payload.get("analysis_facts") or {})
        if validity["current_state"] in {"expired", "not_yet_valid"}:
            historical_production = historical_production or production["state"] in {"matched", "different"}
            historical.extend(f"历史含水率参照：{entry}；不表示当前生产条件" for entry in production["support"])
            if production["state"] == "different":
                historical.extend(f"历史含水率差异：{entry}" for entry in production["counter"])
        else:
            similar.extend(production["support"])
            different.extend(production["counter"] if production["state"] == "different" else [])
        unknown.extend(production["gaps"])
        if validity_gap:
            unknown.append(validity_gap)
        if not similar and not different and not historical_production:
            counts["unknown"] += 1
            continue
        counts["comparable"] += 1
        counts["similar"] += bool(similar)
        counts["different"] += bool(different)
        references.append({"case_id": case.id, "title": case.case_number,
            "occurred_time": iso(case.occurred_time), "profile_id": profile.id,
            "similar": sorted(set(similar)), "different": sorted(set(different)),
            "historical_conditions": sorted(set(historical)),
            "historical_conditions_boundary": "历史手法与地点条件仅作参照，不构成本设施当前事实",
            "production_validity": incident_validity,
            "gaps": sorted(set(unknown)), "evidence_refs": [f"case:{case.id}", f"case_profile:{profile.id}", f"asset:{asset.id}"],
            "boundary": BOUNDARY})
    references.sort(key=lambda row: (-len(row["similar"]), row["case_id"]))
    state = "ready" if references else "missing"
    if any(coverage[key] for key in ("profiles_missing", "profiles_stale", "profiles_invalid", "profiles_partial")):
        state = "partial" if references else "stale" if coverage["profiles_stale"] else "missing"
    if validity["current_state"] == "expired":
        state = "stale"
    elif validity["current_state"] in {"not_yet_valid", "invalid"} and references:
        state = "partial"
    return {"state": state, "reference_cases": references[:REFERENCE_LIMIT],
            "reference_total": len(references), "comparison_counts": dict(counts),
            "representative_limit": REFERENCE_LIMIT, "coverage": coverage, "production_validity": validity,
            "gaps": gaps, "boundary": BOUNDARY}


def compare_visible_facility(db, asset, records, coverage):
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    source_id = attributes.get("source_id")
    if source_id is not None and db.query(MapSource.id).filter(
            MapSource.id == source_id, MapSource.operational_area_id == asset.operational_area_id,
            MapSource.status == "active").first() is None:
        return {"state": "restricted", "gaps": ["当前权限无法读取生产属性来源"], "boundary": BOUNDARY}
    return compare_facility(asset, records, coverage)


def visible_events_query(db):
    """Linked object movement/revocation must not expose cached event details."""
    return db.query(Event).filter(
        or_(Event.related_case_id.is_(None), Event.related_case_id.in_(select(Case.id))),
        or_(Event.related_asset_id.is_(None), Event.related_asset_id.in_(select(JurisdictionAsset.id))))


def build_region_content(db, *, operational_area_id=None, start_date=None, end_date=None, page=1, page_size=20):
    require_scope(db)
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("facility_pagination_invalid")
    start, end = window_values(start_date, end_date)
    if operational_area_id is not None:
        allowed = db.info["authorized_area_ids"]
        if allowed is not None and operational_area_id not in allowed:
            raise PermissionError("facility_area_unavailable")
        with db.no_autoflush:
            area = db.query(OperationalArea).filter_by(id=operational_area_id, status="active").first()
        if area is None:
            raise PermissionError("facility_area_unavailable")
    else:
        area = None
    with db.no_autoflush:
        assets_query = db.query(JurisdictionAsset).populate_existing().filter(
            JurisdictionAsset.status == "active", JurisdictionAsset.asset_type.in_(SOURCE_TYPES),
            or_(JurisdictionAsset.source.is_(None), JurisdictionAsset.source.notin_(SOURCE_EXCLUDED)))
        cases_query = in_window(db.query(Case).populate_existing(), Case.occurred_time, start, end)
        events_query = in_window(visible_events_query(db).populate_existing(), Event.occurred_time, start, end)
        snapshots_query = db.query(MapSnapshot).filter(MapSnapshot.status == "current")
        if operational_area_id is not None:
            assets_query = assets_query.filter(JurisdictionAsset.operational_area_id == operational_area_id)
            cases_query = cases_query.filter(Case.operational_area_id == operational_area_id)
            events_query = events_query.filter(Event.operational_area_id == operational_area_id)
            snapshots_query = snapshots_query.filter(MapSnapshot.operational_area_id == operational_area_id)
        facility_total = assets_query.count()
        assets = assets_query.order_by(JurisdictionAsset.id).offset((page - 1) * page_size).limit(page_size).all()
        cases = cases_query.order_by(Case.occurred_time.desc(), Case.id).all()
        events = events_query.order_by(Event.occurred_time.desc(), Event.id).all()
        records, profile_coverage = profile_catalog(db, cases)
        # Each facility page compares the entire authorized case history;
        # pagination limits facilities, never the history being compared.
        facilities = [{**facility_brief(asset), "condition_comparison": compare_visible_facility(db, asset, records, profile_coverage)} for asset in assets]
        snapshots = [{"id": row.id, "version": row.version, "operational_area_id": row.operational_area_id}
                     for row in snapshots_query.order_by(MapSnapshot.id).all()]
        case_times = {case.id: utc_datetime(case.occurred_time).astimezone(BUSINESS_TIMEZONE) for case in cases}
        event_times = {event.id: utc_datetime(event.occurred_time).astimezone(BUSINESS_TIMEZONE) for event in events}
        hours = Counter((stamp.weekday(), stamp.hour) for stamp in case_times.values())
        case_months = Counter(stamp.strftime("%Y-%m") for stamp in case_times.values())
        event_months = Counter(stamp.strftime("%Y-%m") for stamp in event_times.values())
        linked = sum(event.related_case_id is not None for event in events)
        window_case_ids = {case.id for case in cases}
        linked_outside = sum(event.related_case_id is not None and event.related_case_id not in window_case_ids for event in events)
        partial = len(cases) > MAP_LIMIT or len(events) > MAP_LIMIT or any(profile_coverage[key] for key in
            ("profiles_missing", "profiles_stale", "profiles_invalid", "profiles_partial"))
        spatial = Counter((case_times[case.id].strftime("%Y-%m"), math.floor(case.latitude / .02), math.floor(case.longitude / .02))
            for case in cases if case.latitude is not None and case.longitude is not None)
        return {"schema_version": SCHEMA_VERSION,
            "scope": {"operational_area_id": operational_area_id, "area_name": area.name if area else "全部授权区域",
                      "authorized_area_ids": list(db.info["authorized_area_ids"]) if db.info["authorized_area_ids"] is not None else None},
            "window": {"start_date": iso(start), "end_date": iso(end)},
            "facilities": {"items": facilities, "total": facility_total, "page": page, "page_size": page_size},
            "cases": {"items": [case_brief(row) for row in cases[:MAP_LIMIT]], "total": len(cases),
                      "missing_coordinates": sum(row.latitude is None or row.longitude is None for row in cases)},
            "events": {"items": [{**event_brief(row), "case_in_window": row.related_case_id in window_case_ids if row.related_case_id is not None else None}
                                  for row in events[:MAP_LIMIT]], "total": len(events),
                       "linked_case_count": linked, "linked_case_outside_window_count": linked_outside,
                       "independent_count": len(events) - linked},
            "statistics": {"timezone": "Asia/Shanghai", "facility_count": facility_total, "case_count": len(cases), "event_count": len(events),
                "independent_event_count": len(events) - linked, "case_and_independent_event_count": len(cases) + len(events) - linked,
                "page_facilities_with_reference": sum(bool(row["condition_comparison"].get("reference_total")) for row in facilities),
                "hour_day": [{"weekday": day, "hour": hour, "count": count} for (day, hour), count in sorted(hours.items())],
                "spatial_grid_degrees": .02,
                "spatial_monthly": [{"month": month, "cell_latitude": round((lat + .5) * .02, 6),
                    "cell_longitude": round((lon + .5) * .02, 6), "case_count": count}
                    for (month, lat, lon), count in sorted(spatial.items())],
                "monthly": [{"month": month, "case_count": case_months[month], "event_count": event_months[month]} for month in sorted(case_months.keys() | event_months.keys())]},
            "versions": {"comparison_version": SCHEMA_VERSION, "read_mode": "live_authorized_sources", "map_snapshots": snapshots,
                         "map_snapshot_id": snapshots[0]["id"] if len(snapshots) == 1 else None},
            "coverage": {"state": "partial" if partial else "complete", "case_limit": MAP_LIMIT, "event_limit": MAP_LIMIT,
                "cases_truncated": len(cases) > MAP_LIMIT, "events_truncated": len(events) > MAP_LIMIT,
                "facility_comparison_scope": "current_page_against_all_authorized_profiles", "facility_page_count": len(facilities),
                "event_reference_visibility": "authorized_only", **profile_coverage}, "boundary": BOUNDARY}
