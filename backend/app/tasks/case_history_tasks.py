"""检索派生索引独立更新，不加入案件保存或页面读取事务。"""
from app.database import SessionLocal
from app.services.case_history_index_service import CaseHistoryIndexService
from app.tasks.celery_app import celery_app


@celery_app.task(name="aicommander.case_history.reconcile")
def reconcile_case_history(limit: int = 100) -> dict:
    db = SessionLocal()
    try:
        result = CaseHistoryIndexService.reconcile_batch(db, limit=limit)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
