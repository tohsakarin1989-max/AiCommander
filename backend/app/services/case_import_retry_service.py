"""Manually correct failed import rows without replaying successful case writes."""
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.database import require_area_write_access
from app.models.case_import import CaseImportBatch, CaseImportRow
from app.services.case_import_batch_service import create_import_case
from app.services.case_import_table import FIELDS, MAX_ROWS
from app.services.case_import_values import normalize_case_row, allocation_order
from app.services.case_service import CaseService
from app.services.map_foundation_service import MAX_CELL_TEXT_LENGTH
from app.utils.datetimes import utc_datetime

logger = logging.getLogger(__name__)


def list_import_batches(
    db: Session, *, page: int = 1, page_size: int = 20,
    operational_area_id: int | None = None,
) -> dict[str, Any]:
    """List authorized receipts, without replaying work or returning source text.

    The ORM scope applies before both count and pagination. Row status is the
    authority after corrections; older receipts without rows remain readable but
    must not promise a retry or pretend that duplicates were measured per row.
    """
    if not 1 <= page <= 10000 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="分页范围无效")
    query = db.query(CaseImportBatch)
    if operational_area_id is not None:
        query = query.filter(CaseImportBatch.operational_area_id == operational_area_id)
    total = query.count()
    batches = query.order_by(CaseImportBatch.created_at.desc(), CaseImportBatch.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    counts: dict[str, dict[str, int]] = {}
    if batches:
        for batch_id, status, count in db.query(
            CaseImportRow.batch_id, CaseImportRow.status, func.count(CaseImportRow.id),
        ).filter(CaseImportRow.batch_id.in_([batch.id for batch in batches])).group_by(
            CaseImportRow.batch_id, CaseImportRow.status,
        ).all():
            counts.setdefault(batch_id, {})[status] = count
    levels = db.info.get("area_access_levels")
    items = []
    for batch in batches:
        statuses = counts.get(batch.id, {})
        receipt = batch.result or {}
        table = receipt.get("table") or {}
        row_total = sum(statuses.values())
        success = statuses.get("created", 0) if statuses else receipt.get("created")
        failed = statuses.get("failed", 0) if statuses else (
            len(receipt["errors"]) if isinstance(receipt.get("errors"), list) else None
        )
        can_write = levels is None or levels.get(batch.operational_area_id) in {"write", "manage"}
        source_mode = bool(receipt.get('source_key'))
        updated, unchanged, conflicts = (statuses.get(name, 0) for name in ('updated', 'unchanged', 'conflict'))
        items.append({
            "batch_id": batch.id, "created_at": utc_datetime(batch.created_at),
            "operational_area_id": batch.operational_area_id,
            "total": row_total if statuses else receipt.get("total"),
            "success": success, "failed": failed, "duplicate": None,
            "created": success, "updated": updated, "unchanged": unchanged, "conflict": conflicts,
            "state": ("partial" if failed or conflicts else "completed") if statuses else "legacy_receipt",
            "retry_available": bool(statuses and failed and can_write and not source_mode),
            "source_key": receipt.get('source_key'), "source_revision": receipt.get('source_revision'),
            "next_action": '保留稳定源键，回原来源修正后重新预览导入；不可使用首次建案重试' if source_mode else None,
            "worksheet": table.get("worksheet"), "time_zone": table.get("time_zone"),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _get_batch(db: Session, batch_id: str) -> CaseImportBatch:
    batch = db.query(CaseImportBatch).filter(CaseImportBatch.id == batch_id).one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="导入批次不存在或无权访问")
    return batch


def _row_result(row: CaseImportRow) -> dict[str, Any]:
    from app.services.case_security_ledger import source_row_preview
    return {"row": row.row_number, "revision": row.revision, "status": row.status,
            "case_id": row.case_id, "error": row.error, "values": row.current_values,
            "time_zone": row.time_zone, **source_row_preview(row.source_values.get('_import_provenance'))}


def get_batch_rows(db: Session, batch_id: str) -> dict[str, Any]:
    batch = _get_batch(db, batch_id)
    rows = db.query(CaseImportRow).filter(CaseImportRow.batch_id == batch.id).order_by(CaseImportRow.row_number).all()
    receipt = batch.result or {}
    source_mode = bool(receipt.get('source_key'))
    levels = db.info.get('area_access_levels')
    can_write = levels is None or levels.get(batch.operational_area_id) in {'write', 'manage'}
    return {"batch_id": batch.id, "retry_available": bool(not source_mode and can_write and any(row.status == 'failed' for row in rows)),
            "created_total": sum(row.status == "created" for row in rows),
            "updated_total": sum(row.status == 'updated' for row in rows),
            "unchanged_total": sum(row.status == 'unchanged' for row in rows),
            "conflict_total": sum(row.status == 'conflict' for row in rows),
            "failed_total": sum(row.status == 'failed' for row in rows),
            "source_key": receipt.get('source_key'), "source_revision": receipt.get('source_revision'),
            "next_action": '保留稳定源键，回原来源修正后重新预览导入；不可使用首次建案重试' if source_mode else None,
            "rows": [_row_result(row) for row in rows if source_mode or row.status == "failed"]}


def _validate_changes(requests: Any) -> None:
    if not isinstance(requests, list) or not 1 <= len(requests) <= MAX_ROWS:
        raise HTTPException(status_code=422, detail="一次修正须包含 1—1000 行")
    numbers = set()
    for item in requests:
        if not isinstance(item, dict) or set(item) != {"row", "revision", "changes"}:
            raise HTTPException(status_code=422, detail="修正请求格式无效")
        if type(item["row"]) is not int or item["row"] < 1 or type(item["revision"]) is not int or item["revision"] < 0:
            raise HTTPException(status_code=422, detail="行号和版本必须为有效整数")
        if item["row"] in numbers:
            raise HTTPException(status_code=422, detail="同一行不能在一次请求中重复出现")
        numbers.add(item["row"])
        changes = item["changes"]
        if not isinstance(changes, dict) or not changes or set(changes) - FIELDS:
            raise HTTPException(status_code=422, detail="只能修正允许的案件导入字段")
        if any(value is not None and (not isinstance(value, (str, int, float, bool)) or len(str(value)) > MAX_CELL_TEXT_LENGTH)
               for value in changes.values()):
            raise HTTPException(status_code=422, detail="修正内容必须为有界单元格值")


def retry_batch_rows(db: Session, batch_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Own the request transaction, including lock-time validation failures."""
    try:
        return _retry_batch_rows(db, batch_id, requests)
    except Exception:
        db.rollback()
        raise


def _retry_batch_rows(db: Session, batch_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    _validate_changes(requests)
    batch = _get_batch(db, batch_id)
    require_area_write_access(db, batch.operational_area_id)
    if (batch.result or {}).get('source_key'):
        raise HTTPException(status_code=409, detail='持续来源批次须保留源键重新预览导入，不可走首次建案重试')
    # Serialize corrections of the same batch, including DIFFERENT rows: row CAS
    # alone cannot prevent lost updates of the shared aggregate receipt on PG.
    db.execute(update(CaseImportBatch).where(
        CaseImportBatch.id == batch.id,
        CaseImportBatch.operational_area_id == batch.operational_area_id,
    ).values(input_hash=CaseImportBatch.input_hash).execution_options(synchronize_session=False))
    db.refresh(batch)
    records = {row.row_number: row for row in db.query(CaseImportRow).filter(
        CaseImportRow.batch_id == batch.id,
        CaseImportRow.row_number.in_([item["row"] for item in requests]),
    ).populate_existing().all()}
    if len(records) != len(requests):
        raise HTTPException(status_code=404, detail="原始行记录不存在；旧批次可能不支持逐行重试")
    # Validate all expected revisions before any write; successful original rows
    # are never a route for editing a formal case.
    for item in requests:
        row = records[item["row"]]
        changes = {key: None if value is None else str(value) for key, value in item["changes"].items()}
        replay = (row.status == "created" and row.revision == item["revision"] + 1
                  and row.corrections and row.corrections[-1]["changes"] == changes)
        if not replay and (row.status != "failed" or row.revision != item["revision"]):
            raise HTTPException(status_code=409, detail="该行已成功或版本已变化，请刷新回执")
        if row.revision >= 100:
            raise HTTPException(status_code=409, detail="该行修正次数过多，请由管理员核验来源")

    created_cases = []
    ordered_requests = sorted(requests, key=lambda item: allocation_order(
        {**records[item["row"]].current_values, **item["changes"]}, records[item["row"]].time_zone, item["row"],
    ))
    try:
        for item in ordered_requests:
            row = records[item["row"]]
            if row.status == "created":
                continue
            changed = db.execute(update(CaseImportRow).where(
                CaseImportRow.id == row.id,
                CaseImportRow.operational_area_id == batch.operational_area_id,
                CaseImportRow.status == "failed",
                CaseImportRow.revision == item["revision"],
            ).values(revision=item["revision"] + 1).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise HTTPException(status_code=409, detail="其他请求已处理该行，请刷新回执")
            changes = {key: None if value is None else str(value) for key, value in item["changes"].items()}
            row.revision = item["revision"] + 1
            row.current_values = {**row.current_values, **changes}
            try:
                values = normalize_case_row(row.current_values, time_zone=row.time_zone)
                case = create_import_case(db=db, case_number=None, operational_area_id=batch.operational_area_id, **values)
                row.status, row.case_id, row.error = "created", case.id, None
                created_cases.append(case)
            except Exception as exc:
                row.status = "failed"
                row.error = str(exc) if isinstance(exc, ValueError) else "该行写入失败，请核验字段或联系管理员"
            row.corrections = [*row.corrections, {
                "revision": row.revision, "changes": changes, "outcome": row.status, "error": row.error,
                "actor_id": db.info.get("principal_user_id"), "at": datetime.now(timezone.utc).isoformat(),
            }]
        db.flush()
        all_rows = db.query(CaseImportRow).filter(CaseImportRow.batch_id == batch.id).populate_existing().all()
        created_total = sum(row.status == "created" for row in all_rows)
        batch.result = {**(batch.result or {}), "created": created_total,
                        "valid": max((batch.result or {}).get("valid", 0), created_total),
                        "errors": [{"row": row.row_number, "error": row.error} for row in all_rows if row.status == "failed"]}
        response = {"batch_id": batch.id, "created": len(created_cases), "batch_created_total": created_total,
                    "rows": [_row_result(records[item["row"]]) for item in requests],
                    "errors": batch.result["errors"]}
        from app.services.case_import_original import attach_received_rows
        attach_received_rows(db, batch)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for case in created_cases:
        try:
            CaseService.finish_created_case(db, case)
        except Exception:
            db.rollback()
            logger.warning("失败行已导入，派生索引更新失败；案件和回执已保留")
    return response
