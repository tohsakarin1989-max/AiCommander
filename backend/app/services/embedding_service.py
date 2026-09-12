"""
兼容旧调用的内网嵌入入口；只加载已校验的本地模型包。
"""
from typing import List, Optional, Dict
from app.utils.logger import logger


class EmbeddingService:
    """语义嵌入服务"""
    
    def __init__(self):
        self.provider = None
        self.model_name = None
        self._init_provider()
    
    def _init_provider(self):
        """初始化embedding提供者"""
        from app.services.local_embedding_service import get_local_embedder
        self._local_model = get_local_embedder()
        self.provider = "local" if self._local_model.state == "ready" else None
        self.model_name = self._local_model.model_version
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        生成单个文本的embedding向量
        
        Args:
            text: 输入文本
            
        Returns:
            维度与已校验模型清单一致的向量，未配置或失败时为 None
        """
        if not text or not text.strip():
            return None
        
        try:
            if self.provider == "local":
                return self._local_model.encode(text)
            else:
                logger.error("未配置embedding提供者")
                return None
        except Exception:
            logger.warning("本地嵌入暂不可用，保留词项检索")
            return None
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        批量生成embedding向量
        
        Args:
            texts: 文本列表
            
        Returns:
            embedding向量列表
        """
        if not texts:
            return []
        
        try:
            if self.provider == "local":
                return [self.generate_embedding(text) for text in texts]
            else:
                return [None] * len(texts)
        except Exception:
            logger.warning("本地批量嵌入暂不可用，保留词项检索")
            return [None] * len(texts)
    
    def build_case_text(self, case: Dict) -> str:
        """
        构建案件的完整文本描述，用于生成embedding
        
        Args:
            case: 案件字典，包含description、modus_operandi等字段
            
        Returns:
            组合后的文本
        """
        parts = []
        
        if case.get("description"):
            parts.append(f"案件描述：{case['description']}")
        
        if case.get("modus_operandi"):
            parts.append(f"作案手法：{case['modus_operandi']}")
        
        if case.get("case_type"):
            parts.append(f"案件类型：{case['case_type']}")
        
        if case.get("facility_type"):
            parts.append(f"目标设施：{case['facility_type']}")
        
        if case.get("oil_type"):
            parts.append(f"涉及油品：{case['oil_type']}")
        
        if case.get("vehicle_info"):
            vehicle = case["vehicle_info"]
            if isinstance(vehicle, dict):
                vehicle_str = ", ".join(f"{k}:{v}" for k, v in vehicle.items() if v)
                if vehicle_str:
                    parts.append(f"车辆信息：{vehicle_str}")
        
        if case.get("location"):
            parts.append(f"案发地点：{case['location']}")
        
        return "\n".join(parts) if parts else ""
