from sqlalchemy.orm import Session
from app.models.meeting import Meeting, MeetingConversation, AnalysisResult, Evaluation, Ranking
from app.models.report import Report
from app.models.case import Case
from app.ai.meeting_manager import MeetingManager
from app.services.case_service import CaseService
from app.services.case_quality_service import CaseQualityService
from app.services.system_config_service import SystemConfigService
from typing import List, Optional, Dict
import asyncio
import json
from app.utils.logger import logger


async def _default_progress_callback(meeting_id: str, stage: int, stage_name: str,
                                     status: str, progress: int, details: Optional[Dict] = None):
    """默认进度回调 - 通过 WebSocket 广播"""
    try:
        from app.api.websocket import broadcast_meeting_progress
        await broadcast_meeting_progress(meeting_id, stage, stage_name, status, progress, details)
    except Exception as e:
        logger.warning(f"广播会议进度失败: {e}")


class MeetingService:

    @staticmethod
    async def create_and_run_meeting(
        db: Session,
        case_ids: List[int],
        moderator_model_id: int,
        analyst_model_ids: List[int],
        existing_meeting_id: Optional[str] = None
    ) -> Dict:
        """创建并运行会议"""
        # 检查圆桌会议配置
        meeting_provider = SystemConfigService.get_config_value(db, "meeting_api_provider", "direct")
        if meeting_provider == "openrouter":
            meeting_api_key = SystemConfigService.get_config_value(db, "meeting_api_key", "")
            if not meeting_api_key:
                logger.warning("圆桌会议配置为OpenRouter模式，但未配置API密钥，将使用Direct模式")
        else:
            logger.info(f"圆桌会议使用Direct模式，直接使用AI模型配置中的API密钥")

        # 创建会议管理器（传入进度回调）
        manager = MeetingManager(db, progress_callback=_default_progress_callback)
        
        # 如果提供了已存在的会议ID，使用它；否则创建新的
        if existing_meeting_id:
            meeting_id = existing_meeting_id
            # 查找已存在的会议记录
            meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
            if not meeting:
                raise ValueError(f"会议 {meeting_id} 不存在")
            # 更新状态
            meeting.status = "first_opinions"
            db.commit()
            
            # 初始化 MeetingManager（不调用 start_meeting，因为会议已存在）
            manager.meeting_id = meeting_id
            from app.models.ai_model import AIModel
            from app.ai.agents.moderator import ModeratorAgent
            from app.ai.agents.analyst import AnalystAgent
            
            # 加载主持人模型
            moderator_model = db.query(AIModel).filter(AIModel.id == moderator_model_id).first()
            if not moderator_model:
                raise ValueError(f"主持人模型 {moderator_model_id} 不存在")
            manager.moderator = ModeratorAgent(
                moderator_model,
                manager.factory.create_llm(moderator_model)
            )
            
            # 加载分析员模型
            analyst_models = db.query(AIModel).filter(
                AIModel.id.in_(analyst_model_ids)
            ).all()
            if len(analyst_models) != len(analyst_model_ids):
                raise ValueError("部分分析员模型不存在")
            
            manager.analysts = []
            for model in analyst_models:
                specialty = None
                if model.config and isinstance(model.config, dict):
                    specialty = model.config.get("specialty")
                agent = AnalystAgent(model, manager.factory.create_llm(model), specialty=specialty)
                manager.analysts.append(agent)
        else:
            # 启动会议（创建新的）
            meeting_id = await manager.start_meeting(
                case_ids,
                moderator_model_id,
                analyst_model_ids
            )
            
            # 创建会议记录
            meeting = Meeting(
                meeting_id=meeting_id,
                case_ids=case_ids,
                status="first_opinions",
                moderator_model_id=moderator_model_id,
                analyst_model_ids=analyst_model_ids
            )
            db.add(meeting)
            db.commit()
        
        try:
            # 获取案件数据，并优先使用预处理后的结构化特征
            cases = CaseService.get_cases_by_ids(db, case_ids)
            case_data = []
            for c in cases:
                # 计算附近案件数量（1km 内），用于空间串并案提示
                nearby_cases = CaseService.get_nearby_cases(
                    db, center_case_id=c.id, radius_km=1.0
                )

                # 如果有预处理features，则优先从中取summary等
                features = c.features or {}
                basic = features.get("basic", {}) if isinstance(features, dict) else {}
                geo = features.get("geo", {}) if isinstance(features, dict) else {}
                oil = features.get("oil", {}) if isinstance(features, dict) else {}
                oil_facts = oil.get("facts", {}) if isinstance(oil, dict) else {}
                profile = CaseQualityService.build_case_feature_profile(db, c)

                summary = basic.get("summary") or (c.description or "")

                case_data.append(
                    {
                        "case_number": c.case_number,
                        "occurred_time": basic.get("time") or str(c.occurred_time),
                        "location": basic.get("location") or c.location,
                        "latitude": geo.get("latitude", c.latitude),
                        "longitude": geo.get("longitude", c.longitude),
                        "case_type": basic.get("case_type") or c.case_type,
                        "description": summary,
                        "involved_persons": c.involved_persons,
                        "involved_items": c.involved_items,
                        "loss_amount": c.loss_amount,
                        "nearby_case_count": len(nearby_cases),
                        "management": profile["management"],
                        "quality": profile["quality"],
                        "vehicles": profile["vehicles"],
                        "persons": profile["actors"]["persons"],
                        "evidence_count": len(profile["evidence"]),
                        # 涉油特征（如果有）
                        "oil_type": oil_facts.get("oil_type") or c.oil_type,
                        "oil_nature": c.oil_nature,
                        "oil_volume": oil_facts.get("volume") or c.oil_volume,
                        "water_cut": c.water_cut,
                        "facility_type": oil_facts.get("facility_type") or c.facility_type,
                        "modus_operandi": c.modus_operandi,
                        "analysis_readiness": (
                            features.get("analysis_readiness", {})
                            if isinstance(features, dict)
                            else {}
                        ),
                    }
                )
            
            # 获取地理线索分析（热点、串案等）
            from app.services.geo_analysis_service import GeoAnalysisService
            geo_clues = GeoAnalysisService.generate_geographic_clues(db, case_ids)
            
            # 获取地图MCP数据（位置信息、周边POI等）
            map_mcp_data = {}
            try:
                from app.services.map_mcp_service import MapMCPService
                # 为每个案件获取MCP数据
                for case in cases:
                    if case.latitude and case.longitude:
                        location_info = await MapMCPService.get_location_info(
                            case.latitude, case.longitude
                        )
                        nearby_pois = await MapMCPService.search_nearby_pois(
                            case.latitude,
                            case.longitude,
                            keywords="加油站|油库|输油管线|储油设施",
                            radius=2000
                        )
                        map_mcp_data[case.id] = {
                            "location_info": location_info,
                            "nearby_pois": nearby_pois
                        }
            except Exception as e:
                logger.warning(f"获取地图MCP数据失败（可忽略）: {str(e)}")
            
            # 格式化案件信息（包含地理线索和MCP数据）
            case_info = await manager.moderator.format_case_information(
                case_data, 
                geo_clues=geo_clues,
                map_mcp_data=map_mcp_data
            )
            
            # 记录主持人发言
            conversation = MeetingConversation(
                meeting_id=meeting_id,
                round_number=0,
                speaker_model_id=moderator_model_id,
                message_type="summary",
                content=case_info
            )
            db.add(conversation)
            db.commit()
            
            # ========== 第一阶段：第一意见 ==========
            meeting.status = "first_opinions"
            db.commit()
            
            analyses = await manager.conduct_stage_1_first_opinions(case_info)
            
            # 保存分析结果（第一阶段的独立回答）
            for i, (analyst, analysis) in enumerate(zip(manager.analysts, analyses)):
                result = AnalysisResult(
                    meeting_id=meeting_id,
                    analyst_model_id=analyst.model_id,
                    round_number=1,  # 第一阶段
                    result_content=analysis
                )
                db.add(result)
                
                # 记录对话
                conv = MeetingConversation(
                    meeting_id=meeting_id,
                    round_number=1,
                    speaker_model_id=analyst.model_id,
                    message_type="analysis",
                    content=json.dumps(analysis, ensure_ascii=False)
                )
                db.add(conv)
            
            db.commit()
            
            # ========== 第二阶段：复习和排名 ==========
            meeting.status = "reviewing"
            db.commit()
            
            rankings = await manager.conduct_stage_2_review_and_rank(analyses)
            
            # 保存排名结果
            for i, (analyst, ranking_result) in enumerate(zip(manager.analysts, rankings)):
                ranking = Ranking(
                    meeting_id=meeting_id,
                    evaluator_model_id=analyst.model_id,
                    stage="review",
                    ranking_data=ranking_result
                )
                db.add(ranking)
                
                # 记录对话
                conv = MeetingConversation(
                    meeting_id=meeting_id,
                    round_number=2,
                    speaker_model_id=analyst.model_id,
                    message_type="review",
                    content=f"排名结果: {json.dumps(ranking_result.get('rankings', []), ensure_ascii=False)}"
                )
                db.add(conv)
            
            db.commit()
            
            # ========== 第三阶段：最终回应 ==========
            meeting.status = "finalizing"
            db.commit()
            
            # 计算综合排名
            aggregated_rankings = manager._aggregate_rankings(rankings, analyses)
            
            final_report = await manager.conduct_stage_3_final_response(
                analyses,
                rankings
            )
            
            # 保存综合排名数据
            final_ranking = Ranking(
                meeting_id=meeting_id,
                evaluator_model_id=moderator_model_id,
                stage="final",
                ranking_data={},
                aggregated_data=aggregated_rankings
            )
            db.add(final_ranking)
            
            # 保存报告
            report = Report(
                meeting_id=meeting_id,
                report_type="comprehensive",
                content=final_report,
                consensus_points=final_report.get("consensus_points", []),
                disagreement_points=final_report.get("disagreement_points", []),
                model_contributions=final_report.get("model_contributions", {})
            )
            db.add(report)
            db.flush()
            
            # 更新会议状态
            meeting.status = "completed"
            meeting.final_report_id = report.id
            from datetime import datetime
            meeting.completed_at = datetime.utcnow()
            db.commit()
            
            # 记录主持人总结
            conv = MeetingConversation(
                meeting_id=meeting_id,
                round_number=3,
                speaker_model_id=moderator_model_id,
                message_type="summary",
                content=final_report.get("summary", "")
            )
            db.add(conv)
            db.commit()
            
            logger.info(f"会议 {meeting_id} 完成（三阶段流程）")
            
            return {
                "meeting_id": meeting_id,
                "status": "completed",
                "report_id": report.id
            }
            
        except Exception as e:
            logger.error(f"会议 {meeting_id} 执行失败: {str(e)}")
            meeting.status = "failed"
            db.commit()
            raise
    
    @staticmethod
    def get_meeting(db: Session, meeting_id: str) -> Optional[Meeting]:
        """获取会议"""
        return db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
    
    @staticmethod
    def get_meetings(
        db: Session,
        skip: int = 0,
        limit: int = 100
    ) -> List[Meeting]:
        """获取会议列表"""
        return db.query(Meeting).order_by(Meeting.created_at.desc()).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_meeting_conversations(
        db: Session,
        meeting_id: str
    ) -> List[MeetingConversation]:
        """获取会议对话记录"""
        return db.query(MeetingConversation).filter(
            MeetingConversation.meeting_id == meeting_id
        ).order_by(MeetingConversation.round_number, MeetingConversation.created_at).all()
    
    @staticmethod
    def get_meeting_report(
        db: Session,
        meeting_id: str
    ) -> Optional[Report]:
        """获取会议报告"""
        meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if not meeting or not meeting.final_report_id:
            return None
        return db.query(Report).filter(Report.id == meeting.final_report_id).first()
