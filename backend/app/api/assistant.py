from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
from app.database import get_db
from app.services.assistant_service import AssistantService
from app.services.case_knowledge_service import CaseKnowledgeService

router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    query: str
    conversation_history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[dict] = []
    context_used: Optional[dict] = None
    error: Optional[str] = None


class EvidenceQaRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    case_id: Optional[int] = Field(None, gt=0)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """智能助手聊天接口"""
    try:
        # 转换对话历史格式
        history = None
        if request.conversation_history:
            history = [
                {
                    "role": msg.role,
                    "content": msg.content
                }
                for msg in request.conversation_history
            ]
        
        result = await AssistantService.chat(
            db=db,
            user_query=request.query,
            conversation_history=history
        )
        
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理请求失败: {str(e)}")


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """获取系统统计信息（供智能助手使用）"""
    from app.models.case import Case
    from app.models.meeting import Meeting
    
    try:
        total_cases = db.query(Case).count()
        completed_meetings = db.query(Meeting).filter(Meeting.status == "completed").count()
        pending_meetings = db.query(Meeting).filter(Meeting.status.in_(["processing", "first_opinions", "reviewing", "finalizing"])).count()
        
        return {
            "total_cases": total_cases,
            "completed_meetings": completed_meetings,
            "pending_meetings": pending_meetings,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.post("/evidence-qa")
def evidence_qa(request: EvidenceQaRequest, db: Session = Depends(get_db)):
    """证据型研判问答：回答必须带引用，资料不足时明确返回不足。"""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        return CaseKnowledgeService.evidence_qa(db, request.query, case_id=request.case_id)
    except PermissionError:
        raise HTTPException(404, '检索范围不可访问') from None
    except ValueError:
        raise HTTPException(422, '请提供有效查询条件') from None
    except SQLAlchemyError:
        raise HTTPException(503, '检索暂不可用，不能据此判断没有相关资料') from None
