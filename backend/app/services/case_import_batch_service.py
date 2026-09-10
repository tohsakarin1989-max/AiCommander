"""Atomic receipts: a batch's cases and replay result commit together."""
import hashlib
import json
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.case_import import CaseImportBatch
from app.services.case_service import CaseService


def acquire_import_batch(db: Session, *, content: bytes, area_id: int | None, table):
    configuration = json.dumps({
        "area_id": area_id, "worksheet": table.worksheet, "header_row": table.header_row,
        # Fixed identity, NOT a software version. Parser/alias changes must never
        # implicitly create the same source rows again after an upgrade.
        "identity_schema": "case-import-v1",
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    input_hash = hashlib.sha256(hashlib.sha256(content).digest() + configuration).hexdigest()

    def existing():
        return db.query(CaseImportBatch).filter(
            CaseImportBatch.input_hash == input_hash,
            CaseImportBatch.operational_area_id == area_id,
        ).one_or_none()

    batch = existing()
    if batch is not None:
        return batch, False
    batch = CaseImportBatch(id=str(uuid4()), input_hash=input_hash, operational_area_id=area_id,
                            created_by=db.info.get("principal_user_id"))
    db.add(batch)
    try:
        # The unique insert serializes identical concurrent imports. Do not commit:
        # a crash must roll back this row AND the cases, not leave an orphan claim.
        db.flush()
    except IntegrityError:
        db.rollback()
        batch = existing()
        if batch is None:
            raise
        return batch, False
    return batch, True


def create_import_case(db: Session, **values):
    # A row failure must not roll back already validated rows in the outer batch.
    with db.begin_nested():
        return CaseService.create_case(db=db, commit=False, **values)
