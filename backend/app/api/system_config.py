from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.services.system_config_service import SystemConfigService
from app.models.system_config import SystemConfig

router = APIRouter()

class ConfigCreate(BaseModel):
    config_key: str
    config_value: str
    config_type: str = "api_key"
    category: str = "general"
    description: Optional[str] = None
    extra_data: Optional[dict] = None

class ConfigUpdate(BaseModel):
    config_value: Optional[str] = None
    config_type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    extra_data: Optional[dict] = None

class ConfigResponse(BaseModel):
    id: int
    config_key: str
    config_value: str
    config_type: str
    category: str
    description: Optional[str] = None
    extra_data: Optional[dict] = None
    created_at: str
    updated_at: Optional[str] = None
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_orm(cls, obj: SystemConfig):
        """自定义序列化，处理datetime对象"""
        return cls(
            id=obj.id,
            config_key=obj.config_key,
            config_value=obj.config_value,
            config_type=obj.config_type,
            category=obj.category,
            description=obj.description,
            extra_data=obj.extra_data or {},
            created_at=obj.created_at.isoformat() if obj.created_at else "",
            updated_at=obj.updated_at.isoformat() if obj.updated_at else None
        )

@router.get("/", response_model=List[ConfigResponse])
def get_configs(
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取系统配置列表"""
    if category:
        configs = SystemConfigService.get_configs_by_category(db, category)
    else:
        configs = SystemConfigService.get_all_configs(db)
    return [ConfigResponse.from_orm(config) for config in configs]

@router.get("/{config_key}", response_model=ConfigResponse)
def get_config(config_key: str, db: Session = Depends(get_db)):
    """获取单个配置"""
    config = SystemConfigService.get_config(db, config_key)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    return ConfigResponse.from_orm(config)

@router.post("/", response_model=ConfigResponse)
def create_config(config: ConfigCreate, db: Session = Depends(get_db)):
    """创建配置"""
    existing = SystemConfigService.get_config(db, config.config_key)
    if existing:
        raise HTTPException(status_code=400, detail="配置已存在")
    
    new_config = SystemConfigService.set_config(
        db,
        config_key=config.config_key,
        config_value=config.config_value,
        config_type=config.config_type,
        category=config.category,
        description=config.description,
        extra_data=config.extra_data
    )
    return ConfigResponse.from_orm(new_config)

@router.put("/{config_key}", response_model=ConfigResponse)
def update_config(
    config_key: str,
    config_update: ConfigUpdate,
    db: Session = Depends(get_db)
):
    """更新配置（如果不存在则创建）"""
    config = SystemConfigService.get_config(db, config_key)
    if not config:
        # 如果配置不存在，尝试从默认配置中获取信息，否则创建新配置
        default_configs = {
            "map_api_provider": {"config_type": "string", "category": "map", "description": "地图服务提供商"},
            "map_api_key": {"config_type": "api_key", "category": "map", "description": "地图API密钥"},
            "map_api_base_url": {"config_type": "url", "category": "map", "description": "地图API服务地址"},
            "meeting_api_provider": {"config_type": "string", "category": "meeting", "description": "圆桌会议API提供商"},
            "meeting_api_key": {"config_type": "api_key", "category": "meeting", "description": "圆桌会议API密钥"},
            "meeting_api_base_url": {"config_type": "url", "category": "meeting", "description": "圆桌会议API服务地址"},
        }
        
        default_info = default_configs.get(config_key, {
            "config_type": "string",
            "category": "general",
            "description": None
        })
        
        config = SystemConfigService.set_config(
            db,
            config_key=config_key,
            config_value=config_update.config_value or "",
            config_type=config_update.config_type or default_info["config_type"],
            category=config_update.category or default_info["category"],
            description=config_update.description or default_info.get("description"),
            extra_data=config_update.extra_data or {}
        )
        return ConfigResponse.from_orm(config)
    
    if config_update.config_value is not None:
        config.config_value = config_update.config_value
    if config_update.config_type is not None:
        config.config_type = config_update.config_type
    if config_update.category is not None:
        config.category = config_update.category
    if config_update.description is not None:
        config.description = config_update.description
    if config_update.extra_data is not None:
        config.extra_data = config_update.extra_data
    
    db.commit()
    db.refresh(config)
    return ConfigResponse.from_orm(config)

@router.delete("/{config_key}")
def delete_config(config_key: str, db: Session = Depends(get_db)):
    """删除配置"""
    success = SystemConfigService.delete_config(db, config_key)
    if not success:
        raise HTTPException(status_code=404, detail="配置不存在")
    return {"message": "删除成功"}

@router.post("/init-defaults")
def init_default_configs(db: Session = Depends(get_db)):
    """初始化默认配置"""
    SystemConfigService.init_default_configs(db)
    return {"message": "默认配置初始化成功"}

@router.get("/map/config")
def get_map_config(db: Session = Depends(get_db)):
    """获取地图配置（供前端使用）"""
    provider = SystemConfigService.get_config_value(db, "map_api_provider", "openstreetmap")
    api_key = SystemConfigService.get_config_value(db, "map_api_key", "")
    api_base_url = SystemConfigService.get_config_value(db, "map_api_base_url", "")
    
    return {
        "provider": provider,
        "api_key": api_key,
        "api_base_url": api_base_url
    }

@router.get("/meeting/config")
def get_meeting_config(db: Session = Depends(get_db)):
    """获取圆桌会议配置（供前端使用）"""
    provider = SystemConfigService.get_config_value(db, "meeting_api_provider", "direct")
    api_key = SystemConfigService.get_config_value(db, "meeting_api_key", "")
    api_base_url = SystemConfigService.get_config_value(db, "meeting_api_base_url", "https://openrouter.ai/api/v1")
    
    return {
        "provider": provider,
        "api_key": api_key,
        "api_base_url": api_base_url
    }

