"""Ordinary deterministic catalog maintenance; independent of models and Agent Lab."""
from app.database import SessionLocal
from app.services.facility_summary_service import reconcile_catalog
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.facilities.reconcile', soft_time_limit=50, time_limit=60, ignore_result=True)
def reconcile_facilities():
    with SessionLocal() as db:
        return reconcile_catalog(db)
