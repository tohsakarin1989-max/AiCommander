"""数智自动化告警服务。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.automation_alert import AutomationAlert
from app.models.event import Event
from app.services.case_service import CaseService
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.preprocess_service import CasePreprocessService


ALERT_EVENT_TYPE_MAP = {
    "well_parameter_anomaly": "suspect_activity",
    "pipeline_pressure_anomaly": "pipeline_tap",
    "sensing_target_detected": "suspect_activity",
}


SIMULATED_ALERTS: List[Dict[str, Any]] = [
    {
        "source_system": "simulated-a2-radar-ptz",
        "alert_type": "well_parameter_anomaly",
        "title": "萨中采油区 W-2341 井口异常",
        "description": "流量较基线下降 34%，压力骤降 0.42 MPa。雷达检测到 2 人 1 车，云台已锁定，建议人工复核后转现场核查。",
        "level": "critical",
        "risk_level": "critical",
        "location": "萨中采油区 W-2341 井口",
        "facility_id": "W-2341",
        "facility_name": "萨中采油区 W-2341 井口",
        "parameter_snapshot": {
            "flow_drop_percent": 34,
            "pressure_drop_mpa": 0.42,
            "baseline_window": "近7日同一时段",
        },
        "sensing_summary": {
            "radar_targets": {"person": 2, "vehicle": 1},
            "ptz_status": "已锁定并模拟抓拍",
        },
        "ai_assessment": {
            "result": "suspicious",
            "confidence": 0.86,
            "basis": ["井口流量骤降", "雷达发现人员车辆目标", "异常发生在凌晨时段"],
        },
        "suggested_actions": ["复核 A2 井口参数曲线", "调阅云台录像和雷达目标记录", "核查井口周边车辆停留线索"],
    },
    {
        "source_system": "simulated-a2-pressure",
        "alert_type": "pipeline_pressure_anomaly",
        "title": "喇嘛甸输油干线 K112 段压差异常",
        "description": "AI 判断：疑似管线开孔，非设备故障。热点区域 α 内，周边无监控覆盖，建议转入人工核查。",
        "level": "high",
        "risk_level": "high",
        "location": "喇嘛甸输油干线 K112 段",
        "facility_id": "K112",
        "facility_name": "喇嘛甸输油干线 K112 段",
        "parameter_snapshot": {
            "pressure_diff_status": "异常扩大",
            "baseline_window": "近30日同一管段",
        },
        "sensing_summary": {
            "monitoring_gap": "周边无近距离视频覆盖",
            "manual_review_required": True,
        },
        "ai_assessment": {
            "result": "needs_review",
            "confidence": 0.78,
            "basis": ["压差异常", "历史热点区域", "技防覆盖不足"],
        },
        "suggested_actions": ["复核 K112 段压差曲线", "核对夜间车辆停留点", "进入事件中心持续跟踪"],
    },
]


class AutomationAlertService:
    """数智自动化告警入库、归档和转事件/案件。"""

    @staticmethod
    def _next_alert_number(db: Session, generated_at: Optional[datetime] = None) -> str:
        generated_at = generated_at or datetime.utcnow()
        prefix = f"AUTO{generated_at.strftime('%Y%m%d')}"
        existing_numbers = db.query(AutomationAlert.alert_number).filter(
            AutomationAlert.alert_number.like(f"{prefix}%")
        ).all()

        max_sequence = 0
        for alert_number, in existing_numbers:
            suffix = alert_number.replace(prefix, "", 1)
            if suffix.isdigit():
                max_sequence = max(max_sequence, int(suffix))
        return f"{prefix}{max_sequence + 1:03d}"

    @staticmethod
    def _next_event_number(db: Session, generated_at: Optional[datetime] = None) -> str:
        generated_at = generated_at or datetime.utcnow()
        prefix = f"EVT{generated_at.strftime('%Y%m%d')}"
        existing_numbers = db.query(Event.event_number).filter(Event.event_number.like(f"{prefix}%")).all()
        max_sequence = 0
        for event_number, in existing_numbers:
            suffix = event_number.replace(prefix, "", 1)
            if suffix.isdigit():
                max_sequence = max(max_sequence, int(suffix))
        return f"{prefix}{max_sequence + 1:03d}"

    @staticmethod
    def create_alert(db: Session, payload: Dict[str, Any]) -> AutomationAlert:
        occurred_time = payload.get("occurred_time") or datetime.utcnow()
        for _ in range(5):
            alert = AutomationAlert(
                alert_number=AutomationAlertService._next_alert_number(db, occurred_time),
                source_system=payload.get("source_system") or "manual",
                alert_type=payload["alert_type"],
                title=payload["title"],
                description=payload.get("description"),
                level=payload.get("level") or "medium",
                risk_level=payload.get("risk_level") or "high",
                occurred_time=occurred_time,
                location=payload.get("location"),
                latitude=payload.get("latitude"),
                longitude=payload.get("longitude"),
                facility_id=payload.get("facility_id"),
                facility_name=payload.get("facility_name"),
                parameter_snapshot=payload.get("parameter_snapshot") or {},
                sensing_summary=payload.get("sensing_summary") or {},
                ai_assessment=payload.get("ai_assessment") or {},
                suggested_actions=payload.get("suggested_actions") or [],
                status=payload.get("status") or "pending_review",
                handling_result=payload.get("handling_result") or "待人工核查",
                is_simulated=bool(payload.get("is_simulated", False)),
            )
            db.add(alert)
            try:
                db.commit()
                db.refresh(alert)
                return alert
            except IntegrityError:
                db.rollback()
        raise ValueError("alert_number_conflict")

    @staticmethod
    def seed_simulated_alerts(db: Session) -> List[AutomationAlert]:
        alerts: List[AutomationAlert] = []
        for item in SIMULATED_ALERTS:
            existing = db.query(AutomationAlert).filter(
                AutomationAlert.source_system == item["source_system"],
                AutomationAlert.facility_id == item["facility_id"],
                AutomationAlert.is_simulated == True,
            ).first()
            if existing:
                alerts.append(existing)
                continue
            alerts.append(AutomationAlertService.create_alert(db, {**item, "is_simulated": True}))
        return alerts

    @staticmethod
    def list_alerts(
        db: Session,
        *,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[AutomationAlert]:
        query = db.query(AutomationAlert)
        if status:
            query = query.filter(AutomationAlert.status == status)
        return query.order_by(AutomationAlert.occurred_time.desc(), AutomationAlert.id.desc()).limit(limit).all()

    @staticmethod
    def get_alert(db: Session, alert_id: int) -> AutomationAlert:
        alert = db.query(AutomationAlert).filter(AutomationAlert.id == alert_id).first()
        if not alert:
            raise ValueError("alert_not_found")
        return alert

    @staticmethod
    def ensure_event(db: Session, alert_id: int) -> Event:
        alert = AutomationAlertService.get_alert(db, alert_id)
        if alert.related_event_id:
            event = db.query(Event).filter(Event.id == alert.related_event_id).first()
            if event:
                return event

        event = Event(
            event_number=AutomationAlertService._next_event_number(db, alert.occurred_time),
            event_type=ALERT_EVENT_TYPE_MAP.get(alert.alert_type, "suspect_activity"),
            occurred_time=alert.occurred_time,
            location=alert.location,
            latitude=alert.latitude,
            longitude=alert.longitude,
            title=alert.title,
            description=alert.description,
            discovery_method="数智自动化告警",
            handling_result="待人工核查",
            risk_level=alert.risk_level,
            analysis_notes=AutomationAlertService._build_analysis_notes(alert),
            suggested_actions=alert.suggested_actions,
        )
        db.add(event)
        db.flush()
        alert.related_event_id = event.id
        alert.status = "event_created"
        alert.handling_result = "已生成事件，待人工核查"
        db.commit()
        db.refresh(event)
        return event

    @staticmethod
    def mark_false_alarm(db: Session, alert_id: int, note: Optional[str] = None) -> AutomationAlert:
        alert = AutomationAlertService.get_alert(db, alert_id)
        if alert.related_case_id:
            raise ValueError("converted_alert_cannot_be_false_alarm")
        alert.status = "false_alarm"
        alert.risk_level = "low"
        alert.handling_result = "已核查-误报或设备异常"
        alert.review_notes = note or "人工标记为误报或设备异常"

        if alert.related_event_id:
            event = db.query(Event).filter(Event.id == alert.related_event_id).first()
            if event:
                event.risk_level = "low"
                event.handling_result = alert.handling_result
                event.analysis_notes = f"{event.analysis_notes or ''}\n误报归档：{alert.review_notes}".strip()
                event.suggested_actions = ["记录设备状态", "回看参数曲线", "纳入误报样本优化阈值"]

        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def convert_to_case(db: Session, alert_id: int) -> Dict[str, Any]:
        alert = AutomationAlertService.get_alert(db, alert_id)
        if alert.status == "false_alarm":
            raise ValueError("false_alarm_cannot_convert_to_case")
        if alert.related_case_id:
            return {"alert_id": alert.id, "case_id": alert.related_case_id, "message": "告警已关联案件"}

        event = AutomationAlertService.ensure_event(db, alert.id)
        case = CaseService.create_case(
            db=db,
            case_number=None,
            occurred_time=alert.occurred_time,
            location=alert.location,
            latitude=alert.latitude,
            longitude=alert.longitude,
            case_type="数智自动化告警转案件",
            description=AutomationAlertService._build_case_description(alert),
            source_type="技防预警",
        )
        alert.related_case_id = case.id
        alert.status = "converted_to_case"
        alert.handling_result = "已转案件"
        event.related_case_id = case.id
        event.handling_result = "已转案件"
        db.commit()
        CasePreprocessService.preprocess_case(db, case.id)
        db.refresh(alert)
        return {"alert_id": alert.id, "event_id": event.id, "case_id": case.id, "message": "告警已转案件"}

    @staticmethod
    def build_triage_pack(db: Session, alert_id: int) -> Dict[str, Any]:
        """生成数智自动化告警研判包，供人工核查和大模型辅助解释。"""
        alert = AutomationAlertService.get_alert(db, alert_id)
        related_event = (
            db.query(Event).filter(Event.id == alert.related_event_id).first()
            if alert.related_event_id
            else None
        )
        ai_assessment = alert.ai_assessment if isinstance(alert.ai_assessment, dict) else {}
        sensing_summary = alert.sensing_summary if isinstance(alert.sensing_summary, dict) else {}
        parameter_snapshot = alert.parameter_snapshot if isinstance(alert.parameter_snapshot, dict) else {}

        facts = [
            f"告警编号：{alert.alert_number}",
            f"来源系统：{alert.source_system}",
            f"告警类型：{alert.alert_type}",
            f"风险等级：{alert.risk_level}",
            f"发生时间：{alert.occurred_time.isoformat() if alert.occurred_time else '未填写'}",
            f"位置：{alert.location or '未填写'}",
            f"设施：{alert.facility_name or alert.facility_id or '未填写'}",
        ]
        if parameter_snapshot:
            facts.append(f"参数快照：{parameter_snapshot}")
        if sensing_summary:
            facts.append(f"感知摘要：{sensing_summary}")

        information_gaps = []
        if alert.latitude is None or alert.longitude is None:
            information_gaps.append("缺少告警坐标，暂不能直接关联辖区底座和空间热点。")
        if not parameter_snapshot:
            information_gaps.append("缺少生产参数快照，难以复核异常触发依据。")
        if not sensing_summary:
            information_gaps.append("缺少雷达/云台感知摘要，需人工补录现场核查依据。")
        if not ai_assessment:
            information_gaps.append("缺少 AI 研判摘要，只能作为普通告警进入人工核查。")
        if not information_gaps:
            information_gaps.append("核心告警字段较完整，仍需人工核查现场事实。")

        next_steps = []
        if not alert.related_event_id:
            next_steps.append("先生成事件，形成可追踪的核查记录。")
        if alert.status == "pending_review":
            next_steps.append("人工核查参数曲线、雷达目标和云台录像后，再判断误报或转案件。")
        if alert.related_case_id:
            next_steps.append("已转案件，可进入案件研判工作台查看标签、相似条件和复盘报告。")
        else:
            next_steps.append("如人工核查确认异常，再转案件并触发结构化预处理。")
        next_steps.append("如确认设备异常，按误报/设备异常归档，沉淀为阈值优化样本。")

        related_case_context = None
        if alert.related_case_id:
            try:
                related_case_context = CaseIntelligenceService.build_llm_context_pack(
                    db,
                    case_id=alert.related_case_id,
                    days=365,
                    limit=5,
                )
            except Exception:
                related_case_context = None

        return {
            "alert": {
                "id": alert.id,
                "alert_number": alert.alert_number,
                "title": alert.title,
                "status": alert.status,
                "risk_level": alert.risk_level,
                "related_event_id": alert.related_event_id,
                "related_case_id": alert.related_case_id,
            },
            "facts": facts,
            "triage_assessment": {
                "result": ai_assessment.get("result") or "needs_manual_review",
                "confidence": ai_assessment.get("confidence"),
                "basis": ai_assessment.get("basis") or [],
            },
            "information_gaps": information_gaps,
            "recommended_next_steps": next_steps,
            "related_event": {
                "id": related_event.id,
                "event_number": related_event.event_number,
                "handling_result": related_event.handling_result,
            } if related_event else None,
            "related_case_context": related_case_context,
            "boundary": [
                "告警研判包只用于人工核查和模型辅助解释。",
                "不得把告警建议写成已执行任务，不自动派发巡逻任务。",
                "转案件前不生成案件结论；转案件后仍需按案件研判工作台复核。",
            ],
        }

    @staticmethod
    def _build_analysis_notes(alert: AutomationAlert) -> str:
        basis = []
        if isinstance(alert.ai_assessment, dict):
            basis = alert.ai_assessment.get("basis") or []
        return "\n".join(
            item
            for item in (
                f"数智自动化研判：{alert.description or alert.title}",
                f"研判依据：{'；'.join(str(item) for item in basis)}" if basis else None,
                "边界：该记录为技防/生产参数告警，不自动派发巡逻任务，需人工复核。",
            )
            if item
        )

    @staticmethod
    def _build_case_description(alert: AutomationAlert) -> str:
        return "\n".join(
            item
            for item in (
                alert.title,
                alert.description,
                f"设备/设施：{alert.facility_name or alert.facility_id}" if alert.facility_name or alert.facility_id else None,
                f"参数快照：{alert.parameter_snapshot}" if alert.parameter_snapshot else None,
                f"感知摘要：{alert.sensing_summary}" if alert.sensing_summary else None,
                f"AI研判：{alert.ai_assessment}" if alert.ai_assessment else None,
            )
            if item
        )
