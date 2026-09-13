"""日常工作台：只读汇总全部授权案件，不启动分析或生成业务待办。"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, case as sql_case, func, or_, select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState


SCHEMA_VERSION = "daily-workbench-5.0-1"
_WHITESPACE = " \t\r\n\v\f\u3000\u00a0"


def information_gaps(case: Case) -> list[str]:
    """仅提示三个关键缺口；地点文字或合法坐标任一存在即可。"""
    gaps = []
    if not case.occurred_time:
        gaps.append("案发时间")
    coordinates_valid = (
        case.latitude is not None
        and case.longitude is not None
        and math.isfinite(case.latitude)
        and math.isfinite(case.longitude)
        and -90 <= case.latitude <= 90
        and -180 <= case.longitude <= 180
    )
    if not (case.location or "").strip(_WHITESPACE) and not coordinates_valid:
        gaps.append("案发地点或合法坐标")
    if not (case.description or "").strip(_WHITESPACE):
        gaps.append("案情描述")
    return gaps


def _text_present(column):
    # replace works identically in SQLite and PostgreSQL; align with row hints.
    value = func.coalesce(column, "")
    for char in _WHITESPACE:
        value = func.replace(value, char, "")
    return func.length(value) > 0


class DailyWorkbenchService:
    @staticmethod
    def daily(db: Session, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
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
            Case.occurred_time.is_(None),
            ~has_location,
            ~_text_present(Case.description),
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

        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
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
                    "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
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
