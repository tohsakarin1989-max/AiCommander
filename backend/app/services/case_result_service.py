"""只冻结既有分析；读取时重新核对每项证据，不接收用户提供的成果内容。"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_result import CaseResultSnapshot
from app.models.map_foundation import MapSnapshot
from app.services.case_result_access import CaseResultAccessError, require_result_access
from app.services.case_result_snapshot import assemble_case_result


class CaseResultService:
    @staticmethod
    def create_current(db: Session, case_id: int) -> tuple[dict, bool]:
        """显式请求生成兼容入口；调用方负责写权限及事务提交。"""
        if "authorized_area_ids" not in db.info:
            raise CaseResultAccessError()
        profile = db.scalar(select(CaseAnalysisProfile).where(
            CaseAnalysisProfile.case_id == case_id, CaseAnalysisProfile.is_current.is_(True),
        ).order_by(CaseAnalysisProfile.profile_version.desc()).limit(1).execution_options(populate_existing=True))
        if profile is None:
            raise CaseResultAccessError()
        run = db.scalar(select(CaseAnalysisRun).join(MapSnapshot).where(
            CaseAnalysisRun.case_profile_id == profile.id, MapSnapshot.status == "current",
            CaseAnalysisRun.status.in_(("completed", "degraded")),
        ).order_by(CaseAnalysisRun.started_at.desc(), CaseAnalysisRun.id.desc()).limit(1)
            .execution_options(populate_existing=True))
        hypotheses = list(db.scalars(select(CaseHypothesis).where(
            CaseHypothesis.analysis_run_id == run.id,
        ).order_by(CaseHypothesis.rank).execution_options(populate_existing=True))) if run else []
        snapshot = assemble_case_result(profile, run, hypotheses)
        require_result_access(db, snapshot)
        existing = db.scalar(select(CaseResultSnapshot.id).where(
            CaseResultSnapshot.case_id == case_id,
            CaseResultSnapshot.content_sha256 == snapshot["content_sha256"],
        ))
        if existing:
            return CaseResultService.read(db, existing), False
        dialect = db.get_bind().dialect.name
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("unsupported_case_result_database")
        insert = sqlite_insert if dialect == "sqlite" else postgres_insert
        # 原子冲突忽略不破坏外层事务；避免SQLite首次SAVEPOINT释放即提交的问题。
        created_id = db.scalar(insert(CaseResultSnapshot).values(
            id=str(uuid4()), case_id=case_id, case_profile_id=profile.id,
            content_sha256=snapshot["content_sha256"], content=snapshot["content"],
        ).on_conflict_do_nothing(index_elements=["case_id", "content_sha256"])
            .returning(CaseResultSnapshot.id))
        result_id = created_id or db.scalar(select(CaseResultSnapshot.id).where(
            CaseResultSnapshot.case_id == case_id,
            CaseResultSnapshot.content_sha256 == snapshot["content_sha256"],
        ))
        if result_id is None:
            raise CaseResultAccessError()
        return CaseResultService.read(db, result_id), created_id is not None

    @staticmethod
    def read(db: Session, result_id: str) -> dict:
        if "authorized_area_ids" not in db.info:
            raise CaseResultAccessError()
        row = db.execute(select(
            CaseResultSnapshot.id, CaseResultSnapshot.case_id, CaseResultSnapshot.case_profile_id,
            CaseResultSnapshot.content_sha256, CaseResultSnapshot.content, CaseResultSnapshot.created_at,
        ).where(CaseResultSnapshot.id == result_id)).first()
        if row is None:
            raise CaseResultAccessError()
        snapshot = {"content_sha256": row.content_sha256, "content": row.content}
        require_result_access(db, snapshot)
        if row.case_id != row.content["case_id"] or row.case_profile_id != row.content["versions"]["case_profile_id"]:
            raise CaseResultAccessError()
        return {"id": row.id, "created_at": row.created_at, **snapshot}

    @staticmethod
    def history(db: Session, case_id: int, limit: int = 20, offset: int = 0) -> dict:
        if "authorized_area_ids" not in db.info or db.scalar(select(Case.id).where(Case.id == case_id)) is None:
            raise CaseResultAccessError()
        ids = list(db.scalars(select(CaseResultSnapshot.id).where(CaseResultSnapshot.case_id == case_id)
                   .order_by(CaseResultSnapshot.created_at.desc(), CaseResultSnapshot.id.desc())
                   .offset(offset).limit(limit + 1)))
        items = []
        for result_id in ids[:limit]:
            try:
                result = CaseResultService.read(db, result_id)
            except CaseResultAccessError:
                # 仅主案件范围内的历史条目占位，不透露失权引用、内容或版本。
                items.append({"id": result_id, "availability": "unavailable"})
            else:
                items.append({"id": result_id, "availability": "available", "created_at": result["created_at"],
                              "content_sha256": result["content_sha256"], "versions": result["content"]["versions"]})
        return {"items": items, "has_more": len(ids) > limit, "offset": offset, "limit": limit}
