"""Compatibility projection for the sole revision/outbox/profile pipeline.

Nothing here turns old free-form features into current analysis. The old JSON
remains readable, but freshness comes exclusively from the saved profile.
"""
from datetime import timezone

from sqlalchemy import func

from app.models.case import Case
from app.models.case_pipeline import CasePipelineState, OutboxEvent
from app.models.preprocess_job import PreprocessJob
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_saved_profile import read_saved_profile


def current_profile(db, case):
    saved = read_saved_profile(db, case)
    return saved["data"] if saved["status"] == "ready" else None


def ensure_profile(db, case, *, event_id=None):
    """Explicit maintenance write entry; ordinary GET never invokes it."""
    case_id = case.id
    saved = current_profile(db, case)
    if saved:
        return saved
    if event_id is None:
        event = CasePipelineService.enqueue_case_change(db, case)
        state = db.query(CasePipelineState).filter_by(case_id=case_id).first()
        event_id = event.id if event else (state.event_id if state else None)
        db.commit()
    if event_id:
        event = db.query(OutboxEvent).filter_by(id=event_id).first()
        if event is None or event.aggregate_id != str(case_id) or event.event_type != "case.analysis.requested":
            raise ValueError("preprocess_event_mismatch")
        CasePipelineService.process_event(db, event_id)
    db.expire_all()
    case = db.query(Case).filter_by(id=case_id).first()
    return current_profile(db, case) if case is not None else None


def profile_features(saved):
    """Read-only legacy shape from frozen profile inputs, not another analysis."""
    payload = saved["payload"]
    standard, facts, quality = (payload.get(key) or {} for key in ("standard", "analysis_facts", "quality"))
    sources = {item["field"]: item["text"] for item in
               (payload.get("semantics", {}).get("source_snapshot", {}).get("fields") or [])}
    capabilities = payload.get("analysis_readiness") or {}
    readiness = {key: value.get("status") for key, value in capabilities.items() if isinstance(value, dict)}
    oil = {"oil_type": standard.get("oil_type"), "oil_nature": standard.get("oil_nature"),
           "volume": facts.get("oil_volume"), "volume_unit": facts.get("oil_volume_unit") or "unknown",
           "value": facts.get("oil_value"), "water_cut": facts.get("water_cut"),
           "facility_type": standard.get("facility_type")}
    return {
        "preprocess_mode": "versioned_profile", "confidence": None,
        "profile_model_status": payload.get("semantics", {}).get("model_extraction", {}).get("status", "not_enabled"),
        "profile_binding": {"id": saved["id"], "version": saved["version"],
            "source_hash": saved["source_hash"], "source_revision_id": payload.get("source_revision_id"),
            "schema_version": saved["schema_version"], "dictionary_version": saved["dictionary_version"]},
        "basic": {"title": payload.get("case_number"), "summary": sources.get("description", ""),
                  "summary_kind": "source_excerpt_not_model_summary", "case_type": standard.get("case_type"),
                  "time": standard.get("occurred_time"), "time_precision": standard.get("time_precision"),
                  "occurred_from": standard.get("occurred_from"), "occurred_to": standard.get("occurred_to"),
                  "location": standard.get("location")},
        "geo": {"latitude": facts.get("latitude"), "longitude": facts.get("longitude"),
                "place_type": standard.get("facility_type")},
        "facts": {"oil": oil}, "oil": {"facts": oil},
        "scene_conditions": {"target_object": standard.get("facility_type"),
                             "monitoring_status": "技防/照明/监控情况待核实"},
        "flow": {"upstream_source": facts.get("upstream_source"),
                 "downstream_destination": [facts["downstream_destination"]] if facts.get("downstream_destination") else []},
        "management": {"report_quality_score": quality.get("score"), "report_quality_level": quality.get("level"),
                       "missing_fields": [item["label"] for item in quality.get("missing_required", [])],
                       "recommended_completion_actions": quality.get("recommendations", [])},
        "analysis_readiness": {**readiness, "spacetime": readiness.get("regional_analysis"),
                               "area_profile": "ready" if facts.get("latitude") is not None and facts.get("longitude") is not None else "missing_geo"},
        "capabilities": quality.get("capabilities"), "tags": [value for value in
            (standard.get("case_type"), standard.get("oil_nature"), standard.get("modus_operandi")) if value],
        "inferences": [], "recommendations": [], "semantics": payload.get("semantics"),
        "boundary": "规则画像与原文摘录；模型摘要单独展示，历史 features 不作为当前完成标记。",
    }


def queue_status(db):
    """Current pipeline only; old job counters are explicitly historical."""
    status = func.coalesce(OutboxEvent.status, CasePipelineState.status)
    counts = dict(db.query(status, func.count(CasePipelineState.id)).outerjoin(
        OutboxEvent, CasePipelineState.event_id == OutboxEvent.id).group_by(status).all())
    states = db.query(CasePipelineState).filter(CasePipelineState.completed_at.isnot(None)).order_by(
        CasePipelineState.completed_at.desc()).limit(100).all()
    durations = []
    for state in states:
        if state.completed_at and state.requested_at:
            start, end = state.requested_at, state.completed_at
            start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
            end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
            if end >= start:
                durations.append((end - start).total_seconds())
    return {"source": "case_revision_outbox_profile", "schema_version": "preprocess-status-7.1",
        "pending": sum(counts.get(item, 0) for item in ("pending", "degraded", "retry")),
        "processing": counts.get("processing", 0),
        "success": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "avg_duration_seconds": sum(durations) / len(durations) if durations else None,
        "legacy_history": {"source": "preprocess_jobs", "count": db.query(PreprocessJob).count(),
                           "boundary": "历史记录，不代表当前任务队列或当前画像是否有效。"}}
