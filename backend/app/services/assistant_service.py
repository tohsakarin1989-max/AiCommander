from sqlalchemy.orm import Session
from app.models.case import Case
from app.models.meeting import Meeting
from app.models.report import Report
from app.models.ai_model import AIModel
from app.ai.model_factory import ModelFactory
from app.services.case_service import CaseService
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.meeting_service import MeetingService
from typing import Dict, List, Optional
import json
from datetime import datetime
from app.utils.logger import logger


class AssistantService:
    """智能助手服务 - 为用户提供案件信息查询和问答服务"""
    
    @staticmethod
    def _get_llm(db: Session):
        """获取用于智能助手的LLM模型"""
        factory = ModelFactory()
        # 优先使用默认的主持人模型
        moderator_model = db.query(AIModel).filter(
            AIModel.role == "moderator",
            AIModel.is_default == True,
            AIModel.is_active == True
        ).first()
        
        if not moderator_model:
            # 如果没有默认的，尝试获取任意一个活跃的主持人模型
            moderator_model = db.query(AIModel).filter(
                AIModel.role == "moderator",
                AIModel.is_active == True
            ).first()
        
        if not moderator_model:
            # 如果还是没有，尝试获取任意一个活跃的模型
            moderator_model = db.query(AIModel).filter(
                AIModel.is_active == True
            ).first()
        
        if not moderator_model:
            return None
        
        try:
            return factory.create_llm(moderator_model)
        except Exception as e:
            logger.error(f"创建LLM失败: {e}")
            return None
    
    @staticmethod
    def _gather_context(db: Session, query: str) -> Dict:
        """根据用户查询收集相关上下文信息"""
        context = {
            "cases_summary": [],
            "reports_summary": [],
            "statistics": {},
            "case_intelligence": {},
        }
        
        try:
            # 获取最近的案件（最多10个）
            recent_cases = db.query(Case).order_by(Case.created_at.desc()).limit(10).all()
            context["cases_summary"] = [
                {
                    "id": c.id,
                    "case_number": c.case_number,
                    "occurred_time": str(c.occurred_time) if c.occurred_time else None,
                    "location": c.location,
                    "description": (c.description or "")[:200] if c.description else "",
                    "case_type": c.case_type,
                }
                for c in recent_cases
            ]
            
            # 获取最近的报告（最多5个）
            recent_meetings = db.query(Meeting).filter(
                Meeting.status == "completed"
            ).order_by(Meeting.created_at.desc()).limit(5).all()
            
            for meeting in recent_meetings:
                report = MeetingService.get_meeting_report(db, meeting.meeting_id)
                if report:
                    context["reports_summary"].append({
                        "meeting_id": meeting.meeting_id,
                        "summary": report.content.get("summary", "")[:200] if isinstance(report.content, dict) else str(report.content)[:200],
                        "created_at": str(meeting.created_at),
                    })
            
            # 统计信息
            total_cases = db.query(Case).count()
            completed_meetings = db.query(Meeting).filter(Meeting.status == "completed").count()
            context["statistics"] = {
                "total_cases": total_cases,
                "completed_meetings": completed_meetings,
            }

            selected_case_id = None
            normalized_query = str(query or "")
            for case in context["cases_summary"]:
                case_number = case.get("case_number")
                if case_number and case_number in normalized_query:
                    selected_case_id = case.get("id")
                    break
                if str(case.get("id")) in normalized_query:
                    selected_case_id = case.get("id")
                    break

            workbench = CaseIntelligenceService.build_workbench(
                db,
                case_id=selected_case_id,
                days=365,
                limit=5,
            )
            tags = workbench.get("feature_tags", {}).get("tags", [])
            similar_items = workbench.get("similar_cases", {}).get("items", [])
            suggestions = workbench.get("prevention_suggestions", {}).get("items", [])
            context["case_intelligence"] = {
                "scope": workbench.get("scope"),
                "selected_case": workbench.get("selected_case"),
                "top_tags": [tag.get("label") for tag in tags[:8] if tag.get("label")],
                "spatiotemporal_insights": workbench.get("spatiotemporal", {}).get("insights", [])[:5],
                "similar_cases": [
                    {
                        "case_number": item.get("case", {}).get("case_number"),
                        "score": item.get("similarity_score"),
                        "reasons": item.get("reasons", [])[:3],
                    }
                    for item in similar_items[:5]
                ],
                "suggestions": [
                    {
                        "title": item.get("title"),
                        "action": item.get("action"),
                        "basis": item.get("reason", [])[:3],
                    }
                    for item in suggestions[:5]
                ],
                "boundary": workbench.get("prevention_suggestions", {}).get("boundary"),
            }
            
        except Exception as e:
            logger.error(f"收集上下文信息失败: {e}")
        
        return context
    
    @staticmethod
    async def chat(db: Session, user_query: str, conversation_history: List[Dict] = None) -> Dict:
        """处理用户查询并返回智能回答"""
        if conversation_history is None:
            conversation_history = []
        
        # 获取LLM
        llm = AssistantService._get_llm(db)
        if not llm:
            return {
                "answer": "抱歉，系统未配置AI模型，无法提供智能问答服务。请联系管理员配置AI模型。",
                "sources": [],
                "error": "未配置AI模型"
            }
        
        # 收集上下文信息
        context = AssistantService._gather_context(db, user_query)
        
        # 构建提示词
        context_text = f"""
【系统上下文信息】

统计信息：
- 案件总数：{context['statistics'].get('total_cases', 0)}
- 已完成会议数：{context['statistics'].get('completed_meetings', 0)}

最近案件（最多10条）：
"""
        for i, case in enumerate(context["cases_summary"][:10], 1):
            context_text += f"""
{i}. 案件编号：{case.get('case_number', 'N/A')}
   发生时间：{case.get('occurred_time', 'N/A')}
   地点：{case.get('location', 'N/A')}
   类型：{case.get('case_type', 'N/A')}
   描述：{case.get('description', 'N/A')[:100]}...
"""
        
        if context["reports_summary"]:
            context_text += "\n最近分析报告：\n"
            for i, report in enumerate(context["reports_summary"][:5], 1):
                context_text += f"""
{i}. 会议ID：{report.get('meeting_id', 'N/A')}
   摘要：{report.get('summary', 'N/A')[:100]}...
   创建时间：{report.get('created_at', 'N/A')}
"""
        intelligence = context.get("case_intelligence") or {}
        if intelligence:
            context_text += "\n案件研判工作台摘要：\n"
            context_text += f"- 范围：{intelligence.get('scope')}\n"
            if intelligence.get("selected_case"):
                context_text += f"- 命中案件：{intelligence.get('selected_case')}\n"
            if intelligence.get("top_tags"):
                context_text += f"- 主要标签：{'、'.join(intelligence['top_tags'])}\n"
            if intelligence.get("spatiotemporal_insights"):
                context_text += "- 时空洞察：\n"
                for item in intelligence["spatiotemporal_insights"]:
                    context_text += f"  · {item}\n"
            if intelligence.get("similar_cases"):
                context_text += "- 相似条件案件：\n"
                for item in intelligence["similar_cases"]:
                    context_text += f"  · {item.get('case_number')}，分值 {item.get('score')}，依据：{'; '.join(item.get('reasons') or [])}\n"
            if intelligence.get("suggestions"):
                context_text += "- 防控参考草案：\n"
                for item in intelligence["suggestions"]:
                    context_text += f"  · {item.get('title')}：{item.get('action')}，依据：{'; '.join(item.get('basis') or [])}\n"
            if intelligence.get("boundary"):
                context_text += f"- 边界：{intelligence.get('boundary')}\n"
        
        # 构建对话历史
        history_text = ""
        if conversation_history:
            history_text = "\n【对话历史】\n"
            for msg in conversation_history[-5:]:  # 只保留最近5轮对话
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_text += f"{'用户' if role == 'user' else '助手'}: {content}\n"
        
        prompt = f"""你是一个专业的案件分析智能助手，帮助用户查询和了解案件信息、分析报告等。

{context_text}

{history_text}

【用户问题】
{user_query}

【回答要求】
1. 基于提供的上下文信息回答用户问题
2. 如果用户询问具体案件，请提供案件编号、时间、地点等关键信息
3. 如果用户询问报告，请提供报告摘要和关键发现
4. 如果信息不足，请诚实告知，不要编造信息
5. 涉及研判时必须区分“事实依据、模式推断、防控参考”，不能把建议说成已执行任务
6. 如果用户的问题无法从当前上下文中找到答案，可以建议用户查看具体的案件详情或报告详情

请用自然、友好的语言回答用户的问题："""
        
        try:
            response = await llm.ainvoke(prompt)
            answer = response.content
            
            # 提取可能的来源（案件编号、会议ID等）
            sources = []
            if context["cases_summary"]:
                # 检查回答中是否提到了案件编号
                for case in context["cases_summary"]:
                    case_num = case.get("case_number", "")
                    if case_num and case_num in answer:
                        sources.append({
                            "type": "case",
                            "id": case.get("id"),
                            "case_number": case_num
                        })
            
            if context["reports_summary"]:
                for report in context["reports_summary"]:
                    meeting_id = report.get("meeting_id", "")
                    if meeting_id and meeting_id in answer:
                        sources.append({
                            "type": "report",
                            "meeting_id": meeting_id
                        })
            
            return {
                "answer": answer,
                "sources": sources,
                "context_used": {
                    "cases_count": len(context["cases_summary"]),
                    "reports_count": len(context["reports_summary"]),
                }
            }
            
        except Exception as e:
            logger.error(f"生成回答失败: {e}")
            return {
                "answer": f"抱歉，处理您的问题时出现错误：{str(e)}。请稍后重试或联系管理员。",
                "sources": [],
                "error": str(e)
            }
