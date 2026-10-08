"""Reuse authorized history retrieval as conditional references, not asset links."""
from datetime import datetime, timezone
import json

from app.models.case import Case
from app.services.case_history_retrieval import CaseHistoryRetrieval, source_values
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload
from app.services.case_semantic_service import TERMS
from app.services.facility_temporal_conditions import case_window, knowledge_context

VERSION = "facility-history-7.3-1"


def history_context(db, source: dict, *, known_at=None, knowledge_mode=None) -> dict:
    content = source["content"]
    standard = content["facts_summary"]["recorded_fields"]
    query = "。".join(str(standard.get(key) or "") for key in ("modus_operandi", "facility_type", "oil_type", "location"))[:2000]
    mode, cutoff = knowledge_context(known_at=known_at, knowledge_mode=knowledge_mode, frozen=True)
    result = {"version": VERSION, "state": "information_missing", "records": [],
              "knowledge_mode": mode, "known_at": cutoff.isoformat(), "late_supplement": False,
              "historical_text_coverage": "partial" if mode == "as_known" else "current_authorized_index",
              "boundary": "历史相似条件用于设施类型参照，不证明这些历史案件涉及本设施。"}
    window = case_window(standard)
    occurred = window.get("valid_at") or window.get("valid_from")
    try:
        before = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        before = before.replace(tzinfo=timezone.utc) if before.tzinfo is None else before
    except (AttributeError, ValueError):
        return {**result, "reason": "案件缺少明确时间，未选取历史条件参照"}
    if not query.replace("。", "").strip():
        return {**result, "reason": "案件未形成可检索的明确条件"}
    found = CaseHistoryRetrieval.search(db, query=query, source_case_id=content["case_id"],
                                      filters={"end_date": before}, limit=20)
    records, omitted, seen_cases, later_omitted = [], 0, set(), 0
    for item in found["items"]:
        # Confirmed experience cards remain available in v5.1 history UI. Do not
        # reinterpret an experience summary as a formal facility association.
        if item["source_type"] != "case":
            continue
        if item["case_id"] in seen_cases:
            continue  # Multiple matched fragments are still one historical case.
        case = db.query(Case).populate_existing().filter_by(id=item["case_id"]).first()
        if case is None:
            raise PermissionError("facility_history_access_changed")
        from app.services.case_source_service import CaseSourceService
        revision = CaseSourceService.latest_revision(db, case.id)
        received = revision.created_at if revision else case.updated_at or case.created_at
        received = received.replace(tzinfo=timezone.utc) if received and received.tzinfo is None else received
        if mode == "as_known" and (received is None or received > cutoff):
            later_omitted += 1
            continue  # Current index cannot stand in for unavailable old text.
        incident = case.occurred_time
        if incident is None:
            incident = case.occurred_to
        if incident is None:
            continue
        incident = incident.replace(tzinfo=timezone.utc) if incident.tzinfo is None else incident
        if incident >= before:
            continue  # Overlapping uncertain cases are not definitely earlier.
        values = source_values(case)
        signature = snapshot_payload(freeze_sources(values))["sha256"]
        if signature != item["versions"]["source_text_hash"]:
            raise ValueError("facility_history_source_changed")
        if len(json.dumps(values, ensure_ascii=False).encode()) > 64_000:
            omitted += 1
            continue
        # A matched process fragment and its parent case remain different
        # evidence layers. Formal oil/facility fields come from the validated
        # parent index; they are not invented members of the matched event.
        shared = [row for row in item.get("source_shared_conditions", item["shared_conditions"]) if row[2] == "stated"]
        if not any(row[0] in {"method", "place_condition", "upstream_clue", "downstream_clue", "action"} for row in shared):
            continue
        seen_cases.add(case.id)
        records.append({"case_id": case.id, "source_text_hash": signature, "source_fields": values,
                        "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
                        "versions": item["versions"], "shared_conditions": shared,
                        "source_revision_id": revision.id if revision else None,
                        "known_at": received.isoformat() if received else None,
                        "late_supplement": bool(received and received > before),
                        "different_conditions": item.get("source_different_conditions", item["different_conditions"]),
                        "references": item.get("evidence_refs", []), "fragment": item.get("fragment")})
    return {**result, "state": "partial" if mode == "as_known" and found["state"] == "ready" else found["state"], "coverage": found["coverage"],
            "coverage_time_basis": "current_authorized_index_not_historical_total",
            "late_supplement": any(row["late_supplement"] for row in records), "later_revisions_omitted": later_omitted,
            "historical_text_boundary": "当时已知模式只使用当前索引中在截止前已存在且未被后来修订的文本；未重建旧索引，不代表当时历史全集。" if mode == "as_known" else "使用本次授权下已知文本回看历史，后来补录明确标识。",
            "retrieval_version": found["query_context"]["retrieval_version"],
            "query_sha256": found["query_context"]["query_sha256"], "before": before.isoformat(),
            "semantic_index_state": found["semantic_index_state"], "mode": found["mode"],
            "retrieved_sources": len(found["items"]), "reference_limit": 20,
            "oversized_sources_omitted": omitted, "records": records}


