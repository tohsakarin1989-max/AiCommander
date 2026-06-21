from app.models.ai_model import AIModel
from app.models.case import Case, CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
from app.models.meeting import Meeting, MeetingConversation, AnalysisResult, Evaluation, Ranking
from app.models.report import Report
from app.models.preprocess_job import PreprocessJob
from app.models.system_config import SystemConfig
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.agent_task import AgentTask
from app.models.event import Event, AreaProfile, EventRelation, AnalysisSession, EVENT_TYPES, RELATION_TYPES
from app.models.patrol import PatrolRecord, AreaRiskAssessment
from app.models.meeting_template import MeetingTemplate
from app.models.personnel import SecurityPersonnel
from app.models.key_location import KeyLocation
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.models.automation_alert import AutomationAlert
from app.models.chain_link import ChainLink

__all__ = [
    "AIModel",
    "Case",
    "CaseEvidence",
    "CasePerson",
    "CaseTip",
    "CaseVehicle",
    "OilRecoveryRecord",
    "Meeting",
    "MeetingConversation",
    "AnalysisResult",
    "Evaluation",
    "Ranking",
    "Report",
    "PreprocessJob",
    "SystemConfig",
    "Conclusion",
    "ConclusionReview",
    "AgentTask",
    # 事件和区域研判相关
    "Event",
    "AreaProfile",
    "EventRelation",
    "AnalysisSession",
    "EVENT_TYPES",
    "RELATION_TYPES",
    # 巡逻记录相关
    "PatrolRecord",
    "AreaRiskAssessment",
    # 会议模板
    "MeetingTemplate",
    # 保卫人员 & 重要部位
    "SecurityPersonnel",
    "KeyLocation",
    "JurisdictionAsset",
    "JurisdictionFeedback",
    "AutomationAlert",
    "ChainLink",
]
