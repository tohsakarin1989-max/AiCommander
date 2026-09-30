from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models.agent_task import AgentTask

router = APIRouter()


@router.get("/tasks")
def list_tasks(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    # Legacy global results have no owner/scope provenance. Only an unrestricted
    # administrator may read them, including when new Agent execution is off.
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(401, detail="请先登录")
    if ((principal is not None and principal.role != "admin")
            or db.info.get("authorized_area_ids") is not None):
        raise HTTPException(403, detail="旧任务缺少可重验的范围来源，仅限全域管理员查看历史记录")
    rows = db.query(AgentTask).order_by(AgentTask.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": t.id,
            "query": t.query,
            "case_ids": t.case_ids,
            "status": t.status,
            "result": t.result,
            "created_at": str(t.created_at),
        }
        for t in rows
    ]
