from sqlalchemy.orm import Session
from app.models.system_config import SystemConfig
from typing import Optional, Dict, List

class SystemConfigService:
    """系统配置服务"""
    
    @staticmethod
    def get_config(db: Session, config_key: str) -> Optional[SystemConfig]:
        """获取单个配置"""
        return db.query(SystemConfig).filter(
            SystemConfig.config_key == config_key
        ).first()
    
    @staticmethod
    def get_config_value(db: Session, config_key: str, default: str = None) -> Optional[str]:
        """获取配置值"""
        config = SystemConfigService.get_config(db, config_key)
        return config.config_value if config else default
    
    @staticmethod
    def set_config(
        db: Session,
        config_key: str,
        config_value: str,
        config_type: str = "api_key",
        category: str = "general",
        description: str = None,
        extra_data: Dict = None
    ) -> SystemConfig:
        """设置配置"""
        config = SystemConfigService.get_config(db, config_key)
        if config:
            config.config_value = config_value
            config.config_type = config_type
            config.category = category
            if description:
                config.description = description
            if extra_data:
                config.extra_data = extra_data
        else:
            config = SystemConfig(
                config_key=config_key,
                config_value=config_value,
                config_type=config_type,
                category=category,
                description=description,
                extra_data=extra_data or {}
            )
            db.add(config)
        
        db.commit()
        db.refresh(config)
        return config
    
    @staticmethod
    def get_configs_by_category(db: Session, category: str) -> List[SystemConfig]:
        """按分类获取配置"""
        return db.query(SystemConfig).filter(
            SystemConfig.category == category
        ).all()
    
    @staticmethod
    def get_all_configs(db: Session) -> List[SystemConfig]:
        """获取所有配置"""
        return db.query(SystemConfig).all()
    
    @staticmethod
    def delete_config(db: Session, config_key: str) -> bool:
        """删除配置"""
        config = SystemConfigService.get_config(db, config_key)
        if config:
            db.delete(config)
            db.commit()
            return True
        return False
    
    @staticmethod
    def init_default_configs(db: Session):
        """初始化默认配置项（如果不存在）"""
        default_configs = [
            {
                "config_key": "map_api_provider",
                "config_value": "openstreetmap",
                "config_type": "string",
                "category": "map",
                "description": "地图服务提供商：openstreetmap（免费，无需API key）、mapbox（需要API key）、amap（高德地图，需要API key）、baidu（百度地图，需要API key）",
                "extra_data": {
                    "options": ["openstreetmap", "mapbox", "amap", "baidu"]
                }
            },
            {
                "config_key": "map_api_key",
                "config_value": "",
                "config_type": "api_key",
                "category": "map",
                "description": "地图API密钥（Mapbox/高德/百度地图需要，OpenStreetMap不需要）。用于地图展示和地理定位功能。",
                "extra_data": {}
            },
            {
                "config_key": "map_api_base_url",
                "config_value": "",
                "config_type": "url",
                "category": "map",
                "description": "地图API服务地址（可选，某些自建地图服务需要）",
                "extra_data": {}
            },
            {
                "config_key": "meeting_api_provider",
                "config_value": "openrouter",
                "config_type": "string",
                "category": "meeting",
                "description": "圆桌会议API提供商：openrouter（统一接口，支持多个LLM）、direct（直接使用配置的AI模型，无需额外API）。OpenRouter用于通过统一接口访问多个LLM模型。",
                "extra_data": {
                    "options": ["openrouter", "direct"]
                }
            },
            {
                "config_key": "meeting_api_key",
                "config_value": "",
                "config_type": "api_key",
                "category": "meeting",
                "description": "圆桌会议API密钥（OpenRouter需要，direct模式不需要）。OpenRouter是一个统一的LLM API网关，可以访问GPT、Claude、Gemini等多个模型。",
                "extra_data": {}
            },
            {
                "config_key": "meeting_api_base_url",
                "config_value": "https://openrouter.ai/api/v1",
                "config_type": "url",
                "category": "meeting",
                "description": "圆桌会议API服务地址（OpenRouter默认：https://openrouter.ai/api/v1）",
                "extra_data": {}
            },
        ]
        
        for config_data in default_configs:
            existing = SystemConfigService.get_config(db, config_data["config_key"])
            if not existing:
                SystemConfigService.set_config(
                    db,
                    **config_data
                )

