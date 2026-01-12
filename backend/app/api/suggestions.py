from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()

@router.get("/")
def get_suggestions(db: Session = Depends(get_db)):
    """获取巡逻建议（从报告中提取）"""
    # 这里可以从报告或分析结果中提取建议
    # 暂时返回空列表
    return {"suggestions": []}

