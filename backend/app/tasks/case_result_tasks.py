"""沿用常规后台队列分批补齐升级前的统一成果，不依赖模型或地图构建队列。"""
from app.database import SessionLocal
from app.services.case_result_backfill import enqueue_missing_results, process_result_backfill
from app.tasks.celery_app import celery_app


@celery_app.task(name="aicommander.case_results.reconcile")
def reconcile_case_results(limit: int = 50) -> dict:
    with SessionLocal() as db:
        enqueued = enqueue_missing_results(db, limit)
        return {**enqueued, **process_result_backfill(db, limit)}
