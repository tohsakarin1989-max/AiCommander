from sqlalchemy.orm import Session
from app.models.meeting import Meeting, MeetingConversation, AnalysisResult, Evaluation, Ranking
from app.models.report import Report
from app.models.case import Case
from app.ai.meeting_manager import MeetingManager
from app.services.system_config_service import SystemConfigService
from app.database import require_area_write_access
from typing import List, Optional, Dict
import asyncio
import json
from app.utils.logger import logger
from app.services.intelligent_query_context import result_hash


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
    def validate_models(db: Session, moderator_model_id: int, analyst_model_ids: List[int]) -> None:
        from app.models.ai_model import AIModel

        moderator = db.query(AIModel).filter(
            AIModel.id == moderator_model_id, AIModel.is_active.is_(True),
            AIModel.role == "moderator",
        ).first()
        if not moderator:
            raise ValueError("请选择有效且启用的主持人模型")
        if not analyst_model_ids or len(set(analyst_model_ids)) != len(analyst_model_ids):
            raise ValueError("请选择不重复的分析员模型")
        count = db.query(AIModel).filter(
            AIModel.id.in_(analyst_model_ids), AIModel.is_active.is_(True),
            AIModel.role == "analyst",
        ).count()
        if count != len(analyst_model_ids):
            raise ValueError("请选择有效且启用的分析员模型")
        # Frozen results still contain sensitive internal evidence. Protocol
        # compatibility is not permission to export it to a public provider.
        from app.ai.model_factory import ModelFactory
        for model in db.query(AIModel).filter(AIModel.id.in_([moderator_model_id, *analyst_model_ids])):
            ModelFactory._assert_data_egress_allowed(
                model, provider=(model.provider or '').lower(), data_classification='raw')

    @staticmethod
    def bind_existing_meeting_scope(
        db: Session,
        meeting_id: str,
        case_ids: List[int],
    ) -> Meeting:
        """后台任务先以已持久化会议为信任锚点，再收紧整个会话范围。"""
        meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if not meeting:
            raise ValueError(f"会议 {meeting_id} 不存在")
        stored_ids = list(dict.fromkeys(int(item) for item in (meeting.case_ids or [])))
        requested_ids = list(dict.fromkeys(int(item) for item in case_ids))
        if stored_ids != requested_ids:
            raise ValueError("meeting_case_scope_mismatch")
        if meeting.operational_area_id is None:
            raise ValueError("meeting_area_required")
        area_id = meeting.operational_area_id
        db.info["authorized_area_ids"] = (area_id,)
        db.info["default_operational_area_id"] = area_id
        db.info["area_access_levels"] = {area_id: "write"}
        return meeting

    @staticmethod
    def resolve_meeting_area(db: Session, case_ids: List[int]) -> int:
        normalized_ids = list(dict.fromkeys(int(item) for item in case_ids))
        if not normalized_ids:
            raise ValueError("meeting_cases_required")
        cases = db.query(Case).filter(Case.id.in_(normalized_ids)).all()
        if len(cases) != len(normalized_ids):
            raise ValueError("meeting_case_not_found_or_out_of_scope")
        area_ids = {item.operational_area_id for item in cases if item.operational_area_id is not None}
        if len(area_ids) > 1:
            raise ValueError("meeting_cross_area_not_allowed")
        area_id = next(iter(area_ids), db.info.get("default_operational_area_id"))
        checked = require_area_write_access(db, area_id)
        if checked is None:
            raise ValueError("meeting_area_required")
        return checked

    @staticmethod
    async def create_and_run_meeting(
        db: Session,
        case_ids: List[int],
        moderator_model_id: int,
        analyst_model_ids: List[int],
        existing_meeting_id: Optional[str] = None
    ) -> Dict:
        """创建并运行会议"""
        if existing_meeting_id:
            MeetingService.bind_existing_meeting_scope(db, existing_meeting_id, case_ids)
        operational_area_id = MeetingService.resolve_meeting_area(db, case_ids)
        MeetingService.validate_models(db, moderator_model_id, analyst_model_ids)
        # 检查圆桌会议配置
        meeting_provider = SystemConfigService.get_config_value(db, "meeting_api_provider", "direct")
        if meeting_provider == "openrouter":
            raise ValueError('冻结案件资料只能使用已登记的可信内网模型，不支持外部会议代理')
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
            if meeting.operational_area_id != operational_area_id:
                raise ValueError("meeting_scope_mismatch")
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
                operational_area_id=operational_area_id,
                case_ids=case_ids,
                status="first_opinions",
                moderator_model_id=moderator_model_id,
                analyst_model_ids=analyst_model_ids
            )
            db.add(meeting)
            db.commit()
        
        try:
            from app.services.meeting_frozen_service import freeze_meeting_inputs
            frozen = freeze_meeting_inputs(db, meeting)
            # Deterministic serialization; no fresh extraction/geography and no
            # model is asked to manufacture the source summary or references.
            case_info = json.dumps(frozen, ensure_ascii=False, sort_keys=True)
            
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
            from app.services.meeting_frozen_service import read_meeting_inputs
            if read_meeting_inputs(db, meeting_id) != frozen:
                raise PermissionError('meeting_sources_changed')
            report = Report(
                meeting_id=meeting_id,
                report_type="comprehensive",
                content={**final_report, 'source_manifest': frozen['sources'],
                         'input_sha256': result_hash(frozen),
                         'result_kind': 'model_discussion',
                         'boundary': frozen['boundary']},
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
            
            # 报告、排名、总结与完成状态一次提交，失败时整体回滚。
            conv = MeetingConversation(
                meeting_id=meeting_id,
                round_number=3,
                speaker_model_id=moderator_model_id,
                message_type="summary",
                content=final_report.get("summary", "")
            )
            db.add(conv)
            db.commit()
            await manager._notify_progress(
                stage=3, stage_name="综合报告", status="completed", progress=100,
                details={"report_generated": True},
            )
            
            logger.info(f"会议 {meeting_id} 完成（三阶段流程）")
            
            return {
                "meeting_id": meeting_id,
                "status": "completed",
                "report_id": report.id
            }
            
        except Exception as e:
            logger.error(f"会议 {meeting_id} 执行失败: {str(e)}")
            db.rollback()
            meeting.status = "failed"
            db.commit()
            raise
    
    @staticmethod
    def get_meeting(db: Session, meeting_id: str) -> Optional[Meeting]:
        """获取会议"""
        meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if meeting:
            from app.services.meeting_frozen_service import require_meeting_sources
            try:
                require_meeting_sources(db, meeting)
            except (PermissionError, ValueError):
                return None
        return meeting
    
    @staticmethod
    def get_meetings(
        db: Session,
        skip: int = 0,
        limit: int = 100
    ) -> List[Meeting]:
        """获取会议列表"""
        return [row for row in db.query(Meeting).order_by(Meeting.created_at.desc()).offset(skip).limit(limit)
                if MeetingService.get_meeting(db, row.meeting_id) is not None]
    
    @staticmethod
    def get_meeting_conversations(
        db: Session,
        meeting_id: str
    ) -> List[MeetingConversation]:
        """获取会议对话记录"""
        if MeetingService.get_meeting(db, meeting_id) is None:
            return []
        return db.query(MeetingConversation).filter(
            MeetingConversation.meeting_id == meeting_id
        ).order_by(MeetingConversation.round_number, MeetingConversation.created_at).all()
    
    @staticmethod
    def get_meeting_report(
        db: Session,
        meeting_id: str
    ) -> Optional[Report]:
        """获取会议报告"""
        meeting = MeetingService.get_meeting(db, meeting_id)
        if not meeting or not meeting.final_report_id:
            return None
        from app.services.meeting_frozen_service import report_sources_visible
        report = db.query(Report).filter(Report.id == meeting.final_report_id).first()
        return report if report and report_sources_visible(db, report) else None
