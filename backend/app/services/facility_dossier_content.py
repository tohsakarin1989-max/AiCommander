"""Facility-side aggregation of recorded sources; no analysis or writes on read."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import select

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_result import CaseResultSnapshot
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.event import Event
from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, MapFeatureClaim, MapSource, MapSnapshot
from app.models.meeting import Meeting
from app.models.report import Report
from app.services.case_result_access import require_result_access
from app.services.case_result_service import CaseResultService
from app.services.case_result_snapshot import assemble_case_result
from app.services.case_road_artifact_service import read_road_artifact
from app.services.facility_condition_comparison import (
    case_brief, compare_facility, event_brief, facility_brief, in_window, iso,
    production_validity, profile_catalog, require_scope, window_values,
)
from app.services.internal_road_service import read_import
from app.services.jurisdiction_service import TECH_TYPES
from app.utils.geo import haversine_km


SCHEMA_VERSION = "facility-dossier-5.4-1"
BOUNDARY = "明确记录、空间邻近与系统候选分别呈现；关联不认定实际来源，缺失资料不代表没有问题，本页不生成分析或风险分。"
SECTION_LIMIT = 100
PRODUCTION_FIELDS = {
    "oil_type": "油品", "owner_unit": "所属单位", "production_unit": "生产单位",
    "production_status": "生产状态", "facility_category": "设施类别",
    "production_output": "产量", "water_cut_min": "含水率下限", "water_cut_max": "含水率上限",
    "water_cut_unit": "含水率单位", "production_valid_from": "生产条件有效起始",
    "production_valid_to": "生产条件有效截止",
}


def section(items=(), *, state=None, gaps=(), boundary=BOUNDARY, total=None):
    items = list(items)
    if state == "restricted":
        return {"state": state, "gaps": list(gaps) or ["当前权限无法读取该项资料"], "boundary": boundary}
    count = len(items) if total is None else total
    return {"state": state or ("partial" if count > SECTION_LIMIT else "ready" if items else "empty"),
            "items": items[:SECTION_LIMIT], "total": count, "gaps": list(gaps), "boundary": boundary}


def item(identifier, label, *, evidence_refs=(), support=(), counter=(), gaps=(), **values):
    return {"id": identifier, "label": label, "evidence_refs": list(evidence_refs),
            "support": list(support), "counter": list(counter), "gaps": list(gaps), **values}


def _source_visible(db, source_id, asset):
    return db.query(MapSource.id).filter(MapSource.id == source_id,
        MapSource.operational_area_id == asset.operational_area_id, MapSource.status == "active").first() is not None


def _production(db, asset):
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    if attributes.get("source_id") is not None and not _source_visible(db, attributes["source_id"], asset):
        return section(state="restricted"), {}
    versions = db.query(JurisdictionAssetVersion).join(JurisdictionAsset,
        JurisdictionAsset.id == JurisdictionAssetVersion.asset_id).filter(
            JurisdictionAsset.id == asset.id).order_by(JurisdictionAssetVersion.version).all()
    claims = {}
    stored_refs = asset.source_claim_refs or []
    if not isinstance(stored_refs, list) or any(type(ref) is not int or ref < 1 for ref in stored_refs):
        return section(state="unavailable", gaps=["设施来源引用格式不完整，未推断来源版本"]), {}
    claim_ids = set(stored_refs) | {version.source_claim_id for version in versions if version.source_claim_id is not None}
    for claim_id in claim_ids:
        claim = db.query(MapFeatureClaim).filter_by(id=claim_id, asset_id=asset.id).first()
        if claim is None or not _source_visible(db, claim.source_id, asset):
            return section(state="restricted"), {}
        claims[claim.id] = claim
    evidence = [f"asset:{asset.id}", *(f"map_claim:{identifier}" for identifier in sorted(claims))]
    items = [item(key, label, detail=str(attributes[key]), value=attributes[key], evidence_refs=evidence)
             for key, label in PRODUCTION_FIELDS.items() if attributes.get(key) is not None]
    history = []
    for version in versions:
        snapshot = version.snapshot if isinstance(version.snapshot, dict) else {}
        allowed = db.info["authorized_area_ids"]
        if (allowed is not None and snapshot.get("operational_area_id") is not None
                and snapshot["operational_area_id"] not in allowed):
            return section(state="restricted"), {}
        version_attributes = snapshot.get("attributes") or {}
        if version_attributes.get("source_id") is not None and not _source_visible(db, version_attributes["source_id"], asset):
            return section(state="restricted"), {}
        claim = claims.get(version.source_claim_id)
        history.append({"version_id": version.id, "version": version.version,
            "name": snapshot.get("name"), "external_id": snapshot.get("external_id"),
            "source_claim_id": version.source_claim_id, "source_revision": claim.source_revision if claim else None,
            "created_at": iso(version.created_at), "change_type": version.change_type})
    for claim in claims.values():
        items.append(item(f"claim:{claim.id}", "台账来源", detail=claim.source_revision,
            source_id=claim.source_id, run_id=claim.run_id, row_number=claim.row_number,
            source_record_id=claim.source_record_id, source_revision=claim.source_revision,
            evidence_refs=[f"map_claim:{claim.id}"]))
    for version in history:
        items.append(item(f"asset_version:{version['version_id']}", "历史名称与版本",
            detail=version["name"], evidence_refs=[f"asset_version:{version['version_id']}"], **version))
    gaps = []
    if not claims:
        gaps.append("尚无可追溯的台账行来源；不补造台账编号")
    if not versions:
        gaps.append("尚无保存的历史名称版本")
    if not asset.verified:
        gaps.append("设施资料尚未核验")
    state = "ready" if items else "missing"
    validity = production_validity(attributes)
    if validity["current_state"] == "expired":
        state = "stale"
        gaps.append("生产条件有效期已结束，历史资料仍保留，不作为当前有效条件")
    elif validity["current_state"] in {"invalid", "not_yet_valid"}:
        state = "partial" if items else "missing"
        gaps.append("生产条件有效期无效或尚未生效，不能确认当前时效")
    elif validity["current_state"] == "unknown" and any(attributes.get(key) is not None for key in PRODUCTION_FIELDS):
        gaps.append("登记生产属性有效期未知，不证明当前或案发时条件")
    return section(items, state=state, gaps=gaps,
                   boundary="只展示已记录属性和同一稳定编号的来源版本；历史名称不用于自动合并设施。"), {
        "asset_version_ids": [row["version_id"] for row in history],
        "source_claim_ids": sorted(claims), "source_revision": attributes.get("source_revision")}


def _recorded_events(db, asset, start, end):
    events = in_window(db.query(Event).populate_existing().filter(Event.related_asset_id == asset.id),
                       Event.occurred_time, start, end).order_by(Event.occurred_time.desc(), Event.id).all()
    links, records, case_ids = [], [], set()
    for event in events:
        case = None
        if event.related_case_id is not None:
            case = db.query(Case).populate_existing().filter_by(id=event.related_case_id).first()
            if case is None:
                return section(state="restricted"), section(state="restricted"), set()
        evidence = [f"event:{event.id}", f"asset:{asset.id}"]
        records.append(item(event.id, event.title or event.event_number, evidence_refs=evidence,
            detail=event.description, **{key: value for key, value in event_brief(event).items() if key != "id"}))
        if case is not None:
            # The relationship is a recorded link, even if observation review
            # is confirmed. It never means the well was confirmed oil source.
            at = case.occurred_time
            at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
            case_in_window = (start is None or at >= start) and (end is None or at < end)
            if case_in_window:
                case_ids.add(case.id)
            links.append(item(f"event:{event.id}:case:{case.id}", case.case_number,
                evidence_refs=[*evidence, f"case:{case.id}"], case_id=case.id, event_id=event.id,
                review_status=event.review_status or "pending_review", relation_kind="recorded_event_link",
                case_in_window=case_in_window, occurred_time=iso(case.occurred_time),
                detail="事件记录同时关联该案件与设施，复核状态保留原记录",
                counter=["事件复核状态不等于确认实际盗取来源"],
                gaps=[] if case_in_window else ["该关联案件发生时间不在当前时间窗，不纳入窗口内案件统计"]))
    return section(links), section(records, boundary="仅收录原始事件明确记录的设施编号，不将最近井自动分配提升为关联事实。"), case_ids


def _nearby(db, asset, start, end):
    if asset.latitude is None or asset.longitude is None:
        return section(state="missing", gaps=["设施缺少坐标，未推断空间邻近案件"])
    cases = in_window(db.query(Case).populate_existing().filter(Case.latitude.isnot(None), Case.longitude.isnot(None)),
                      Case.occurred_time, start, end).order_by(Case.id)
    rows = []
    for case in cases:
        distance = haversine_km(asset.latitude, asset.longitude, case.latitude, case.longitude)
        if distance <= 1.0:
            rows.append(item(case.id, case.case_number, evidence_refs=[f"case:{case.id}", f"asset:{asset.id}"],
                distance_km=round(distance, 4), **{key: value for key, value in case_brief(case).items() if key not in {"id", "title"}},
                counter=["空间邻近不证明该设施涉案"]))
    rows.sort(key=lambda row: (row["distance_km"], row["case_id"]))
    return section(rows, boundary="按当前已记录坐标计算 1 公里直线邻近，不代表道路可达或实际涉案关系。")


def _targets(refs, asset_id):
    if not isinstance(refs, list):
        return False
    return any(isinstance(ref, str) and re.fullmatch(rf"map_asset:{asset_id}@snapshot:[A-Za-z0-9_-]{{1,36}}", ref)
               for ref in refs or [])


def _candidates_and_results(db, asset, start, end, linked_case_ids):
    cases = in_window(db.query(Case.id), Case.occurred_time, start, end).subquery()
    hypotheses = db.query(CaseHypothesis).filter(CaseHypothesis.case_id.in_(select(cases.c.id))).order_by(CaseHypothesis.id).all()
    candidates, results = [], []
    restricted_candidates = restricted_results = False
    unavailable_candidates = unavailable_results = False
    for hypothesis in hypotheses:
        if not _targets(hypothesis.evidence_refs, asset.id):
            continue
        run = db.query(CaseAnalysisRun).filter_by(id=hypothesis.analysis_run_id).first()
        profile = db.query(CaseAnalysisProfile).filter_by(id=run.case_profile_id).first() if run else None
        try:
            if profile is None or run is None:
                raise PermissionError()
            peers = db.query(CaseHypothesis).filter_by(analysis_run_id=run.id).all()
            snapshot = assemble_case_result(profile, run, peers)
            require_result_access(db, snapshot)
        except PermissionError:
            restricted_candidates = True
            continue
        except (ValueError, TypeError, KeyError, AttributeError):
            unavailable_candidates = True
            continue
        candidates.append(item(hypothesis.id, hypothesis.title, detail=hypothesis.claim,
            case_id=hypothesis.case_id, analysis_run_id=run.id, status=hypothesis.status,
            evidence_refs=hypothesis.evidence_refs, support=hypothesis.supporting_evidence,
            counter=hypothesis.counter_evidence, gaps=hypothesis.information_gaps,
            map_snapshot_id=run.map_snapshot_id, profile_id=profile.id,
            relation_kind="system_candidate", boundary=hypothesis.boundary))
    for row in db.query(CaseResultSnapshot).filter(CaseResultSnapshot.case_id.in_(select(cases.c.id))).order_by(CaseResultSnapshot.id):
        content = row.content if isinstance(row.content, dict) else {}
        saved_candidates = content.get("candidates")
        if not isinstance(saved_candidates, list):
            unavailable_results = unavailable_results or row.case_id in linked_case_ids
            continue
        if row.case_id not in linked_case_ids and not any(_targets(candidate.get("evidence_refs"), asset.id)
                for candidate in saved_candidates if isinstance(candidate, dict)):
            continue
        try:
            saved = CaseResultService.read(db, row.id)
        except PermissionError:
            restricted_results = True
            continue
        except (ValueError, KeyError, TypeError, AttributeError):
            unavailable_results = True
            continue
        results.append(item(row.id, "案件研判成果", case_id=row.case_id,
            result_id=row.id, created_at=iso(row.created_at), content_sha256=saved["content_sha256"],
            evidence_refs=[f"case_result:{row.id}"], versions=saved["content"]["versions"]))
    for row in db.query(CaseRoadArtifact).filter(CaseRoadArtifact.case_id.in_(select(cases.c.id))).order_by(CaseRoadArtifact.id):
        content = row.content if isinstance(row.content, dict) else {}
        comparison = content.get("result") or {}
        target = content.get("target") or {}
        if not isinstance(comparison, dict) or not isinstance(target, dict):
            unavailable_results = unavailable_results or row.case_id in linked_case_ids
            continue
        saved_candidates = comparison.get("candidates", [])
        if not isinstance(saved_candidates, list):
            unavailable_results = unavailable_results or row.case_id in linked_case_ids
            continue
        matched = [candidate for candidate in saved_candidates if isinstance(candidate, dict) and candidate.get("asset_id") == asset.id]
        if not matched and target.get("asset_id") != asset.id:
            continue
        try:
            saved = read_road_artifact(db, row.id)
        except PermissionError:
            restricted_candidates = restricted_results = True
            continue
        except (ValueError, KeyError, TypeError, AttributeError):
            unavailable_candidates = unavailable_results = True
            continue
        for candidate in matched:
            candidates.append(item(f"road:{row.id}:{asset.id}", candidate.get("name") or asset.name,
                case_id=row.case_id, artifact_id=row.id, relation_kind="system_candidate",
                evidence_refs=candidate.get("evidence_refs", []), support=candidate.get("supporting_evidence", []),
                counter=candidate.get("counter_evidence", []), gaps=candidate.get("information_gaps", []),
                detail="已保存的道路及生产条件候选比较", versions=saved["content"].get("calculation")))
        results.append(item(f"road:{row.id}", "道路研判成果", case_id=row.case_id,
            artifact_id=row.id, created_at=iso(row.created_at), evidence_refs=[f"road_artifact:{row.id}"]))
    # Historical meeting reports keep their original source, never converted
    # into a new facility conclusion. Re-authorize every recorded member case.
    for report, meeting in db.query(Report, Meeting).join(Meeting, Meeting.meeting_id == Report.meeting_id).order_by(Report.id):
        if not isinstance(meeting.case_ids, list) or any(type(value) is not int for value in meeting.case_ids):
            continue  # No trustworthy link to this facility can be established.
        members = set(meeting.case_ids)
        if not members.intersection(linked_case_ids):
            continue
        visible = {row[0] for row in db.query(Case.id).filter(Case.id.in_(members))}
        if visible != members:
            restricted_results = True
            continue
        results.append(item(f"report:{report.id}", "历史会议报告", report_id=report.id,
            meeting_id=meeting.meeting_id, case_ids=sorted(members), created_at=iso(report.created_at),
            evidence_refs=[f"report:{report.id}"], detail="通过事件明确记录的案件关联；保留原会议来源"))
    candidate_section = section(candidates, state="restricted" if restricted_candidates else
        "partial" if unavailable_candidates and candidates else "unavailable" if unavailable_candidates else None,
        gaps=["部分历史候选来源不完整，未展开内容"] if unavailable_candidates else [])
    return candidate_section, section(results, state="restricted" if restricted_results else
        "partial" if unavailable_results and results else "unavailable" if unavailable_results else None,
        gaps=["部分历史成果资料损坏，未展开内容"] if unavailable_results else [])


def _roads(db, asset):
    rows = db.query(InternalRoadFeatureVersion, InternalRoadImport).join(InternalRoadImport,
        InternalRoadImport.id == InternalRoadFeatureVersion.import_id).join(MapSource,
        MapSource.id == InternalRoadImport.source_id).filter(
            InternalRoadImport.operational_area_id == asset.operational_area_id,
            MapSource.status == "active", InternalRoadFeatureVersion.kind == "entrance").order_by(
                InternalRoadFeatureVersion.import_id.desc()).all()
    seen, imports, items = set(), {}, []
    for version, batch in rows:
        key = (version.source_id, version.feature_id)
        if key in seen:
            continue
        seen.add(key)
        feature = next((row for row in batch.features if row.get("id") == version.feature_id), None)
        if not feature or (feature.get("properties") or {}).get("facility_asset_id") != asset.id:
            continue
        try:
            if batch.id not in imports:
                imports[batch.id] = read_import(db, batch.source_id, batch.id)
            checks = imports[batch.id]["entrance_checks"]
        except (PermissionError, LookupError):
            return section(state="restricted")
        except (ValueError, KeyError, TypeError):
            return section(state="unavailable", gaps=["入口来源资料不完整，未推断连接状态"])
        check = next((row for row in checks if row["entrance_id"] == version.feature_id), {})
        properties = feature.get("properties") or {}
        items.append(item(f"entrance:{batch.id}:{version.feature_id}", properties.get("name") or version.name,
            source_id=version.source_id, import_id=batch.id, feature_id=version.feature_id,
            evidence_refs=[f"internal_road_entrance:{batch.id}:{version.feature_id}"],
            detail="已记录设施入口；核验与通行许可分别展示", conditions=properties.get("conditions", {}),
            facility_link_verified=check.get("facility_link_verified", False),
            connection_status=check.get("status", "unknown"), review_id=check.get("connection_review_id"),
            road_import_id=check.get("road_import_id"), input_sha256=batch.input_sha256,
            geometry=feature.get("geometry"), routing_available=False,
            gaps=[] if check.get("facility_link_verified") else ["设施入口关联尚未完成核验"],
            counter=["已记录入口或节点重合不代表实际道路连通或已获通行许可"]))
    return section(items, state=None if items else "missing", gaps=[] if items else ["尚无可用的明确设施入口记录"],
                   boundary="只读取已保存的入口来源与核验；本次读取不计算道路、不推断设施内部连通或案发路线。")


def _tech(db, asset):
    if asset.latitude is None or asset.longitude is None:
        return section(state="missing", gaps=["设施坐标未知，无法核对邻近技防资料"])
    rows = []
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    if attributes.get("defense_coverage_status"):
        rows.append(item("recorded_coverage", "已登记技防状态", detail=str(attributes["defense_coverage_status"]),
                         evidence_refs=[f"asset:{asset.id}"], counter=["登记状态仍须结合有效期与现场核验"]))
    for tech in db.query(JurisdictionAsset).populate_existing().filter(JurisdictionAsset.asset_type.in_(TECH_TYPES),
            JurisdictionAsset.status == "active", JurisdictionAsset.latitude.isnot(None), JurisdictionAsset.longitude.isnot(None)):
        distance = haversine_km(asset.latitude, asset.longitude, tech.latitude, tech.longitude)
        if distance <= 0.5:
            rows.append(item(tech.id, tech.name, detail="500 米以内登记的技防要素",
                asset_id=tech.id, asset_type=tech.asset_type, distance_km=round(distance, 4),
                verified=bool(tech.verified), evidence_refs=[f"asset:{tech.id}"],
                counter=["空间邻近不证明设备覆盖该设施，也不证明设备当前在线"]))
    return section(rows, state=None if rows else "missing", gaps=[] if rows else ["未取得技防资料，不等于没有技防"],
                   boundary="仅展示已登记状态和邻近设备；缺资料不判定为无覆盖，不用区域设备总数推定单井覆盖。")


def build_dossier_content(db, asset_id, *, start_date=None, end_date=None):
    require_scope(db)
    start, end = window_values(start_date, end_date)
    with db.no_autoflush:
        asset = db.query(JurisdictionAsset).populate_existing().filter_by(id=asset_id).first()
        if asset is None:
            raise PermissionError("facility_unavailable")
        production, source_versions = _production(db, asset)
        links, events, linked_case_ids = _recorded_events(db, asset, start, end)
        candidates, results = _candidates_and_results(db, asset, start, end, linked_case_ids)
        cases = in_window(db.query(Case).populate_existing(), Case.occurred_time, start, end).order_by(Case.id).all()
        profiles, coverage = profile_catalog(db, cases)
        comparison = compare_facility(asset, profiles, coverage) if production["state"] != "restricted" else None
        history = section(state="restricted") if comparison is None else section([
            item(row["case_id"], row["title"], case_id=row["case_id"],
                evidence_refs=row["evidence_refs"], support=row["similar"], counter=row["different"],
                gaps=row["gaps"], profile_id=row["profile_id"], occurred_time=row["occurred_time"],
                historical_conditions=row["historical_conditions"], detail="；".join(row["historical_conditions"]) or None)
            for row in comparison["reference_cases"]], state="partial" if comparison["state"] != "stale" and comparison["reference_total"] > len(comparison["reference_cases"]) else comparison["state"],
            gaps=comparison["gaps"], total=comparison["reference_total"], boundary=comparison["boundary"])
        snapshots = db.query(MapSnapshot).filter_by(operational_area_id=asset.operational_area_id, status="current").order_by(MapSnapshot.id).all()
        sections = {"production": production, "record_links": links, "nearby_cases": _nearby(db, asset, start, end),
            "candidate_links": candidates, "events": events, "results": results, "roads": _roads(db, asset),
            "tech_defense": section(state="restricted") if production["state"] == "restricted" else _tech(db, asset),
            "history_conditions": history}
        return {"schema_version": SCHEMA_VERSION, "facility": facility_brief(asset),
            "filters": {"start_date": iso(start), "end_date": iso(end)}, "sections": sections,
            "versions": {"schema_version": SCHEMA_VERSION, "asset_updated_at": iso(asset.updated_at),
                "read_mode": "live_authorized_sources",
                "section_sources": {key: {"read_mode": "live", "state": value["state"],
                    "evidence_refs": sorted({ref for row in value.get("items", []) for ref in row["evidence_refs"]})}
                    for key, value in sections.items()},
                "map_snapshot_id": snapshots[0].id if len(snapshots) == 1 else None,
                "map_snapshots": [{"id": row.id, "version": row.version} for row in snapshots],
                **source_versions, **coverage},
            "gaps": sorted({gap for value in sections.values() for gap in value["gaps"]}), "boundary": BOUNDARY}
