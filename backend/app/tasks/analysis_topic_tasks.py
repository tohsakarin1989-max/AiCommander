"""Periodic deterministic topics; no original case data is placed in Redis."""
from app.database import SessionLocal
from app.services.analysis_topic_service import process_next_topic
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.topics.process_next',
                 soft_time_limit=125, time_limit=135, ignore_result=True)
def process_topic():
    with SessionLocal() as db:
        return process_next_topic(db)
