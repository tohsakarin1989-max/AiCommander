"""Remove expired private snapshots without starting any analysis workflow."""
from app.database import SessionLocal
from app.services.case_draft_service import purge_expired_case_drafts
from app.tasks.celery_app import celery_app


@celery_app.task(name="aicommander.case_drafts.expire", ignore_result=True)
def expire_case_drafts():
    with SessionLocal() as db:
        return purge_expired_case_drafts(db)
