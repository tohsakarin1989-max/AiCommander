from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.agent_task import AgentTask
from app.services.agent_service import AgentService

router = APIRouter()


@router.post("/run")
async def run_agent(query: str, case_ids: Optional[List[int]] = None, db: Session = Depends(get_db)):
    if not query:
        raise HTTPException(status_code=400, detail="query不能为空")
    task = await AgentService.run_task(db, query=query, case_ids=case_ids)
    return {
        "id": task.id,
        "query": task.query,
        "case_ids": task.case_ids,
        "status": task.status,
        "result": task.result,
        "created_at": str(task.created_at),
    }


@router.get("/tasks")
def list_tasks(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
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
