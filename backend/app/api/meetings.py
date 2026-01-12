from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.services.meeting_service import MeetingService
from app.models.meeting import Meeting, MeetingConversation, AnalysisResult, Ranking
from app.models.report import Report

router = APIRouter()

class MeetingCreate(BaseModel):
    case_ids: List[int]
    moderator_model_id: int
    analyst_model_ids: List[int]

class MeetingResponse(BaseModel):
    id: int
    meeting_id: str
    case_ids: List[int]
    status: str
    moderator_model_id: int
    analyst_model_ids: List[int]
    final_report_id: Optional[int] = None
    created_at: str
    completed_at: Optional[str] = None
    
    class Config:
        from_attributes = True

class ConversationResponse(BaseModel):
    id: int
    round_number: int
    speaker_model_id: int
    message_type: str
    content: str
    created_at: str
    
    class Config:
        from_attributes = True

@router.post("/")
async def create_meeting(
    meeting: MeetingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """创建并启动会议（异步执行）"""
    try:
        # 先创建会议记录，状态为 "processing"
        from app.ai.meeting_manager import MeetingManager
        from app.models.meeting import Meeting
        import uuid
        from datetime import datetime
        
        manager = MeetingManager(db)
        meeting_id = f"MEET-{uuid.uuid4().hex[:8].upper()}"
        
        # 创建会议记录
        meeting_record = Meeting(
            meeting_id=meeting_id,
            case_ids=meeting.case_ids,
            status="processing",  # 初始状态为处理中
            moderator_model_id=meeting.moderator_model_id,
            analyst_model_ids=meeting.analyst_model_ids
        )
        db.add(meeting_record)
        db.commit()
        db.refresh(meeting_record)
        
        # 使用 Celery 异步任务执行会议
        try:
            from app.tasks.meeting_tasks import run_meeting_task
            task = run_meeting_task.delay(
                meeting_id=meeting_id,  # 传递会议ID
                case_ids=meeting.case_ids,
                moderator_model_id=meeting.moderator_model_id,
                analyst_model_ids=meeting.analyst_model_ids
            )
        except Exception as celery_error:
            # 如果 Celery 不可用，使用 BackgroundTasks 作为备选方案
            from app.utils.logger import logger
            logger.warning(f"Celery 不可用，使用 BackgroundTasks: {str(celery_error)}")
            background_tasks.add_task(
                _run_meeting_sync,
                meeting_id=meeting_id,
                case_ids=meeting.case_ids,
                moderator_model_id=meeting.moderator_model_id,
                analyst_model_ids=meeting.analyst_model_ids
            )
        
        # 立即返回会议ID和状态
        return {
            "meeting_id": meeting_id,
            "status": "processing",
            "message": "会议已创建，正在后台处理中，请稍后查看结果"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_meeting_sync(
    meeting_id: str,
    case_ids: List[int],
    moderator_model_id: int,
    analyst_model_ids: List[int]
):
    """同步执行会议（作为 Celery 的备选方案）"""
    try:
        # 需要重新获取数据库会话
        from app.database import SessionLocal
        new_db = SessionLocal()
        try:
            # 调用服务创建并运行会议（传入 meeting_id）
            result = await MeetingService.create_and_run_meeting(
                db=new_db,
                case_ids=case_ids,
                moderator_model_id=moderator_model_id,
                analyst_model_ids=analyst_model_ids,
                existing_meeting_id=meeting_id  # 传入已存在的会议ID
            )
        finally:
            new_db.close()
    except Exception as e:
        from app.utils.logger import logger
        logger.error(f"执行会议 {meeting_id} 失败: {str(e)}")
        # 更新会议状态为失败
        try:
            from app.database import SessionLocal
            error_db = SessionLocal()
            try:
                from app.models.meeting import Meeting
                meeting_record = error_db.query(Meeting).filter(
                    Meeting.meeting_id == meeting_id
                ).first()
                if meeting_record:
                    meeting_record.status = "failed"
                    error_db.commit()
            finally:
                error_db.close()
        except:
            pass

@router.get("/", response_model=List[MeetingResponse])
def get_meetings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取会议列表"""
    try:
        meetings = MeetingService.get_meetings(db, skip=skip, limit=limit)
        # 确保 JSON 字段正确序列化
        result = []
        for meeting in meetings:
            result.append({
                "id": meeting.id,
                "meeting_id": meeting.meeting_id,
                "case_ids": meeting.case_ids if meeting.case_ids else [],
                "status": meeting.status,
                "moderator_model_id": meeting.moderator_model_id,
                "analyst_model_ids": meeting.analyst_model_ids if meeting.analyst_model_ids else [],
                "final_report_id": meeting.final_report_id,
                "created_at": meeting.created_at.isoformat() if meeting.created_at else "",
                "completed_at": meeting.completed_at.isoformat() if meeting.completed_at else None,
            })
        return result
    except Exception as e:
        from app.utils.logger import logger
        logger.error(f"获取会议列表失败: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取会议列表失败: {str(e)}")

@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    """获取单个会议"""
    meeting = MeetingService.get_meeting(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")
    return meeting

@router.get("/{meeting_id}/conversations", response_model=List[ConversationResponse])
def get_meeting_conversations(meeting_id: str, db: Session = Depends(get_db)):
    """获取会议对话记录"""
    conversations = MeetingService.get_meeting_conversations(db, meeting_id)
    return conversations

@router.get("/{meeting_id}/report")
def get_meeting_report(meeting_id: str, db: Session = Depends(get_db)):
    """获取会议报告"""
    report = MeetingService.get_meeting_report(db, meeting_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report

@router.get("/{meeting_id}/analyses")
def get_meeting_analyses(meeting_id: str, db: Session = Depends(get_db)):
    """获取会议第一阶段的分析结果（所有LLM的独立回答）"""
    analyses = db.query(AnalysisResult).filter(
        AnalysisResult.meeting_id == meeting_id,
        AnalysisResult.round_number == 1  # 第一阶段
    ).order_by(AnalysisResult.created_at).all()
    
    return [
        {
            "id": a.id,
            "analyst_model_id": a.analyst_model_id,
            "result_content": a.result_content,
            "created_at": str(a.created_at)
        }
        for a in analyses
    ]

@router.get("/{meeting_id}/rankings")
def get_meeting_rankings(meeting_id: str, db: Session = Depends(get_db)):
    """获取会议第二阶段的排名结果"""
    rankings = db.query(Ranking).filter(
        Ranking.meeting_id == meeting_id
    ).order_by(Ranking.created_at).all()
    
    return [
        {
            "id": r.id,
            "evaluator_model_id": r.evaluator_model_id,
            "stage": r.stage,
            "ranking_data": r.ranking_data,
            "aggregated_data": r.aggregated_data,
            "created_at": str(r.created_at)
        }
        for r in rankings
    ]

