"""Bounded ledger originals in the existing evidence store, never executable files.

The caller owns the import transaction. Originals are not deduplicated across
sources, and a download must pass the current source authorization first.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.case_source import EvidenceObject
from app.models.map_foundation import MapFeatureClaim, MapIngestRun, MapSource


MAX_ORIGINAL_BYTES = 10 * 1024 * 1024


def safe_filename(value: str) -> str:
    name = str(value).replace("\\", "/").split("/")[-1]
    return "".join(char for char in name if ord(char) >= 32 and ord(char) != 127)[:200] or "生产台账"


def capture_original(db: Session, run: MapIngestRun, *, content: bytes, filename: str) -> None:
    """Capture already parsed input atomically with its import; no commit here."""
    if not content or len(content) > MAX_ORIGINAL_BYTES:
        raise ValueError("original_size_invalid|台账原件须为 1 字节至 10 MiB")
    signature = sha256(content).hexdigest()
    if signature != run.file_hash:
        raise ValueError("original_hash_mismatch|台账原件与导入摘要不一致")
    if run.original_evidence_object_id is not None:
        existing = db.get(EvidenceObject, run.original_evidence_object_id)
        if (existing is None or existing.availability != "available"
                or existing.sha256 != signature or existing.content != content):
            raise ValueError("original_changed|原始台账记录不可替换")
        return
    original = EvidenceObject(
        storage_key=f"map-ledger-{uuid4().hex}", sha256=signature,
        media_type="application/octet-stream", sensitivity="sensitive",
        captured_at=datetime.now(timezone.utc), availability="available", content=content,
    )
    db.add(original)
    db.flush()
    run.original_evidence_object_id = original.id
    # The stored original is arbitrary source material; no parsing, execution,
    # inferred authority, public URL or filesystem path is exposed here.


def authorized_run(db: Session, run_id: str) -> MapIngestRun:
    value = db.query(MapIngestRun).join(MapSource, MapSource.id == MapIngestRun.source_id).filter(
        MapIngestRun.id == run_id, MapSource.status == "active",
    ).first()
    if value is None:
        raise LookupError("map_original_not_found")
    return value


def original_metadata(db: Session, run: MapIngestRun) -> dict:
    """No binary load or access grant; callers authorize the source/asset first."""
    material = (db.query(EvidenceObject.id, EvidenceObject.availability, EvidenceObject.sha256)
                .filter(EvidenceObject.id == run.original_evidence_object_id).first())
    state = "metadata_only" if material is None else material.availability
    return {"state": state, "filename": safe_filename(run.filename), "sha256": run.file_hash,
            "download_access": "map_administrator", "run_id": run.id}


def read_original(db: Session, run_id: str) -> tuple[bytes, str]:
    run = authorized_run(db, run_id)
    material = db.get(EvidenceObject, run.original_evidence_object_id) if run.original_evidence_object_id else None
    if material is None or material.availability != "available":
        raise ValueError("original_unavailable")
    content = material.content
    if (not content or len(content) > MAX_ORIGINAL_BYTES
            or sha256(content).hexdigest() != material.sha256):
        raise ValueError("original_integrity_failed")
    # Corrected runs may point to the parent's bytes. They must retain the
    # original hash, rather than pretend edited cells are a new source file.
    if material.sha256 != run.file_hash:
        raise ValueError("original_integrity_failed")
    return bytes(content), safe_filename(run.filename)


def claim_provenance(db: Session, claim: MapFeatureClaim) -> dict:
    """A claim's immutable column locations, not current template guesses."""
    run = authorized_run(db, claim.run_id)
    if run.source_id != claim.source_id:
        raise LookupError("map_original_not_found")
    metadata = run.table_metadata if isinstance(run.table_metadata, dict) else {}
    snapshot = run.template_snapshot if isinstance(run.template_snapshot, dict) else {}
    mapping = snapshot.get("field_mapping") if isinstance(snapshot.get("field_mapping"), dict) else {}
    headers = metadata.get("headers") if isinstance(metadata.get("headers"), list) else []
    columns = []
    for field, column in mapping.items():
        if column not in headers:
            continue
        position = headers.index(column) + 1
        cell = None
        if metadata.get("sheet_name"):
            from openpyxl.utils.cell import get_column_letter
            cell = f"{get_column_letter(position)}{claim.row_number}"
        columns.append({"field": field, "column": column, "column_number": position, "cell": cell})
    return {"original": original_metadata(db, run), "sheet_name": metadata.get("sheet_name"),
            "header_row": metadata.get("header_row"), "row_number": claim.row_number,
            "columns": columns, "parent_claim_id": claim.parent_claim_id,
            "correction_note": claim.correction_note,
            "locator_state": "recorded" if headers and mapping else "legacy_unrecorded"}
