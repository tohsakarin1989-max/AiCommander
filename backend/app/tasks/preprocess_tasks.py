from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.services.preprocess_service import CasePreprocessService
from app.models.preprocess_job import PreprocessJob
from datetime import datetime


@celery_app.task
def preprocess_case_task(case_id: int) -> dict:
    """
    异步执行案件预处理任务：
    - 从原始案情中抽取结构化特征并写入 Case.features
    - 记录任务状态到 PreprocessJob 表
    """
    db = SessionLocal()
    job = None
    try:
        # 创建任务记录
        job = PreprocessJob(case_id=case_id, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)

        # 标记为 processing
        job.status = "processing"
        job.started_at = datetime.utcnow()
        db.commit()

        result = CasePreprocessService.preprocess_case(db, case_id=case_id)

        job.status = "success"
        job.finished_at = datetime.utcnow()
        db.commit()

        return result or {}
    except Exception as e:
        if job is not None:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error = str(e)
            db.commit()
        return {"error": str(e)}
    finally:
        db.close()


