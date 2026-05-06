"""
会议模板 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.meeting_template import MeetingTemplate

router = APIRouter()


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    moderator_model_id: int
    analyst_model_ids: List[int]
    config: Optional[dict] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    moderator_model_id: Optional[int] = None
    analyst_model_ids: Optional[List[int]] = None
    config: Optional[dict] = None


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    moderator_model_id: int
    analyst_model_ids: List[int]
    config: Optional[dict]
    is_system: bool
    use_count: int
    created_at: str

    class Config:
        from_attributes = True


@router.get("/")
def list_templates(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[dict]:
    """获取所有会议模板"""
    templates = (
        db.query(MeetingTemplate)
        .order_by(MeetingTemplate.use_count.desc(), MeetingTemplate.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "moderator_model_id": t.moderator_model_id,
            "analyst_model_ids": t.analyst_model_ids or [],
            "config": t.config or {},
            "is_system": t.is_system,
            "use_count": t.use_count,
            "created_at": str(t.created_at) if t.created_at else None,
        }
        for t in templates
    ]


@router.post("/")
def create_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
) -> dict:
    """创建会议模板"""
    # 检查名称是否重复
    existing = db.query(MeetingTemplate).filter(MeetingTemplate.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="模板名称已存在")

    template = MeetingTemplate(
        name=data.name,
        description=data.description,
        moderator_model_id=data.moderator_model_id,
        analyst_model_ids=data.analyst_model_ids,
        config=data.config or {},
        is_system=False,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return {
        "id": template.id,
        "name": template.name,
        "message": "模板创建成功",
    }


@router.get("/{template_id:int}")
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """获取模板详情"""
    template = db.query(MeetingTemplate).filter(MeetingTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "moderator_model_id": template.moderator_model_id,
        "analyst_model_ids": template.analyst_model_ids or [],
        "config": template.config or {},
        "is_system": template.is_system,
        "use_count": template.use_count,
        "created_at": str(template.created_at) if template.created_at else None,
    }


@router.put("/{template_id:int}")
def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: Session = Depends(get_db),
) -> dict:
    """更新模板"""
    template = db.query(MeetingTemplate).filter(MeetingTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if template.is_system:
        raise HTTPException(status_code=403, detail="系统模板不可修改")

    if data.name is not None:
        # 检查名称是否重复
        existing = (
            db.query(MeetingTemplate)
            .filter(MeetingTemplate.name == data.name, MeetingTemplate.id != template_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="模板名称已存在")
        template.name = data.name

    if data.description is not None:
        template.description = data.description
    if data.moderator_model_id is not None:
        template.moderator_model_id = data.moderator_model_id
    if data.analyst_model_ids is not None:
        template.analyst_model_ids = data.analyst_model_ids
    if data.config is not None:
        template.config = data.config

    db.commit()
    db.refresh(template)

    return {
        "id": template.id,
        "name": template.name,
        "message": "模板更新成功",
    }


@router.delete("/{template_id:int}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """删除模板"""
    template = db.query(MeetingTemplate).filter(MeetingTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if template.is_system:
        raise HTTPException(status_code=403, detail="系统模板不可删除")

    db.delete(template)
    db.commit()

    return {"message": "模板删除成功"}


@router.post("/{template_id:int}/use")
def use_template(
    template_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """使用模板（增加使用计数，返回模板配置）"""
    template = db.query(MeetingTemplate).filter(MeetingTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    template.use_count = (template.use_count or 0) + 1
    db.commit()

    return {
        "moderator_model_id": template.moderator_model_id,
        "analyst_model_ids": template.analyst_model_ids or [],
        "config": template.config or {},
    }
