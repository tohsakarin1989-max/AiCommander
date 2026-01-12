"""
向量数据库服务 - 使用Chroma存储案件语义向量
"""
try:
    import chromadb
    from chromadb.config import Settings
except Exception:  # pragma: no cover - optional dependency
    chromadb = None
    Settings = None
from typing import List, Dict, Optional
import os
from app.utils.logger import logger
from app.services.embedding_service import EmbeddingService


class VectorDBService:
    """向量数据库服务"""
    
    def __init__(self):
        self.client = None
        self.collection = None
        self.embedding_service = EmbeddingService()
        self._init_client()
    
    def _init_client(self):
        """初始化Chroma客户端"""
        try:
            if chromadb is None or Settings is None:
                logger.warning("chromadb 未安装，向量数据库不可用")
                self.client = None
                self.collection = None
                return
            # 使用持久化存储
            persist_directory = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data",
                "chroma_db"
            )
            os.makedirs(persist_directory, exist_ok=True)
            
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            
            # 获取或创建collection
            self.collection = self.client.get_or_create_collection(
                name="cases",
                metadata={"description": "案件语义向量库"}
            )
            
            logger.info(f"向量数据库初始化成功，存储路径: {persist_directory}")
        except Exception as e:
            logger.error(f"向量数据库初始化失败: {e}")
            self.client = None
            self.collection = None
    
    def is_available(self) -> bool:
        """检查向量数据库是否可用"""
        return self.client is not None and self.collection is not None
    
    def add_case(self, case_id: int, case_data: Dict, embedding: Optional[List[float]] = None) -> bool:
        """
        添加案件到向量数据库
        
        Args:
            case_id: 案件ID
            case_data: 案件数据字典
            embedding: 可选的预生成embedding，如果为None则自动生成
            
        Returns:
            是否成功
        """
        if not self.is_available():
            logger.warning("向量数据库不可用，跳过添加")
            return False
        
        try:
            # 构建案件文本
            text = self.embedding_service.build_case_text(case_data)
            if not text:
                logger.warning(f"案件 {case_id} 无有效文本，跳过向量化")
                return False
            
            # 生成embedding
            if embedding is None:
                embedding = self.embedding_service.generate_embedding(text)
                if not embedding:
                    logger.error(f"无法为案件 {case_id} 生成embedding")
                    return False
            
            # 添加到collection
            self.collection.add(
                ids=[str(case_id)],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{
                    "case_id": case_id,
                    "case_number": case_data.get("case_number", ""),
                    "case_type": case_data.get("case_type", ""),
                    "modus_operandi": case_data.get("modus_operandi", ""),
                    "occurred_time": str(case_data.get("occurred_time", "")),
                }]
            )
            
            logger.info(f"案件 {case_id} 已添加到向量数据库")
            return True
        except Exception as e:
            logger.error(f"添加案件到向量数据库失败: {e}")
            return False
    
    def update_case(self, case_id: int, case_data: Dict) -> bool:
        """更新案件向量（先删除再添加）"""
        self.delete_case(case_id)
        return self.add_case(case_id, case_data)
    
    def delete_case(self, case_id: int) -> bool:
        """从向量数据库删除案件"""
        if not self.is_available():
            return False
        
        try:
            self.collection.delete(ids=[str(case_id)])
            logger.info(f"案件 {case_id} 已从向量数据库删除")
            return True
        except Exception as e:
            logger.error(f"从向量数据库删除案件失败: {e}")
            return False
    
    def search_similar_cases(
        self,
        query_text: str,
        top_k: int = 10,
        min_similarity: float = 0.5
    ) -> List[Dict]:
        """
        语义搜索相似案件
        
        Args:
            query_text: 查询文本（可以是案件描述、作案手法等）
            top_k: 返回最相似的k个案件
            min_similarity: 最小相似度阈值（0-1）
            
        Returns:
            相似案件列表，包含相似度分数
        """
        if not self.is_available():
            logger.warning("向量数据库不可用，无法搜索")
            return []
        
        try:
            # 生成查询embedding
            query_embedding = self.embedding_service.generate_embedding(query_text)
            if not query_embedding:
                logger.error("无法生成查询embedding")
                return []
            
            # 搜索相似向量
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            # 解析结果
            similar_cases = []
            if results["ids"] and len(results["ids"][0]) > 0:
                for i, case_id_str in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i] if results["distances"] else 1.0
                    # Chroma返回的是距离，转换为相似度（1 - distance）
                    similarity = 1.0 - distance if distance <= 1.0 else 0.0
                    
                    if similarity >= min_similarity:
                        metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                        similar_cases.append({
                            "case_id": int(case_id_str),
                            "similarity": round(similarity, 4),
                            "distance": round(distance, 4),
                            "metadata": metadata,
                            "document": results["documents"][0][i] if results["documents"] else ""
                        })
            
            return similar_cases
        except Exception as e:
            logger.error(f"语义搜索失败: {e}")
            return []
    
    def find_semantic_serial_cases(
        self,
        case_id: int,
        top_k: int = 10,
        min_similarity: float = 0.6
    ) -> List[Dict]:
        """
        基于语义相似度查找串案
        
        Args:
            case_id: 目标案件ID
            top_k: 返回最相似的k个案件
            min_similarity: 最小相似度阈值
            
        Returns:
            相似案件列表
        """
        if not self.is_available():
            return []
        
        try:
            # 获取目标案件的embedding
            results = self.collection.get(ids=[str(case_id)])
            if not results["ids"] or len(results["ids"]) == 0:
                logger.warning(f"案件 {case_id} 不在向量数据库中")
                return []
            
            # 使用目标案件的embedding搜索相似案件（排除自己）
            query_embedding = results["embeddings"][0]
            
            search_results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k + 1  # 多取一个，因为会排除自己
            )
            
            similar_cases = []
            if search_results["ids"] and len(search_results["ids"][0]) > 0:
                for i, found_id_str in enumerate(search_results["ids"][0]):
                    found_id = int(found_id_str)
                    if found_id == case_id:
                        continue  # 排除自己
                    
                    distance = search_results["distances"][0][i] if search_results["distances"] else 1.0
                    similarity = 1.0 - distance if distance <= 1.0 else 0.0
                    
                    if similarity >= min_similarity:
                        metadata = search_results["metadatas"][0][i] if search_results["metadatas"] else {}
                        similar_cases.append({
                            "case_id": found_id,
                            "similarity": round(similarity, 4),
                            "metadata": metadata
                        })
            
            return similar_cases
        except Exception as e:
            logger.error(f"查找语义串案失败: {e}")
            return []
