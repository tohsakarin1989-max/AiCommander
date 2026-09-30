from app.database import SessionLocal
from app.tasks.celery_app import celery_app


@celery_app.task
def scan_chain_links_task(case_id: int) -> dict:
    # Keep queued legacy messages executable, without running an unscoped scan.
    return {"case_id": case_id, "status": "legacy_request_requires_authorized_outbox"}


@celery_app.task(name="aicommander.chain.process_pending")
def process_chain_events(limit: int = 50) -> dict:
    from app.services.chain_outbox_service import process_pending
    db = SessionLocal()
    try:
        return process_pending(db, limit=limit)
    finally:
        db.close()
