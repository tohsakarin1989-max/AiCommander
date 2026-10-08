"""Owner-only snapshots and atomic conversion; no extraction or analysis on save."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import settings
from app.database import require_area_write_access
from app.models.case import Case
from app.models.case_draft import CaseDraft
from app.models.map_foundation import OperationalArea
from app.models.user import User
from app.services.case_edit_service import update_case_checked
from app.services.case_number_service import ensure_number_transaction
from app.services.case_service import CaseService
from app.services.case_submission_service import create_case_submission


class DraftUnavailable(LookupError):
    pass


class DraftIdentityError(PermissionError):
    pass


class DraftConflict(ValueError):
    def __init__(self, message, current_revision=None):
        super().__init__(message)
        self.current_revision = current_revision


def now_utc():
    return datetime.now(timezone.utc)


def _owner(db):
    value = db.info.get("principal_user_id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DraftIdentityError("私有草稿需要登录")
    return value


def _encode(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > 262144:
        raise ValueError("草稿内容超过 256 KiB，请移除大文件或过长内容")
    return encoded


def _digest(value):
    return hashlib.sha256(_encode(value).encode()).hexdigest()


def _query(db, *, at=None, include_references=True):
    query = db.query(CaseDraft).join(OperationalArea, OperationalArea.id == CaseDraft.operational_area_id).join(
        User, User.id == CaseDraft.owner_id).filter(
        CaseDraft.owner_id == _owner(db), CaseDraft.expires_at > (at or now_utc()),
        OperationalArea.status == "active", User.is_active.is_(True), User.role.in_(("admin", "analyst")))
    levels = db.info.get("area_access_levels")
    if levels is not None:
        query = query.filter(CaseDraft.operational_area_id.in_(
            [area_id for area_id, access in levels.items() if access in {"write", "manage"}]))
    if not include_references:
        return query
    # A moved/deleted target cannot be used to reveal its old private snapshot.
    def still_visible(column):
        return exists(select(Case.id).where(Case.id == column,
            Case.operational_area_id == CaseDraft.operational_area_id))
    return query.filter(or_(CaseDraft.mode == "create", still_visible(CaseDraft.target_case_id))).filter(
        or_(CaseDraft.status == "active", still_visible(CaseDraft.submitted_case_id)))


def get_draft(db, draft_id, *, lock=False):
    query = _query(db, include_references=not lock).filter(CaseDraft.id == draft_id).populate_existing()
    if lock:
        query = query.with_for_update(of=CaseDraft)
    row = query.first()
    if row is not None and lock:
        # PostgreSQL may wait here for a submitting writer. EvalPlanQual sees
        # its updated draft but a same-statement EXISTS cannot see the new Case.
        # Keep the draft lock, then recheck all reference/ACL/expiry predicates
        # with a fresh statement snapshot; never treat the receipt as authority.
        row = _query(db).filter(CaseDraft.id == draft_id).populate_existing().first()
    if row is None:
        raise DraftUnavailable("草稿不存在、已过期或当前无权访问")
    return row


def list_drafts(db, *, page=1, page_size=20, status="active"):
    query = _query(db)
    if status != "all":
        query = query.filter(CaseDraft.status == status)
    total = query.count()
    rows = query.order_by(CaseDraft.updated_at.desc(), CaseDraft.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def _validate_area(db, area_id):
    area_id = require_area_write_access(db, area_id)
    if area_id is None or db.scalar(select(OperationalArea.id).where(
        OperationalArea.id == area_id, OperationalArea.status == "active")) is None:
        raise ValueError("请选择当前可写的有效厂区")
    return area_id


def save_draft(db, draft_id, *, expected_revision, operational_area_id, form_snapshot,
               schema_version=1, target_case_id=None, base_case_revision=None):
    owner_id = _owner(db)
    signature = _digest({"expected_revision": expected_revision, "operational_area_id": operational_area_id,
        "target_case_id": target_case_id, "base_case_revision": base_case_revision,
        "schema_version": schema_version, "form_snapshot": form_snapshot})
    try:
        ensure_number_transaction(db)
        area_id = _validate_area(db, operational_area_id)
        if target_case_id is not None:
            if base_case_revision is None:
                raise ValueError("编辑草稿需要来源版本")
            case = db.scalar(select(Case).where(Case.id == target_case_id).execution_options(populate_existing=True))
            if case is None or case.operational_area_id != area_id:
                raise DraftUnavailable("草稿目标不在所选厂区")
        elif base_case_revision is not None:
            raise ValueError("新增草稿不能指定案件来源版本")
        try:
            row = get_draft(db, draft_id, lock=True)
        except DraftUnavailable:
            row = None
        if row is None:
            if expected_revision != 0:
                raise DraftUnavailable("草稿不存在、已过期或当前无权访问")
            now = now_utc()
            table = CaseDraft.__table__
            insert = {"sqlite": sqlite_insert, "postgresql": postgresql_insert}[db.get_bind().dialect.name]
            values = dict(id=draft_id, owner_id=owner_id, operational_area_id=area_id,
                mode="edit" if target_case_id is not None else "create", target_case_id=target_case_id,
                base_case_revision=base_case_revision, schema_version=schema_version,
                revision=1, status="active", form_snapshot=form_snapshot, last_save_sha256=signature,
                submission_key=f"draft-{draft_id}", created_at=now, updated_at=now,
                expires_at=now + timedelta(days=settings.CASE_DRAFT_RETENTION_DAYS))
            inserted = db.scalar(insert(table).values(**values).on_conflict_do_nothing(
                index_elements=[table.c.id]).returning(table.c.id))
            row = get_draft(db, draft_id, lock=True)
            if inserted is not None:
                db.commit()
                db.refresh(row)
                return row
        if row.status != "active":
            raise DraftConflict("草稿已经正式提交，请查看对应案件", row.revision)
        if row.revision == expected_revision + 1 and row.last_save_sha256 == signature:
            # Lost responses reuse exactly the saved revision, not a new write.
            return row
        if row.revision != expected_revision:
            raise DraftConflict("草稿已在其他页面更新，请保留当前输入并重新读取", row.revision)
        if row.target_case_id != target_case_id or row.operational_area_id != area_id:
            raise ValueError("草稿的案件和厂区不可更换，请另存为新的草稿")
        row.form_snapshot = form_snapshot
        row.schema_version = schema_version
        row.base_case_revision = base_case_revision
        row.revision += 1
        row.last_save_sha256 = signature
        row.updated_at = now_utc()
        row.expires_at = row.updated_at + timedelta(days=settings.CASE_DRAFT_RETENTION_DAYS)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def delete_draft(db, draft_id, *, expected_revision):
    try:
        ensure_number_transaction(db)
        row = get_draft(db, draft_id, lock=True)
        if row.revision != expected_revision:
            raise DraftConflict("草稿已更新，未删除较新的内容", row.revision)
        db.delete(row)
        db.commit()
    except Exception:
        db.rollback()
        raise


def submit_draft(db, draft_id, *, expected_revision, request_payload, values,
                 idempotency_key=None, confirm_only=False):
    signature = _digest({"expected_revision": expected_revision, "case_payload": request_payload})
    try:
        ensure_number_transaction(db)
        row = get_draft(db, draft_id, lock=True)
        if idempotency_key is not None and idempotency_key != row.submission_key:
            raise DraftConflict("请使用草稿原有的提交标识", row.revision)
        if row.status == "submitted":
            if row.submission_sha256 != signature:
                raise DraftConflict("草稿已提交，重试内容不一致", row.revision)
            return row
        if confirm_only:
            raise DraftConflict("尚未确认原提交成功；草稿保持不变，请保留当前输入", row.revision)
        if row.revision != expected_revision:
            raise DraftConflict("草稿已更新，请重新核对提交内容", row.revision)
        if row.mode == "create":
            area_id = values.get("operational_area_id") or row.operational_area_id
            if area_id != row.operational_area_id:
                raise ValueError("正式提交厂区与草稿不一致")
            values = {**values, "operational_area_id": area_id}
            values.setdefault("case_number", None)
            values.setdefault("occurred_time", None)
            case = create_case_submission(db, key=row.submission_key, request_payload=request_payload,
                                          values=values, commit=False)
        else:
            case = update_case_checked(db, row.target_case_id, values,
                                       expected_revision=row.base_case_revision, commit=False)
        if case.operational_area_id != row.operational_area_id:
            # A legacy request might have already used this key with a different
            # default area; a receipt never permits crossing the draft's scope.
            raise DraftConflict("提交对应案件的厂区已变化，请保留草稿并核对原提交", row.revision)
        row.status, row.submitted_case_id = "submitted", case.id
        row.submission_sha256 = signature
        row.form_snapshot = {}
        row.revision += 1
        row.updated_at = now_utc()
        row.expires_at = row.updated_at + timedelta(days=settings.CASE_DRAFT_RETENTION_DAYS)
        db.commit()
        if row.mode == "create":
            CaseService.finish_created_case(db, case)
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def purge_expired_case_drafts(db, *, at=None):
    """Explicit maintenance only; normal reads never write or delete."""
    result = db.execute(delete(CaseDraft).where(CaseDraft.expires_at <= (at or now_utc())))
    db.commit()
    return result.rowcount
