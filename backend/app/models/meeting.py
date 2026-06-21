from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class Meeting(Base):
    __tablename__ = "meetings"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), unique=True, nullable=False, index=True)
    case_ids = Column(JSON)  # 关联的案件ID列表
    status = Column(String(20), default="pending")  # pending, first_opinions, reviewing, ranking, finalizing, completed
    moderator_model_id = Column(Integer, ForeignKey("ai_models.id"))
    analyst_model_ids = Column(JSON)  # 分析员模型ID列表
    final_report_id = Column(Integer, ForeignKey("reports.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

class MeetingConversation(Base):
    __tablename__ = "meeting_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), ForeignKey("meetings.meeting_id"), index=True)
    round_number = Column(Integer, nullable=False)
    speaker_model_id = Column(Integer, ForeignKey("ai_models.id"))
    message_type = Column(String(20))  # analysis, review, feedback, summary
    content = Column(Text, nullable=False)
    extra_data = Column(JSON)  # 原metadata字段，改为extra_data避免与SQLAlchemy保留字冲突
    parent_message_id = Column(Integer, ForeignKey("meeting_conversations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), ForeignKey("meetings.meeting_id"), index=True)
    analyst_model_id = Column(Integer, ForeignKey("ai_models.id"))
    round_number = Column(Integer, nullable=False)
    result_content = Column(JSON, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Evaluation(Base):
    __tablename__ = "evaluations"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), ForeignKey("meetings.meeting_id"), index=True)
    evaluator_model_id = Column(Integer, ForeignKey("ai_models.id"))
    target_result_id = Column(Integer, ForeignKey("analysis_results.id"))
    score = Column(Integer)  # 1-10
    strengths = Column(JSON)
    weaknesses = Column(JSON)
    suggestions = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Ranking(Base):
    __tablename__ = "rankings"
    
    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(String(64), ForeignKey("meetings.meeting_id"), index=True)
    evaluator_model_id = Column(Integer, ForeignKey("ai_models.id"))  # 进行排名的模型ID
    stage = Column(String(20), default="review")  # review, final
    ranking_data = Column(JSON, nullable=False)  # 完整的排名结果（包含rankings数组）
    aggregated_data = Column(JSON, nullable=True)  # 综合排名数据（仅final阶段有）
    created_at = Column(DateTime(timezone=True), server_default=func.now())

