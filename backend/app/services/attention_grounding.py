"""Read-only, source-deduplicated attention grounds; never a risk score.

The caller chooses the time basis and the complete authorized case collection.
This module does not assign discovery records to incident dates or rerun models.
"""
from collections import defaultdict
from datetime import timezone
from time import monotonic

from app.models.case import Case
from app.models.case_facility_association import CaseFacilityAssociation
from app.models.case_source import CaseLocation, CaseSourceLink
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource
from app.services.case_facility_association_service import view_association
from app.services.facility_condition_comparison import production_validity, profile_catalog, require_scope
from app.services.facility_source_access import attributes_sources_visible
from app.utils.geo import haversine_km

VERSION = "attention-grounding-8.1-1"
BOUNDARY = "明确关联、空间邻近、条件相似与生产背景分层；原文表述不等于已证实事实，不预测发案或形成风险分。"
CONDITION_CATEGORIES = {"method", "place_condition", "time_condition", "oil", "facility"}


def _batches(values):
    values = list(values)
    for offset in range(0, len(values), 400):
        yield values[offset:offset + 400]


def _source_groups(db, cases):
    """Only explicit source identity is deduplicated, never similar wording."""
    parents = {case.id: case.id for case in cases}
    sources, refs = {}, defaultdict(list)

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for batch in _batches(parents):
        for link in db.query(CaseSourceLink).join(Case, Case.id == CaseSourceLink.case_id).filter(
                Case.id.in_(batch)).order_by(CaseSourceLink.id):
            key = (link.source_type, link.source_id)
            if key in sources:
                left, right = root(link.case_id), root(sources[key])
                parents[max(left, right)] = min(left, right)
            sources[key] = link.case_id
            refs[link.case_id].append(f"case_source_link:{link.id}")
    return {identifier: root(identifier) for identifier in parents}, refs


def _layer(items, groups, *, boundary, gaps=(), state=None):
    identifiers = {identifier for row in items for identifier in row.get("case_ids", [])}
    refs = sorted({ref for row in items for ref in row.get("evidence_refs", [])})
    return {"state": state or ("ready" if items else "empty"), "items": items,
            "record_count": len({groups[identifier] for identifier in identifiers}),
            "raw_record_count": len(identifiers), "evidence_refs": refs,
            "gaps": list(gaps), "boundary": boundary}


def _condition_rows(records, groups, source_refs):
    grouped, polarities = defaultdict(list), defaultdict(set)
    for case, profile, assertions in records:
        for assertion in assertions:
            category, value = assertion["category"], assertion["value"]
            if category not in CONDITION_CATEGORIES:
                continue
            polarities[groups[case.id], category, value].add(assertion["kind"])
            if assertion["kind"] == "stated":
                grouped[category, value].append({"case_id": case.id, "profile_id": profile.id,
                    "source_revision_id": profile.source_revision_id, "source_hash": profile.source_hash,
                    "reference": assertion["reference"],
                    "evidence_refs": [f"case:{case.id}", f"case_profile:{profile.id}", *source_refs[case.id]]})
    result = []
    for (category, value), references in sorted(grouped.items()):
        references = [row for row in references
                      if polarities[groups[row["case_id"]], category, value] == {"stated"}]
        if not references:
            continue
        identifiers = sorted({row["case_id"] for row in references})
        count = len({groups[identifier] for identifier in identifiers})
        result.append({"category": category, "value": value, "kind": "stated", "case_ids": identifiers,
            "independent_count": count, "raw_record_count": len(identifiers),
            "occurrence": "repeated_conditions" if count >= 2 else "new_information",
            "references": references,
            "evidence_refs": sorted({ref for row in references for ref in row["evidence_refs"]})})
    return result


