"""独立 Agent Lab 队列任务。"""
import asyncio

from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.config import settings
from app.database import SessionLocal
from app.tasks.celery_app import celery_app
from app.utils.logger import logger


@celery_app.task(
    name="aicommander.agent.execute",
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
    track_started=True,
)
def execute_agent_run_task(self, run_id: str):
    db = SessionLocal()
    result = None
    retry_error = None
    try:
        result = asyncio.run(asyncio.wait_for(
            AgentRunExecutor().execute(db, run_id),
            timeout=settings.AGENT_TIMEOUT_SECONDS,
        ))
        if result.status == "failed":
            retry_error = RuntimeError(result.error_message or "agent_execution_failed")
    except TimeoutError as exc:
        db.rollback()
        result = AgentRunService.mark_execution_failed(
            db,
            run_id,
            reason="agent_timeout",
        )
        retry_error = exc
    except Exception as exc:
        db.rollback()
        logger.error(f"Agent 任务执行失败 run_id={run_id}: {type(exc).__name__}")
        result = AgentRunService.mark_execution_failed(
            db,
            run_id,
            reason=type(exc).__name__,
        )
        retry_error = exc
    finally:
        db.close()

    if retry_error is not None and self.request.retries < self.max_retries:
        raise self.retry(
            exc=retry_error,
            countdown=min(2 ** self.request.retries, 30),
        )
    return result.id


@celery_app.task(name="aicommander.agent.expire_approvals")
def expire_agent_approvals_task() -> int:
    db = SessionLocal()
    try:
        return AgentRunService.expire_stale_approvals(db)
    finally:
        db.close()
