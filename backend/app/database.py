import sqlite3

from fastapi import Request
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker, with_loader_criteria
from app.config import settings
from typing import Dict, Any


def _create_engine_from_settings() -> "Engine":
    """
    根据配置创建数据库引擎：
    - 默认使用 SQLite 本地文件（无需 Docker/PostgreSQL）
    - 如设置了 DATABASE_URL（PostgreSQL等），则使用对应配置
    """
    url = settings.DATABASE_URL
    connect_args: Dict[str, Any] = {}

    # SQLite 需要特殊的 connect_args 设置
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    return create_engine(url, connect_args=connect_args)


engine = _create_engine_from_settings()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite 本地与测试环境也必须执行生产库定义的外键语义。"""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


class AreaWriteAccessError(PermissionError):
    """当前请求没有目标厂区的写权限。"""


def require_area_write_access(db: Session, operational_area_id: int | None = None) -> int | None:
    """后台/测试会话不受影响；已认证请求必须具备 write 或 manage。"""
    access_levels = db.info.get("area_access_levels")
    if access_levels is None:
        return operational_area_id or db.info.get("default_operational_area_id")
    area_id = operational_area_id or db.info.get("default_operational_area_id")
    if area_id is None or access_levels.get(area_id) not in {"write", "manage"}:
        raise AreaWriteAccessError("area_write_access_required")
    return area_id


@event.listens_for(Session, "do_orm_execute")
def _apply_operational_area_scope(execute_state) -> None:
    """对来自已认证 API 的 ORM 查询统一施加厂区范围，后台任务不受影响。"""
    if not execute_state.is_select:
        return
    area_ids = execute_state.session.info.get("authorized_area_ids")
    if area_ids is None:
        return
    from app.models.case import Case
    from app.models.deployment_advisor import SituationBrief, TechDefenseEventAggregate, TechDefenseSource
    from app.models.event import AreaProfile, Event
    from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
    from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, MapSource
    from app.models.meeting import Meeting

    scoped_models = (
        Case,
        JurisdictionAsset,
        JurisdictionFeedback,
        MapSource,
        MapSnapshot,
        MapSnapshotFeature,
        TechDefenseSource,
        TechDefenseEventAggregate,
        SituationBrief,
        Meeting,
        Event,
        AreaProfile,
    )
    statement = execute_state.statement
    for model in scoped_models:
        statement = statement.options(
            with_loader_criteria(
                model,
                model.operational_area_id.in_(area_ids),
                include_aliases=True,
            )
        )
    from app.models.case import CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
    from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
    from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState
    from app.models.preprocess_job import PreprocessJob
    from app.models.automation_alert import AutomationAlert
    from app.models.chain_link import ChainLink
    from app.models.conclusion import Conclusion
    from app.models.conclusion_review import ConclusionReview
    from app.models.event import EventRelation
    from app.models.knowledge_asset import KnowledgeAsset, KnowledgeReuseRecord
    from app.models.meeting import AnalysisResult, Evaluation, MeetingConversation, Ranking
    from app.models.report import Report

    allowed_case_ids = select(Case.id).where(Case.operational_area_id.in_(area_ids))
    for model in (
        CaseVehicle,
        CasePerson,
        CaseEvidence,
        OilRecoveryRecord,
        CaseTip,
        PreprocessJob,
        CasePipelineState,
        CaseAnalysisProfile,
        CaseAnalysisRun,
        CaseHypothesis,
        Conclusion,
    ):
        statement = statement.options(
            with_loader_criteria(
                model,
                model.case_id.in_(allowed_case_ids),
                include_aliases=True,
            )
        )
    statement = statement.options(
        with_loader_criteria(
            KnowledgeAsset,
            KnowledgeAsset.source_case_id.in_(allowed_case_ids),
            include_aliases=True,
        ),
        with_loader_criteria(
            KnowledgeReuseRecord,
            KnowledgeReuseRecord.target_case_id.in_(allowed_case_ids),
            include_aliases=True,
        ),
        with_loader_criteria(
            ChainLink,
            ChainLink.case_id_a.in_(allowed_case_ids)
            & ChainLink.case_id_b.in_(allowed_case_ids),
            include_aliases=True,
        ),
    )
    allowed_conclusion_ids = select(Conclusion.id).where(
        Conclusion.case_id.in_(allowed_case_ids)
    )
    allowed_asset_ids = select(JurisdictionAsset.id).where(
        JurisdictionAsset.operational_area_id.in_(area_ids)
    )
    allowed_event_ids = select(Event.id).where(Event.operational_area_id.in_(area_ids))
    allowed_meeting_ids = select(Meeting.meeting_id).where(
        Meeting.operational_area_id.in_(area_ids)
    )
    statement = statement.options(
        with_loader_criteria(
            ConclusionReview,
            ConclusionReview.conclusion_id.in_(allowed_conclusion_ids),
            include_aliases=True,
        ),
        with_loader_criteria(
            AutomationAlert,
            (AutomationAlert.related_case_id.in_(allowed_case_ids))
            | (
                AutomationAlert.related_case_id.is_(None)
                & AutomationAlert.related_event_id.in_(allowed_event_ids)
            ),
            include_aliases=True,
        ),
        with_loader_criteria(
            EventRelation,
            EventRelation.event_a_id.in_(allowed_event_ids)
            & EventRelation.event_b_id.in_(allowed_event_ids),
            include_aliases=True,
        ),
    )
    for model in (MeetingConversation, AnalysisResult, Evaluation, Ranking, Report):
        statement = statement.options(
            with_loader_criteria(
                model,
                model.meeting_id.in_(allowed_meeting_ids),
                include_aliases=True,
            )
        )
    execute_state.statement = statement


def bind_principal_scope(db: Session, principal, *, method: str = "GET") -> None:
    if principal is None:
        return
    from app.models.map_foundation import OperationalArea, UserAreaScope

    default_area_id = db.execute(
        select(OperationalArea.id)
        .where(OperationalArea.status == "active")
        .order_by(OperationalArea.is_default.desc(), OperationalArea.id)
        .limit(1)
    ).scalar_one_or_none()
    if principal.role == "admin":
        db.info["authorized_area_ids"] = None
        db.info["area_access_levels"] = None
        db.info["default_operational_area_id"] = default_area_id
        return
    scope_rows = tuple(
        db.execute(
            select(UserAreaScope.operational_area_id, UserAreaScope.access_level)
            .join(
                OperationalArea,
                OperationalArea.id == UserAreaScope.operational_area_id,
            )
            .where(UserAreaScope.user_id == principal.user_id)
            .where(OperationalArea.status == "active")
            .order_by(UserAreaScope.operational_area_id)
        ).all()
    )
    access_levels = {area_id: access_level for area_id, access_level in scope_rows}
    if method not in {"GET", "HEAD", "OPTIONS"}:
        area_ids = tuple(
            area_id
            for area_id, access_level in scope_rows
            if access_level in {"write", "manage"}
        )
    else:
        area_ids = tuple(area_id for area_id, _ in scope_rows)
    db.info["authorized_area_ids"] = area_ids
    db.info["area_access_levels"] = access_levels
    db.info["default_operational_area_id"] = area_ids[0] if area_ids else None


def _bind_request_scope(db: Session, request: Request | None) -> None:
    if request is None:
        return
    bind_principal_scope(
        db,
        getattr(request.state, "principal", None),
        method=request.method,
    )


def get_db(request: Request = None):
    db = SessionLocal()
    try:
        _bind_request_scope(db, request)
        yield db
    finally:
        db.close()
