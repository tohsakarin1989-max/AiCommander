"""
语义嵌入服务 - 用于生成案件描述的向量表示
支持多种embedding模型：OpenAI、本地sentence-transformers等
"""
from typing import List, Optional, Dict
import os
from app.utils.logger import logger
from app.ai.llm_providers import LLMProvider


class EmbeddingService:
    """语义嵌入服务"""
    
    def __init__(self):
        self.provider = None
        self.model_name = None
        self._init_provider()
    
    def _init_provider(self):
        """初始化embedding提供者"""
        # 优先使用OpenAI（如果配置了）
        # 否则使用本地sentence-transformers模型
        try:
            # 尝试使用OpenAI embedding
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.provider = "openai"
                self.model_name = "text-embedding-3-small"  # 或 text-embedding-ada-002
                logger.info("使用OpenAI embedding模型")
                return
        except Exception as e:
            logger.warning(f"无法使用OpenAI embedding: {e}")
        
        # 使用本地模型
        try:
            from sentence_transformers import SentenceTransformer
            self.provider = "local"
            # 使用中文优化的模型
            self.model_name = "paraphrase-multilingual-MiniLM-L12-v2"  # 支持中文
            self._local_model = SentenceTransformer(self.model_name)
            logger.info(f"使用本地embedding模型: {self.model_name}")
        except Exception as e:
            logger.error(f"无法加载本地embedding模型: {e}")
            self.provider = None
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        生成单个文本的embedding向量
        
        Args:
            text: 输入文本
            
        Returns:
            embedding向量（384维或1536维，取决于模型）
        """
        if not text or not text.strip():
            return None
        
        try:
            if self.provider == "openai":
                import openai
                response = openai.embeddings.create(
                    model=self.model_name,
                    input=text
                )
                return response.data[0].embedding
            elif self.provider == "local":
                embedding = self._local_model.encode(text, convert_to_numpy=False)
                return embedding.tolist()
            else:
                logger.error("未配置embedding提供者")
                return None
        except Exception as e:
            logger.error(f"生成embedding失败: {e}")
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
            if self.provider == "openai":
                import openai
                # OpenAI支持批量
                response = openai.embeddings.create(
                    model=self.model_name,
                    input=texts
                )
                return [item.embedding for item in response.data]
            elif self.provider == "local":
                # sentence-transformers也支持批量
                embeddings = self._local_model.encode(
                    texts,
                    convert_to_numpy=False,
                    show_progress_bar=False
                )
                return [emb.tolist() for emb in embeddings]
            else:
                return [None] * len(texts)
        except Exception as e:
            logger.error(f"批量生成embedding失败: {e}")
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

