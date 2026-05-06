from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.services.ai_model_service import AIModelService
from app.models.ai_model import AIModel

router = APIRouter()

class ModelCreate(BaseModel):
    name: str
    provider: str  # openai, anthropic
    model_name: str
    api_key: str
    role: str  # moderator, analyst
    config: dict = {}
    description: Optional[str] = None

class ModelUpdate(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    config: Optional[dict] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ModelResponse(BaseModel):
    id: int
    name: str
    provider: str
    model_name: str
    role: str
    is_active: bool
    is_default: bool
    config: dict
    description: Optional[str] = None
    
    class Config:
        from_attributes = True

@router.post("/", response_model=ModelResponse)
def create_model(model: ModelCreate, db: Session = Depends(get_db)):
    """创建AI模型配置"""
    ai_model = AIModelService.create_model(
        db=db,
        name=model.name,
        provider=model.provider,
        model_name=model.model_name,
        api_key=model.api_key,
        role=model.role,
        config=model.config,
        description=model.description
    )
    return ai_model

@router.get("/", response_model=List[ModelResponse])
def get_models(role: Optional[str] = None, db: Session = Depends(get_db)):
    """获取模型列表"""
    models = AIModelService.get_models(db, role=role)
    return models

@router.get("/{model_id:int}", response_model=ModelResponse)
def get_model(model_id: int, db: Session = Depends(get_db)):
    """获取单个模型"""
    model = AIModelService.get_model(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model

@router.put("/{model_id:int}", response_model=ModelResponse)
def update_model(
    model_id: int,
    model_update: ModelUpdate,
    db: Session = Depends(get_db)
):
    """更新模型配置"""
    update_data = model_update.dict(exclude_unset=True)
    model = AIModelService.update_model(db, model_id, **update_data)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model

@router.delete("/{model_id:int}")
def delete_model(model_id: int, db: Session = Depends(get_db)):
    """删除模型"""
    success = AIModelService.delete_model(db, model_id)
    if not success:
        raise HTTPException(status_code=404, detail="模型不存在")
    return {"message": "删除成功"}

@router.post("/{model_id:int}/set-default")
def set_default_moderator(model_id: int, db: Session = Depends(get_db)):
    """设置默认主持人模型"""
    success = AIModelService.set_default_moderator(db, model_id)
    if not success:
        raise HTTPException(status_code=400, detail="设置失败")
    return {"message": "设置成功"}

@router.post("/{model_id:int}/test")
def test_model(model_id: int, db: Session = Depends(get_db)):
    """测试模型连接"""
    model = AIModelService.get_model(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    result = AIModelService.test_model_connection(model)
    return result
