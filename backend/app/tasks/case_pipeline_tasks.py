"""可靠消费案件治理 Outbox 的后台任务。"""
from app.database import SessionLocal
from app.services.case_pipeline_service import CasePipelineService
from app.tasks.celery_app import celery_app


@celery_app.task(name="aicommander.case_pipeline.process_pending")
def process_case_pipeline_events(limit: int = 50) -> dict:
    db = SessionLocal()
    try:
        return CasePipelineService.process_pending(db, limit=limit)
    finally:
        db.close()
