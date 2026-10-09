"""Source ledgers use the dedicated map queue, never request lifetimes."""
from app.database import SessionLocal
from app.services.map_ingest_jobs import process_next
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.map_ledgers.process_next', queue='map_build',
                 soft_time_limit=1800, time_limit=1860, ignore_result=True)
def process_map_ledger():
    with SessionLocal() as db:
        return process_next(db)
