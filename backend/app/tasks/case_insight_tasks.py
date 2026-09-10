"""自动消费双域融合研判事件。"""
from app.database import SessionLocal
from app.services.case_insight_service import CaseInsightService
from app.tasks.celery_app import celery_app


@celery_app.task(name="aicommander.case_insights.process_pending")
def process_case_insight_events(limit: int = 30) -> dict:
    db = SessionLocal()
    try:
        return CaseInsightService.process_pending(db, limit=limit)
    finally:
        db.close()


@celery_app.task(name="aicommander.case_insights.reconcile_current_pairs")
def reconcile_current_case_insights(limit: int = 500) -> dict:
    db = SessionLocal()
    try:
        return CaseInsightService.reconcile_current_pairs(db, limit=limit)
    finally:
        db.close()
