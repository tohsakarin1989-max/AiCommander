from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.services.preprocess_service import CasePreprocessService


@celery_app.task
def preprocess_case_task(case_id: int) -> dict:
    """
    异步执行案件预处理任务：
    旧 Celery 名称兼容入口；唯一持久任务是案件 Outbox，不写旧 features/jobs。
    """
    db = SessionLocal()
    try:
        # Old queued messages have no captured user authority; rules only.
        result = CasePreprocessService.preprocess_case(db, case_id=case_id, use_llm=False)
        return result or {}
    except Exception as e:
        db.rollback()
        return {"error": "case_profile_failed", "source": "case_revision_outbox_profile"}
    finally:
        db.close()

