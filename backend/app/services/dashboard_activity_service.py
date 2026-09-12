"""Read-only activity projections from persisted records, never an audit log."""
from sqlalchemy import String, cast, func

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_result import CaseResultSnapshot
from app.services.case_result_access import CaseResultAccessError, require_result_access
from app.utils.datetimes import utc_datetime


def dashboard_activity(db, cases, analysis_query, *, start, end, limit=20):
    limit = max(1, min(100, limit))
    activities = []

    def record(case, key, kind, title, timestamp, **extra):
        return {"id": key, "kind": kind, "title": title,
                "recorded_at": utc_datetime(timestamp), "case_id": case.id,
                "case_number": case.case_number, "latitude": case.latitude,
                "longitude": case.longitude, **extra}

    for field, kind, title in ((Case.created_at, "case_created", "新案件已入库"),
                               (Case.updated_at, "case_updated", "案件资料最近更新")):
        query = cases.filter(field >= start, field < end)
        if kind == "case_updated":
            query = query.filter(Case.updated_at > Case.created_at)
        for case in query.order_by(field.desc(), Case.id.desc()).limit(limit):
            timestamp = case.created_at if kind == "case_created" else case.updated_at
            activities.append(record(case, f"{kind}:{case.id}:{timestamp.isoformat()}", kind, title, timestamp))

    # Outbox rows have no general updated_at: report creation time with current state,
    # not an invented timestamp for a retry/failure transition. Never expose payload/error.
    tasks = db.query(OutboxEvent).filter(
        OutboxEvent.aggregate_type == "case",
        OutboxEvent.aggregate_id.in_(cases.with_entities(cast(Case.id, String))),
        OutboxEvent.event_type.in_(["case.analysis.requested", "case.insights.requested"]),
        OutboxEvent.status.in_(["pending", "processing", "retry", "failed"]),
        OutboxEvent.created_at >= start, OutboxEvent.created_at < end)
    processing = {status: 0 for status in ("pending", "processing", "retry", "failed")}
    processing.update(dict(tasks.with_entities(OutboxEvent.status, func.count(OutboxEvent.id))
                           .group_by(OutboxEvent.status).all()))
    labels = {"pending": "排队中", "processing": "处理中", "retry": "等待重试", "failed": "失败"}
    for task in tasks.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(limit):
        case = cases.filter(Case.id == int(task.aggregate_id)).first()
        if case is not None:
            stage = "资料准备" if task.event_type == "case.analysis.requested" else "案件研判"
            activities.append(record(case, f"task:{task.id}:{task.status}:{task.attempts}", "task",
                f"{stage}任务：{labels[task.status]}", task.created_at, status=task.status,
                detail="任务创建时间；展示当前状态"))

    completion = {"completed": 0, "degraded": 0}
    from app.models.case_insight import CaseAnalysisRun
    completion.update(dict(analysis_query.with_entities(CaseAnalysisRun.status, func.count(CaseAnalysisRun.id))
                           .group_by(CaseAnalysisRun.status).all()))
    for run in analysis_query.order_by(CaseAnalysisRun.completed_at.desc(), CaseAnalysisRun.id.desc()).limit(limit):
        case = cases.filter(Case.id == run.case_id).first()
        if case is not None:
            activities.append(record(case, f"analysis:{run.id}", "analysis",
                "案件研判完成" if run.status == "completed" else "案件研判降级完成",
                run.completed_at, status=run.status))

    results = []
    snapshots = db.query(CaseResultSnapshot).filter(
        CaseResultSnapshot.case_id.in_(cases.with_entities(Case.id)),
        CaseResultSnapshot.created_at >= start, CaseResultSnapshot.created_at < end,
    ).order_by(CaseResultSnapshot.created_at.desc(), CaseResultSnapshot.id.desc())
    for snapshot in snapshots.yield_per(100):
        try:
            require_result_access(db, {"content_sha256": snapshot.content_sha256, "content": snapshot.content})
        except CaseResultAccessError:
            continue
        case = cases.filter(Case.id == snapshot.case_id).first()
        if case is None:
            continue
        item = record(case, f"result:{snapshot.id}", "result", "案件成果已保存",
                      snapshot.created_at, result_id=snapshot.id)
        results.append(item)
        activities.append(item)
        if len(results) >= max(5, limit):
            break

    activities.sort(key=lambda item: (item["recorded_at"], item["id"]), reverse=True)
    return {"activities": activities[:limit], "activity_limit": limit,
            "processing": processing, "recent_results": results[:5], "completion": completion}
