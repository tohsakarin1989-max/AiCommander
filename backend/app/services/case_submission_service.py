"""A request key identifies one creation, never a cached authorization decision."""
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import require_area_write_access
from app.models.case import Case
from app.models.case_submission import CaseSubmissionReceipt
from app.services.case_number_service import ensure_number_transaction
from app.services.case_service import CaseService


class SubmissionIdentityError(PermissionError):
    pass


class SubmissionConflictError(ValueError):
    pass


class SubmissionUnavailableError(LookupError):
    pass


def _identity(db, key):
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key) is None:
        raise ValueError("提交标识须为 1–128 位字母、数字或 . _ : -")
    user_id = db.info.get("principal_user_id")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise SubmissionIdentityError("确认提交结果需要登录")
    return user_id


def _receipt(db, user_id, key):
    # Explicit owner filtering is mandatory: never look up a receipt by key alone.
    return db.scalar(select(CaseSubmissionReceipt).where(
        CaseSubmissionReceipt.user_id == user_id,
        CaseSubmissionReceipt.idempotency_key == key,
    ).execution_options(populate_existing=True))


def _visible_case(db, receipt):
    if receipt is None or receipt.case_id is None:
        return None
    # Do not use Session.get: an already loaded object may predate scope revocation.
    return db.scalar(select(Case).where(Case.id == receipt.case_id)
                     .execution_options(populate_existing=True))


def submission_status(db, key):
    user_id = _identity(db, key)
    case = _visible_case(db, _receipt(db, user_id, key))
    # Unconfirmed includes an in-flight transaction, missing receipt, deleted case
    # or lost access. It is NOT proof that the operation never committed.
    return {"status": "completed" if case is not None else "unconfirmed",
            "case_id": case.id if case is not None else None}


def _claim_receipt(db, user_id, key, digest):
    """Arbitrate only the request-key conflict, without a separate savepoint."""
    insert = {"sqlite": sqlite_insert, "postgresql": postgresql_insert}.get(db.get_bind().dialect.name)
    if insert is None:
        raise ValueError("当前数据库不支持安全的案件提交确认")
    table = CaseSubmissionReceipt.__table__
    # The explicit conflict target must not hide FK/NOT NULL/other failures.
    # A concurrent claim waits for the winner's transaction, just as a unique
    # insert does. No receipt or case is committed by this statement alone.
    statement = insert(table).values(user_id=user_id, idempotency_key=key, request_sha256=digest)
    return db.scalar(statement.on_conflict_do_nothing(
        index_elements=[table.c.user_id, table.c.idempotency_key],
    ).returning(table.c.id))


def create_case_submission(db, *, key, request_payload, values, commit=True):
    """The unique insert arbitrates concurrent retries on PostgreSQL and SQLite."""
    user_id = _identity(db, key)
    digest = hashlib.sha256(json.dumps(request_payload, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    try:
        # Reserve the SQLite writer before the claim; subsequent automatic
        # numbering still uses a savepoint within this actual outer transaction.
        ensure_number_transaction(db)
        receipt_id = _claim_receipt(db, user_id, key, digest)
        if receipt_id is None:
            receipt = _receipt(db, user_id, key)
            if receipt is None:
                raise SubmissionUnavailableError("暂时无法确认提交结果，请保留原提交标识重试")
            if receipt.request_sha256 != digest:
                raise SubmissionConflictError("同一提交标识的内容已变化，请先确认原提交结果")
            case = _visible_case(db, receipt)
            if case is None:
                raise SubmissionUnavailableError("原提交案件不存在或当前无权访问")
            require_area_write_access(db, case.operational_area_id)
            return case
        case = CaseService.create_case(db=db, commit=False, **values)
        table = CaseSubmissionReceipt.__table__
        db.execute(table.update().where(table.c.id == receipt_id, table.c.user_id == user_id)
                   .values(case_id=case.id))
        if commit:
            db.commit()
            db.refresh(case)
            CaseService.finish_created_case(db, case)
        return case
    except Exception:
        db.rollback()
        raise