def _catalog(db, cases, records=None, coverage=None, *, deadline=None):
    groups, source_refs = _source_groups(db, cases)
    if records is None:
        records, coverage = [], {key: 0 for key in (
            "profiles_scanned", "profiles_current", "profiles_stale", "profiles_missing", "profiles_invalid", "profiles_partial")}
        for batch in _batches(cases):
            if deadline is not None and monotonic() >= deadline:
                break
            entries, counts = profile_catalog(db, batch)
            records.extend(entries)
            for key, count in counts.items():
                coverage[key] += count
    condition_rows = _condition_rows(records, groups, source_refs)
    ids = set(groups)
    links, points = defaultdict(list), defaultdict(list)
    catalog_complete = True
    for batch in _batches(ids):
        if deadline is not None and monotonic() >= deadline:
            catalog_complete = False
            break
        for row in db.query(CaseFacilityAssociation).filter(
                CaseFacilityAssociation.case_id.in_(batch), CaseFacilityAssociation.revoked_at.is_(None)):
            if deadline is not None and monotonic() >= deadline:
                catalog_complete = False
                break
            try:
                viewed = view_association(db, row)
            except PermissionError:
                continue
            if viewed["source_state"] == "current" and viewed["evidence_state"] == "available":
                links[row.asset_id].append({"case_ids": [row.case_id], "relation_kind": viewed["relation_type"],
                    "label": viewed["label"], "evidence_refs": [f"case:{row.case_id}", *viewed["evidence_refs"]]})
        for row in db.query(Event).filter(Event.related_case_id.in_(batch), Event.related_asset_id.isnot(None)):
            links[row.related_asset_id].append({"case_ids": [row.related_case_id],
                "relation_kind": "recorded_event_link", "label": "事件中的明确登记关联",
                "evidence_refs": [f"event:{row.id}", f"case:{row.related_case_id}", f"asset:{row.related_asset_id}"]})
        for row in db.query(CaseLocation).join(Case, Case.id == CaseLocation.case_id).filter(
                Case.id.in_(batch), CaseLocation.role.in_(("incident", "discovery")), CaseLocation.precision == "exact"):
            geometry = row.geometry or {}
            coords = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
            if (isinstance(geometry, dict) and geometry.get("type") == "Point" and len(coords) == 2
                    and all(type(value) in (int, float) for value in coords)
                    and -180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
                points[row.case_id].append((coords[1], coords[0], row.role, f"case_location:{row.id}"))
    # Legacy coordinates are background only; their incident role is not inferred.
    for case in cases:
        if not points[case.id] and case.latitude is not None and case.longitude is not None:
            points[case.id].append((case.latitude, case.longitude, "legacy_unknown", f"case:{case.id}"))
    return {"groups": groups, "conditions": condition_rows, "links": links, "points": points,
            "coverage": coverage, "cases": cases, "catalog_complete": catalog_complete}


def _facility(db, asset, catalog, *, production=None):
    from app.services.facility_dossier_content import _production
    production = production if production is not None else _production(db, asset)[0]
    groups = catalog["groups"]
    explicit = _layer(catalog["links"].get(asset.id, []), groups,
        boundary="所引材料明确登记该设施，不因此确认实际盗取来源；关联事件不增加案件数量。")
    nearby = []
    if asset.latitude is not None and asset.longitude is not None:
        for case_id, points in catalog["points"].items():
            matches = [(haversine_km(asset.latitude, asset.longitude, lat, lon), role, ref)
                       for lat, lon, role, ref in points
                       if abs(lat - asset.latitude) <= .01 and abs(lon - asset.longitude) <= .04]
            if not matches:
                continue
            distance, role, ref = min(matches)
            if distance <= 1:
                nearby.append({"case_ids": [case_id], "distance_km": round(distance, 4), "location_role": role,
                    "evidence_refs": [f"case:{case_id}", f"asset:{asset.id}", ref]})
    conditions = []
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    # Do not reuse a generic asset type or an unvalidated/stale production label as
    # evidence of matching conditions. These remain production background below.
    if (production["state"] not in {"restricted", "unavailable", "stale"} and asset.verified
            and production_validity(attributes)["current_state"] not in {"expired", "invalid", "not_yet_valid"}):
        expected = {"place_condition": attributes.get("place_conditions"),
                    "method": attributes.get("historical_methods")}
        for row in catalog["conditions"]:
            allowed = expected.get(row["category"])
            if isinstance(allowed, list) and row["value"] in allowed:
                conditions.append({**row, "evidence_refs": [*row["evidence_refs"], f"asset:{asset.id}"],
                    "applicability": "登记标签对照；未证明案发时或当前现场条件"})
    background = ({"state": "restricted", "gaps": ["生产来源当前不可读取"], "boundary": BOUNDARY}
                  if production["state"] == "restricted" else
                  {"state": production["state"], "items": production.get("items", []),
                   "gaps": sorted(set([*production.get("gaps", []),
                       *([] if attributes.get("defense_coverage_status") else ["未取得技防资料，不等于没有技防"])])),
                   "boundary": "生产背景与资料缺失不形成风险分；设施是否涉案须另有明确记录。"})
    layers = {"explicit_links": explicit,
        "spatial_proximity": _layer(nearby, groups, boundary="仅 1 公里直线邻近背景，不等于涉案、通行可达或真实来源。"),
        "condition_similarity": _layer(conditions, groups, boundary="只使用经原文校验的明确肯定条件；相似不是本设施涉案依据。"),
        "production_background": background}
    count = max(explicit["record_count"], max((row["independent_count"] for row in conditions), default=0))
    source_ids = set()
    if production["state"] != "restricted":
        if type(attributes.get("source_id")) is int:
            source_ids.add(attributes["source_id"])
        for metadata in (attributes.get("field_groups") or {}).values():
            if isinstance(metadata, dict) and type(metadata.get("source_id")) is int:
                source_ids.add(metadata["source_id"])
        source_ids.update(row["source_id"] for row in production.get("items", [])
                          if type(row.get("source_id")) is int)
    return {"object_key": f"asset:{asset.id}", "object_type": "facility", "object_id": asset.id,
        "label": asset.name, "state": "repeated_conditions" if count >= 2 else "new_information" if count else "background_only",
        "layers": layers, "support_record_count": count,
        "evidence_refs": sorted({ref for layer in layers.values() for row in layer.get("items", [])
                                 for ref in row.get("evidence_refs", [])}),
        "production_sources": [{"source_id": identifier, "operational_area_id": asset.operational_area_id}
                               for identifier in sorted(source_ids)],
        "gaps": sorted({gap for layer in layers.values() for gap in layer.get("gaps", [])}), "boundary": BOUNDARY}


def facility_attention_grounding(db, asset, cases, records, coverage, *, production):
    require_scope(db)
    with db.no_autoflush:
        catalog = _catalog(db, cases, records, coverage)
        return {"version": VERSION, **_facility(db, asset, catalog, production=production),
                "source_bindings": {"case_ids": sorted(case.id for case in cases), "asset_ids": [asset.id]},
                "coverage": {**coverage, "cases_scanned": len(cases), "selection": "complete_authorized_window"}}


def build_attention_grounding(db, area_id, case_ids, *, area_name, deadline=None):
    require_scope(db)
    allowed = db.info["authorized_area_ids"]
    if allowed is not None and area_id not in allowed:
        raise PermissionError("attention_area_forbidden")
    deadline = deadline if deadline is not None else monotonic() + 5
    with db.no_autoflush:
        requested = set(case_ids)
        cases = []
        for batch in _batches(requested):
            cases.extend(db.query(Case).populate_existing().filter(Case.id.in_(batch), Case.operational_area_id == area_id).all())
        if {case.id for case in cases} != requested:
            raise PermissionError("attention_case_sources_changed")
        cases.sort(key=lambda case: case.id)
        catalog = _catalog(db, cases, deadline=deadline)
        assets = db.query(JurisdictionAsset).populate_existing().filter_by(operational_area_id=area_id, status="active").order_by(JurisdictionAsset.id).all()
        # Scan the complete lightweight catalog first. Only the finally selected
        # objects need source-history queries and O(N) proximity enrichment.
        latest = {case.id: (case.created_at.replace(tzinfo=timezone.utc) if case.created_at
                           and case.created_at.tzinfo is None else case.created_at) for case in cases}
        def rank(explicit_count, count, identifiers, key):
            recorded = max((latest[identifier].timestamp() for identifier in identifiers if latest[identifier]), default=0)
            return (not bool(explicit_count), count < 2, -count, -recorded, key)
        candidates = []
        for asset in assets:
            links = catalog["links"].get(asset.id, [])
            linked = {identifier for row in links for identifier in row["case_ids"]}
            explicit_count = len({catalog["groups"][identifier] for identifier in linked})
            attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
            expected = {"method": attributes.get("historical_methods"), "place_condition": attributes.get("place_conditions")}
            matched = [row for row in catalog["conditions"] if asset.verified
                       and production_validity(attributes)["current_state"] not in {"expired", "invalid", "not_yet_valid"}
                       and isinstance(expected.get(row["category"]), list) and row["value"] in expected[row["category"]]]
            count = explicit_count or max((row["independent_count"] for row in matched), default=0)
            if count:
                ids = linked if explicit_count else {identifier for row in matched for identifier in row["case_ids"]}
                candidates.append((rank(explicit_count, count, ids, f"asset:{asset.id}"), asset))
        # One area object merges all grounded regional conditions, not one task per tag.
        conditions = [row for row in catalog["conditions"] if row["category"] in {"method", "place_condition", "time_condition"}]
        if conditions:
            count = max(row["independent_count"] for row in conditions)
            regional = {"object_key": f"area:{area_id}", "object_type": "area", "object_id": area_id,
                "label": area_name, "state": "repeated_conditions" if count >= 2 else "new_information",
                "support_record_count": count,
                "layers": {"condition_similarity": _layer(conditions, catalog["groups"], boundary=BOUNDARY)},
                "evidence_refs": sorted({ref for row in conditions for ref in row["evidence_refs"]}),
                "gaps": ["同一条件重复登记不证明因果关系或统一作案主体。"], "boundary": BOUNDARY}
            ids = {identifier for row in conditions for identifier in row["case_ids"]}
            candidates.append((rank(0, count, ids, regional["object_key"]), regional))
        candidates.sort(key=lambda row: row[0])
        selected, examined = [], 0
        complete = catalog["coverage"]["profiles_scanned"] == len(cases) and catalog["catalog_complete"]
        for _, candidate in candidates:
            if monotonic() >= deadline:
                complete = False
                break
            item = candidate if isinstance(candidate, dict) else _facility(db, candidate, catalog)
            examined += 1
            if item["state"] != "background_only":
                selected.append(item)
            if len(selected) == 3:
                break
        gaps = [] if complete else ["关注对象读取预算已用尽，仅展示已核验部分，未宣称全域最优。"]
        for key, label in (("profiles_missing", "缺少保存画像"), ("profiles_stale", "画像已过期"),
                           ("profiles_invalid", "原文引用校验失败"), ("profiles_partial", "画像提取范围不完整")):
            if catalog["coverage"][key]:
                gaps.append(f"{catalog['coverage'][key]} 起记录{label}，缺少条件不能解释为没有该情况。")
        return {"version": VERSION, "items": selected,
            "coverage": {**catalog["coverage"], "cases_scanned": len(cases),
                "independent_records": len(set(catalog["groups"].values())), "facilities_scanned": len(assets),
                "enriched_objects": examined, "display_limit": 3, "selection": "complete_authorized_window",
                "state": "complete" if complete else "partial", "ranking_complete": complete,
                "data_state": "ready" if not gaps else "partial", "information_gaps": gaps},
            "source_bindings": {"case_ids": sorted(requested), "asset_ids": [row["object_id"] for row in selected if row["object_type"] == "facility"]},
            "boundary": BOUNDARY}


def attention_sources_visible(db, snapshot):
    bindings = snapshot.get("source_bindings", {})
    ids = set(bindings.get("case_ids", []))
    visible = {row[0] for batch in _batches(ids) for row in db.query(Case.id).filter(Case.id.in_(batch))}
    asset_ids = set(bindings.get("asset_ids", []))
    assets = [row for batch in _batches(asset_ids) for row in db.query(JurisdictionAsset).filter(JurisdictionAsset.id.in_(batch))]
    if visible != ids or {row.id for row in assets} != asset_ids:
        return False
    items = snapshot.get('items', [snapshot] if snapshot.get('object_key') else [])
    event_ids = {int(ref.split(':', 1)[1]) for item in items
                 for ref in item.get('evidence_refs', []) if ref.startswith('event:')}
    visible_events = {row[0] for batch in _batches(event_ids) for row in db.query(Event.id).filter(Event.id.in_(batch))}
    if visible_events != event_ids:
        return False
    recorded_sources = {(row["source_id"], row["operational_area_id"])
                        for item in items for row in item.get("production_sources", [])}
    source_ids = {identifier for identifier, _ in recorded_sources}
    visible_sources = {(row.id, row.operational_area_id) for batch in _batches(source_ids)
                       for row in db.query(MapSource).filter(MapSource.id.in_(batch), MapSource.status == "active")}
    if visible_sources != recorded_sources:
        return False
    from app.services.facility_dossier_content import _production
    return all(attributes_sources_visible(db, row.attributes or {}, row.operational_area_id)
               and _production(db, row)[0]["state"] != "restricted" for row in assets)


def attention_recommendations(snapshot):
    results = []
    for item in snapshot["items"]:
        repeated = item["state"] == "repeated_conditions"
        support = []
        explicit = item["layers"].get("explicit_links", {})
        if explicit.get("record_count"):
            support.append(f"明确登记关联 {explicit['record_count']} 起独立来源记录；不因此确认该设施实际涉案。")
        for row in item["layers"].get("condition_similarity", {}).get("items", []):
            support.append(f"{row['value']}：{row['independent_count']} 起独立来源记录；" +
                           ("重复出现的明确表述。" if row["independent_count"] >= 2 else "仅一条新增情况，不称为规律。"))
        results.append({"title": f"{item['label']}：{'已有重复条件依据' if repeated else '新增情况参考'}",
            "target_area": item["label"], "time_window": "本期所选时间口径，具体时段以原始记录为准",
            "suggested_action": "按需查阅已有记录及差异，结合现场已知情况判断是否关注；不自动形成任务。",
            "resource_assumption": "未给定人员、车辆或巡查量，不预设部署资源。",
            "expected_effect": "提供可引用的关注依据，不宣称犯罪风险或防控效果。",
            "evidence_refs": item["evidence_refs"], "supporting_evidence": support,
            "information_gaps": item["gaps"], "confidence": 0.0})
    return results
