from sqlalchemy.orm import Session
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.utils.encryption import encrypt_api_key, decrypt_api_key
from typing import List, Optional
from app.utils.logger import logger

class AIModelService:
    
    @staticmethod
    def create_model(
        db: Session,
        name: str,
        provider: str,
        model_name: str,
        api_key: str,
        role: str,
        config: dict = None,
        description: str = None
    ) -> AIModel:
        """创建AI模型配置"""
        encrypted_key = encrypt_api_key(api_key)
        
        model = AIModel(
            name=name,
            provider=provider,
            model_name=model_name,
            api_key=encrypted_key,
            role=role,
            config=config or {},
            description=description
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        logger.info(f"创建AI模型: {name}")
        return model
    
    @staticmethod
    def get_models(db: Session, role: Optional[str] = None) -> List[AIModel]:
        """获取模型列表"""
        query = db.query(AIModel).filter(AIModel.is_active == True)
        if role:
            query = query.filter(AIModel.role == role)
        return query.all()
    
    @staticmethod
    def get_model(db: Session, model_id: int) -> Optional[AIModel]:
        """获取单个模型"""
        return db.query(AIModel).filter(AIModel.id == model_id).first()
    
    @staticmethod
    def update_model(
        db: Session,
        model_id: int,
        **kwargs
    ) -> Optional[AIModel]:
        """更新模型配置"""
        model = db.query(AIModel).filter(AIModel.id == model_id).first()
        if not model:
            return None
        
        for key, value in kwargs.items():
            if key == "api_key" and value:
                value = encrypt_api_key(value)
            if value is not None:
                setattr(model, key, value)
        
        db.commit()
        db.refresh(model)
        logger.info(f"更新AI模型: {model.name}")
        return model
    
    @staticmethod
    def delete_model(db: Session, model_id: int) -> bool:
        """删除模型（软删除）"""
        model = db.query(AIModel).filter(AIModel.id == model_id).first()
        if not model:
            return False
        model.is_active = False
        db.commit()
        logger.info(f"删除AI模型: {model.name}")
        return True
    
    @staticmethod
    def set_default_moderator(db: Session, model_id: int) -> bool:
        """设置默认主持人模型"""
        # 取消其他默认设置
        db.query(AIModel).filter(
            AIModel.role == "moderator"
        ).update({"is_default": False})
        
        # 设置新的默认
        model = db.query(AIModel).filter(AIModel.id == model_id).first()
        if model and model.role == "moderator":
            model.is_default = True
            db.commit()
            logger.info(f"设置默认主持人模型: {model.name}")
            return True
        return False
    
    @staticmethod
    def test_model_connection(model: AIModel) -> dict:
        """测试模型连接"""
        try:
            factory = ModelFactory()
            llm = factory.create_llm(model)
            # 发送测试请求
            response = llm.invoke("测试连接，请回复'连接成功'")
            return {"success": True, "message": "连接成功", "response": response.content[:100]}
        except Exception as e:
            logger.error(f"模型连接测试失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    @staticmethod
    def get_decrypted_api_key(model: AIModel) -> str:
        """获取解密后的API密钥"""
        return decrypt_api_key(model.api_key)

