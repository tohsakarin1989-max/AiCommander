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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            MeetingService.create_and_run_meeting(
                db=db,
                case_ids=case_ids,
                moderator_model_id=moderator_model_id,
                analyst_model_ids=analyst_model_ids,
                existing_meeting_id=meeting_id  # 传入已存在的会议ID
            )
        )
        
        return result
    except Exception as e:
        logger.error(f"执行会议任务失败: {str(e)}")
        # 更新会议状态为失败
        try:
            meeting = db.query(Meeting).filter(
                Meeting.meeting_id == meeting_id
            ).first()
            if meeting:
                meeting.status = "failed"
                db.commit()
        except:
            pass
        raise
    finally:
        db.close()

