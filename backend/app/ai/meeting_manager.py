from app.models.ai_model import AIModel
from app.ai.agents.moderator import ModeratorAgent
from app.ai.agents.analyst import AnalystAgent
from app.ai.model_factory import ModelFactory
from app.ai.anonymizer import Anonymizer
from app.services.case_service import CaseService
from sqlalchemy.orm import Session
from typing import List, Dict
import uuid
import asyncio
from app.utils.logger import logger

class MeetingManager:
    """圆桌会议管理器"""
    
    def __init__(self, db: Session):
        self.db = db
        self.meeting_id = None
        self.moderator = None
        self.analysts = []
        self.anonymizer = Anonymizer()
        self.factory = ModelFactory()
    
    async def start_meeting(
        self,
        case_ids: List[int],
        moderator_model_id: int,
        analyst_model_ids: List[int]
    ) -> str:
        """启动会议"""
        # 生成会议ID
        self.meeting_id = f"MEET-{uuid.uuid4().hex[:8].upper()}"
        
        # 加载主持人模型
        moderator_model = self.db.query(AIModel).filter(
            AIModel.id == moderator_model_id
        ).first()
        if not moderator_model:
            raise ValueError(f"主持人模型 {moderator_model_id} 不存在")
        
        self.moderator = ModeratorAgent(
            moderator_model,
            self.factory.create_llm(moderator_model)
        )
        
        # 加载分析员模型，并根据config.specialty专家角色化
        analyst_models = self.db.query(AIModel).filter(
            AIModel.id.in_(analyst_model_ids)
        ).all()
        
        if len(analyst_models) != len(analyst_model_ids):
            raise ValueError("部分分析员模型不存在")
        
        self.analysts = []
        for model in analyst_models:
            specialty = None
            if model.config and isinstance(model.config, dict):
                specialty = model.config.get("specialty")
            agent = AnalystAgent(model, self.factory.create_llm(model), specialty=specialty)
            self.analysts.append(agent)
        
        logger.info(
            f"启动会议 {self.meeting_id}, 主持人: {moderator_model.name}, "
            f"分析员: {[m.name for m in analyst_models]}"
        )
        
        return self.meeting_id
    
    async def conduct_stage_1_first_opinions(self, case_info: str) -> List[Dict]:
        """
        第一阶段：第一意见
        所有LLM独立回答，收集回复（类似标签视图）
        """
        logger.info(f"会议 {self.meeting_id} 开始第一阶段：第一意见")
        tasks = [
            analyst.analyze_cases(case_info)
            for analyst in self.analysts
        ]
        results = await asyncio.gather(*tasks)
        logger.info(f"会议 {self.meeting_id} 第一阶段完成，共收集 {len(results)} 个独立回答")
        return results
    
    async def conduct_stage_2_review_and_rank(self, analyses: List[Dict]) -> List[Dict]:
        """
        第二阶段：复习和排名
        每个LLM匿名审查其他LLM的回答并排名（并发执行）
        """
        logger.info(f"会议 {self.meeting_id} 开始第二阶段：复习和排名")

        # 创建完全匿名的批次（打乱顺序，移除身份信息）
        anonymous_batch = self.anonymizer.create_anonymous_batch(analyses)

        async def rank_by_analyst(analyst_index: int, analyst: AnalystAgent) -> Dict:
            """单个分析员的排名任务"""
            # 获取其他分析员的结果（排除自己）
            other_analyses = [
                anonymous_batch[j]
                for j in range(len(anonymous_batch))
                if anonymous_batch[j].get("_anonymous_id") != f"Response_{analyst_index+1}"
            ]

            # 如果只有自己，跳过排名
            if not other_analyses:
                logger.warning(f"分析员 {analyst_index+1} 没有其他结果可排名")
                return {
                    "analyst_index": analyst_index,
                    "rankings": [],
                    "overall_comment": "无其他分析结果可排名"
                }

            # 进行排名
            ranking_result = await analyst.rank_analyses(other_analyses)
            ranking_result["analyst_index"] = analyst_index
            return ranking_result

        # 并发执行所有分析员的排名任务
        ranking_tasks = [
            rank_by_analyst(i, analyst)
            for i, analyst in enumerate(self.analysts)
        ]
        all_rankings = await asyncio.gather(*ranking_tasks)

        logger.info(f"会议 {self.meeting_id} 第二阶段完成，共收集 {len(all_rankings)} 个排名结果")
        return list(all_rankings)
    
    async def conduct_stage_3_final_response(
        self,
        original_analyses: List[Dict],
        rankings: List[Dict]
    ) -> Dict:
        """
        第三阶段：最终回应
        主席级LLM汇总所有回答和排名，生成最终答案
        """
        logger.info(f"会议 {self.meeting_id} 开始第三阶段：最终回应")
        
        # 计算综合排名（基于所有LLM的排名结果）
        aggregated_rankings = self._aggregate_rankings(rankings, original_analyses)
        
        # 生成最终报告
        report = await self.moderator.generate_final_report(
            original_analyses,
            rankings,
            aggregated_rankings
        )
        
        logger.info(f"会议 {self.meeting_id} 第三阶段完成")
        return report
    
    def _aggregate_rankings(
        self,
        rankings: List[Dict],
        original_analyses: List[Dict]
    ) -> Dict:
        """
        聚合所有LLM的排名结果，计算综合排名
        返回每个分析结果的综合得分和排名
        """
        # 建立匿名ID到原始索引的映射
        anonymous_to_index = {}
        for i, analysis in enumerate(original_analyses):
            anonymous_id = f"Response_{i+1}"
            anonymous_to_index[anonymous_id] = i
        
        # 收集所有排名数据
        scores = {}  # {anonymous_id: [scores]}
        rank_positions = {}  # {anonymous_id: [rank positions]}
        
        for ranking_result in rankings:
            if "rankings" not in ranking_result:
                continue
                
            for rank_item in ranking_result.get("rankings", []):
                anonymous_id = rank_item.get("anonymous_id")
                if not anonymous_id:
                    continue
                
                score = rank_item.get("score", 0)
                rank = rank_item.get("rank", 999)
                
                if anonymous_id not in scores:
                    scores[anonymous_id] = []
                    rank_positions[anonymous_id] = []
                
                scores[anonymous_id].append(score)
                rank_positions[anonymous_id].append(rank)
        
        # 计算平均得分和平均排名
        aggregated = {}
        for anonymous_id, score_list in scores.items():
            if anonymous_id in anonymous_to_index:
                original_index = anonymous_to_index[anonymous_id]
                avg_score = sum(score_list) / len(score_list) if score_list else 0
                avg_rank = sum(rank_positions[anonymous_id]) / len(rank_positions[anonymous_id]) if rank_positions[anonymous_id] else 999
                
                aggregated[original_index] = {
                    "anonymous_id": anonymous_id,
                    "average_score": round(avg_score, 2),
                    "average_rank": round(avg_rank, 2),
                    "vote_count": len(score_list)
                }
        
        # 按平均得分排序
        sorted_aggregated = sorted(
            aggregated.items(),
            key=lambda x: x[1]["average_score"],
            reverse=True
        )
        
        return {
            "rankings": dict(sorted_aggregated),
            "summary": f"共 {len(rankings)} 个LLM参与排名，{len(aggregated)} 个分析结果被评价"
        }