def facility_history_match(context: dict, *, asset_type: str, oil_type, verified: bool) -> dict:
    result = {"state": "unknown", "case_ids": [], "support": [], "counter": [], "gaps": []}
    types = {"well": {"油井", "井口"}, "pipeline_node": {"输油管线"}, "valve": {"阀门"}}
    if not verified or not types.get(asset_type):
        result["gaps"].append("设施类型资料不足，未套用历史案件条件")
        return result
    for record in context["records"]:
        shared = [row for row in record["shared_conditions"] if row[2] == "stated"]
        if not any(row[0] in {"method", "place_condition", "upstream_clue", "downstream_clue", "action"} for row in shared):
            continue
        fields = record["source_fields"]
        formal_facility = TERMS["facility"].get(fields.get("facility_type"), fields.get("facility_type"))
        formal_oil = fields.get("oil_type")
        if formal_facility not in types[asset_type] or not oil_type or formal_oil != oil_type:
            continue
        if any(row[0] in {"facility", "oil", "method", "action"} for row in record["different_conditions"]):
            continue
        if not any(row[0] == "facility" and row[1] in types[asset_type] for row in shared):
            continue
        result["case_ids"].append(record["case_id"])
    if result["case_ids"]:
        result["state"] = "matched"
        result["support"].append(f"本轮历史检索中有 {len(result['case_ids'])} 项明确条件及油品、设施类型可参照；不是全库数量统计")
        result["counter"].append("历史案例的类型条件相似不证明其与本设施存在实际涉案关系")
    else:
        result["gaps"].append("本轮未取得同时满足明确历史条件、油品及设施类型的参照，不等于没有历史关联")
    if context["state"] != "ready" or context.get("oversized_sources_omitted"):
        result["gaps"].append("历史检索或证据保留未完整覆盖，结果只代表本轮取得的参考")
    return result


def validate_history_access(db, context: dict, *, require_fresh=False):
    for record in context["records"]:
        case = db.query(Case).populate_existing().filter_by(id=record["case_id"]).first()
        if case is None:
            raise PermissionError("facility_history_access_changed")
        if require_fresh and "source_revision_id" in record:
            from app.services.case_source_service import CaseSourceService
            latest = CaseSourceService.latest_revision(db, case.id)
            if (latest.id if latest else None) != record["source_revision_id"]:
                raise ValueError("facility_history_source_changed")
        if require_fresh and (snapshot_payload(freeze_sources(source_values(case)))["sha256"] != record["source_text_hash"]
                or (case.occurred_time.isoformat() if case.occurred_time else None) != record["occurred_time"]):
            raise ValueError("facility_history_source_changed")
