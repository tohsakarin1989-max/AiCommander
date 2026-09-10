"""Dedicated agent queue consumer; questions/results never enter broker messages."""
import asyncio

from app.config import settings
from app.database import SessionLocal
from app.services.intelligent_query_worker import process_next
from app.tasks.celery_app import celery_app


@celery_app.task(name='aicommander.queries.process_next', queue=settings.AGENT_REDIS_QUEUE,
                 soft_time_limit=125, time_limit=135, ignore_result=True)
def process_query():
    with SessionLocal() as db:
        return asyncio.run(process_next(db))
