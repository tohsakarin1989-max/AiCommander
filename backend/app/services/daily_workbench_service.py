"""日常工作台：只读汇总全部授权案件，不启动分析或生成业务待办。"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState
from app.services.case_time_window import case_time_fields
from app.utils.datetimes import utc_datetime


SCHEMA_VERSION = "daily-workbench-9.0-1"
_WHITESPACE = " \t\r\n\v\f\u3000\u00a0"


def information_gaps(case: Case) -> list[str]:
    """仅提示三个关键缺口；地点文字或合法坐标任一存在即可。"""
    gaps = []
    coordinates_valid = (
        case.latitude is not None
        and case.longitude is not None
        and math.isfinite(case.latitude)
        and math.isfinite(case.longitude)
        and -90 <= case.latitude <= 90
        and -180 <= case.longitude <= 180
    )
    if not (case.location or "").strip(_WHITESPACE) and not coordinates_valid:
        gaps.append("地点原文或已核对坐标")
    if not (case.description or "").strip(_WHITESPACE):
        gaps.append("案情描述")
    # Unknown is not a missing employee task; an explicitly entered but
    # contradictory interval still requires correction (including legacy data).
    if case.time_precision == "interval" and (
        case.occurred_from is None or case.occurred_to is None
        or case.occurred_time is not None
        or utc_datetime(case.occurred_to) < utc_datetime(case.occurred_from)
    ):
        gaps.append("案发时间")
    return gaps


def _text_present(column):
    # replace works identically in SQLite and PostgreSQL; align with row hints.
    value = func.coalesce(column, "")
    for char in _WHITESPACE:
        value = func.replace(value, char, "")
    return func.length(value) > 0


class DailyWorkbenchService:
    @staticmethod
    def daily(db: Session, *, limit: int = 20, offset: int = 0,
              user_id: int | None = None, role: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid_workbench_pagination")

        coordinates_valid = and_(
            Case.latitude.between(-90, 90),
            Case.longitude.between(-180, 180),
        )
        has_location = or_(
            _text_present(Case.location), func.coalesce(coordinates_valid, False)
        )
        needs_information = or_(
            ~has_location,
            ~_text_present(Case.description),
            and_(Case.time_precision == "interval", or_(
                Case.occurred_from.is_(None), Case.occurred_to.is_(None),
                Case.occurred_time.is_not(None), Case.occurred_to < Case.occurred_from,
            )),
        )
        current_profile = (
            select(CaseAnalysisProfile.id)
            .where(
                CaseAnalysisProfile.case_id == Case.id,
                CaseAnalysisProfile.is_current.is_(True),
                CaseAnalysisProfile.source_hash == CasePipelineState.source_hash,
                CaseAnalysisProfile.schema_version == CasePipelineState.schema_version,
                CaseAnalysisProfile.dictionary_version == CasePipelineState.dictionary_version,
            )
            .correlate(Case, CasePipelineState)
            .exists()
        )
        analysis_ready = and_(
            CasePipelineState.status == "completed", current_profile
        )

        # ORM expressions retain the request's mandatory operational-area scope.
        # Reading the workbench must not flush unrelated pending session changes.
        with db.no_autoflush:
            totals = (
                db.query(
                    func.count(Case.id).label("total_cases"),
                    func.coalesce(func.sum(sql_case((needs_information, 1), else_=0)), 0)
                    .label("needs_information"),
                    func.coalesce(func.sum(sql_case((analysis_ready, 1), else_=0)), 0)
                    .label("analysis_ready"),
                )
                .select_from(Case)
                .outerjoin(CasePipelineState, CasePipelineState.case_id == Case.id)
                .one()
            )
            rows = (
                db.query(
                    Case,
                    CasePipelineState.status.label("pipeline_status"),
                    analysis_ready.label("profile_ready"),
                )
                .outerjoin(CasePipelineState, CasePipelineState.case_id == Case.id)
                .order_by(Case.created_at.desc(), Case.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            resume = _personal_resume(db, user_id=user_id, role=role)

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "changes": _topic_changes(db),
            "resume": resume,
            "material_entry": {"target_path": "/reports", "label": "取已有材料"},
            "summary": {
                "total_cases": totals.total_cases,
                "needs_information": totals.needs_information,
                "analysis_pending": totals.total_cases - totals.analysis_ready,
                "analysis_ready": totals.analysis_ready,
            },
            "cases": [
                {
                    "id": case.id,
                    "case_number": case.case_number,
                    **case_time_fields(case),
                    "discovered_at": utc_datetime(case.discovered_at).isoformat() if case.discovered_at else None,
                    "registered_at": utc_datetime(case.created_at).isoformat() if case.created_at else None,
                    "location": case.location,
                    "case_status": case.status,
                    "pipeline_status": pipeline_status or "not_started",
                    "profile_ready": bool(profile_ready),
                    "information_gaps": information_gaps(case),
                    "target_path": f"/cases?caseId={case.id}",
                }
                for case, pipeline_status, profile_ready in rows
            ],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(rows),
                "total": totals.total_cases,
            },
        }


def _topic_changes(db):
    from app.services.topic_notifications import daily_changes
    return daily_changes(db)


def _personal_resume(db: Session, *, user_id: int | None, role: str | None) -> dict[str, Any]:
    """Owner-only continuation counts, without draft content or other employees' workload."""
    from app.models.case_draft import CaseDraft
    from app.models.case_import import CaseImportBatch, CaseImportRow
    from app.models.user import User
    from app.services.case_draft_service import _query as authorized_drafts

    if role == "viewer":
        return {"state": "not_applicable"}
    levels = db.info.get("area_access_levels")
    if (not isinstance(user_id, int) or isinstance(user_id, bool)
            or user_id != db.info.get("principal_user_id")
            or role not in {"admin", "analyst"} or 'area_access_levels' not in db.info
            or not (isinstance(levels, dict) or role == 'admin' and levels is None)):
        return {"state": "unavailable"}
    active = db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True),
                                             User.role == role))
    if active is None:
        return {"state": "unavailable"}
    drafts = authorized_drafts(db).filter(CaseDraft.status == "active").count()
    failed_rows = select(CaseImportRow.id).where(
        CaseImportRow.batch_id == CaseImportBatch.id, CaseImportRow.status.in_(("failed", "conflict")),
    ).correlate(CaseImportBatch).exists()
    imports_query = db.query(CaseImportBatch).filter(CaseImportBatch.created_by == user_id, failed_rows)
    if levels is not None:
        writable_areas = [area_id for area_id, access in levels.items() if access in {"write", "manage"}]
        imports_query = imports_query.filter(CaseImportBatch.operational_area_id.in_(writable_areas))
    imports = imports_query.count()
    return {"state": "ready", "drafts": {"total": drafts, "target_path": "/cases?drafts=1"},
            "imports": {"total": imports, "target_path": "/cases?imports=1"}}
