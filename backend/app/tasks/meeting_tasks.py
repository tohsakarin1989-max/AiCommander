from app.tasks.celery_app import celery_app
from app.services.meeting_service import MeetingService
from app.database import SessionLocal
from app.models.meeting import Meeting
import asyncio
from app.utils.logger import logger

@celery_app.task
def run_meeting_task(
    meeting_id: str,
    case_ids: list,
    moderator_model_id: int,
    analyst_model_ids: list
):
    """异步执行会议任务"""
    db = SessionLocal()
    try:
        # 运行异步函数，传入已存在的会议ID
        result = asyncio.run(
            MeetingService.create_and_run_meeting(
                db=db,
                case_ids=case_ids,
                moderator_model_id=moderator_model_id,
                analyst_model_ids=analyst_model_ids,
                existing_meeting_id=meeting_id  # 传入已存在的会议ID
            )
        )
        
        return result
    except Exception:
        logger.exception("执行会议任务失败: %s", meeting_id)
        # 更新会议状态为失败
        try:
            db.rollback()
            meeting = db.query(Meeting).filter(
                Meeting.meeting_id == meeting_id
            ).first()
            if meeting:
                meeting.status = "failed"
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("会议 %s 失败状态写入失败", meeting_id)
        raise
    finally:
        db.close()
