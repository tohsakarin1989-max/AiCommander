"""Scoped source history and references. Reads never create a revision."""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Response
from hashlib import sha256
from uuid import uuid4
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import get_db, require_area_write_access
from app.api.case_source_schemas import SourceReferenceCreate
from app.models.case_source import CaseLocation, OilMeasurement, CaseRevision, SourceReference, EvidenceObject
from app.services.case_service import CaseService
from app.services.case_pipeline_service import CasePipelineService
from app.models.case import CaseEvidence
from app.utils.datetimes import utc_datetime

router = APIRouter()


def _case(db, case_id, *, write=False):
    case = CaseService.get_case(db, case_id)
    if case is None:
        raise HTTPException(404, "案件不存在")
    if write:
        require_area_write_access(db, case.operational_area_id)
    return case


def _values(row):
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "content"}
    return {key: utc_datetime(value) if isinstance(value, datetime) else value for key, value in values.items()}


@router.get("/{case_id:int}/locations")
def list_locations(case_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    return [_values(row) for row in db.query(CaseLocation).filter_by(case_id=case_id).order_by(CaseLocation.id).all()]


@router.get("/{case_id:int}/measurements")
def list_measurements(case_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    return [_values(row) for row in db.query(OilMeasurement).filter_by(case_id=case_id).order_by(OilMeasurement.id).all()]


@router.get("/{case_id:int}/sources")
def list_sources(case_id: int, limit: int = Query(50, ge=1, le=200), before_revision: int | None = None,
                 db: Session = Depends(get_db)):
    _case(db, case_id)
    query = db.query(CaseRevision).filter_by(case_id=case_id)
    latest = query.order_by(CaseRevision.revision.desc()).first()
    if before_revision is not None:
        query = query.filter(CaseRevision.revision < before_revision)
    rows = query.order_by(CaseRevision.revision.desc()).limit(limit + 1).all()
    references = db.query(SourceReference).filter_by(case_id=case_id).order_by(SourceReference.id.desc()).limit(200).all()
    return {"case_id": case_id, "current_revision_id": latest.id if latest else None,
            "revisions": [{key: value for key, value in _values(row).items() if key != "payload"} for row in rows[:limit]],
            "next_before_revision": rows[limit - 1].revision if len(rows) > limit else None,
            "references": [_values(row) for row in references],
            "references_limit": 200,
            "status": "available" if latest else "not_recorded",
            "boundary": "来源版本从 v6.1 实际写入开始记录；不伪造此前修订历史。"}


@router.get("/{case_id:int}/sources/{revision_id:int}")
def get_revision(case_id: int, revision_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    row = db.query(CaseRevision).filter_by(case_id=case_id, id=revision_id).first()
    if row is None:
        raise HTTPException(404, "来源版本不存在或不可访问")
    return _values(row)


@router.post("/{case_id:int}/source-references", status_code=201)
def create_reference(case_id: int, payload: SourceReferenceCreate, db: Session = Depends(get_db)):
    _case(db, case_id, write=True)
    revision = db.query(CaseRevision).filter_by(case_id=case_id, id=payload.source_revision_id).first()
    if revision is None:
        raise HTTPException(404, "来源版本不存在或不可访问")
    original = revision.payload.get("case", {}).get(payload.field)
    if not isinstance(original, str) or not 0 <= payload.start < payload.end <= len(original):
        raise HTTPException(422, "引用位置必须落在该版本原文内")
    locator = {"field": payload.field, "start": payload.start, "end": payload.end,
               "quote": original[payload.start:payload.end]}
    existing = db.query(SourceReference).filter_by(case_id=case_id, source_revision_id=revision.id, kind="text").all()
    row = next((item for item in existing if item.locator == locator), None)
    if row is None:
        row = SourceReference(case_id=case_id, source_revision_id=revision.id, kind="text", locator=locator)
        db.add(row)
        db.commit()
    return _values(row)


@router.get("/{case_id:int}/source-references/{reference_id:int}")
def get_reference(case_id: int, reference_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    row = db.query(SourceReference).filter_by(case_id=case_id, id=reference_id).first()
    if row is None:
        raise HTTPException(404, "引用不存在或不可访问")
    result = _values(row)
    if row.evidence_object_id is not None:
        evidence = db.get(EvidenceObject, row.evidence_object_id)
        # Storage location is never a user/model-executable path.
        result["evidence"] = ({key: value for key, value in _values(evidence).items() if key != "storage_key"}
                              if evidence else None)
        result["availability"] = evidence.availability if evidence else "unavailable"
    else:
        result["availability"] = "available" if db.query(CaseRevision.id).filter_by(id=row.source_revision_id, case_id=case_id).first() else "unavailable"
    return result


@router.post("/{case_id:int}/source-references/{reference_id:int}/revoke")
def revoke_evidence(case_id: int, reference_id: int, db: Session = Depends(get_db)):
    case = _case(db, case_id, write=True)
    row = db.query(SourceReference).filter_by(case_id=case_id, id=reference_id).first()
    if row is None or row.evidence_object_id is None:
        raise HTTPException(404, "材料引用不存在")
    evidence = db.get(EvidenceObject, row.evidence_object_id)
    if evidence is None:
        raise HTTPException(404, "材料对象不存在")
    evidence.availability = "revoked"
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"evidence"})
    db.commit()
    return {"reference_id": reference_id, "availability": "revoked"}


@router.post("/{case_id:int}/evidence-files", status_code=201)
def upload_evidence(case_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Store a bounded original attachment, never parse documents or execute it."""
    case = _case(db, case_id, write=True)
    content = file.file.read(4 * 1024 * 1024 + 1)
    if not content or len(content) > 4 * 1024 * 1024:
        raise HTTPException(422, "佐证文件须为 1 字节至 4 MiB；大文件请登记材料目录")
    # The filename and client MIME never decide the actual file type.
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type, extension = "image/png", "png"
    elif content.startswith(b"\xff\xd8\xff"):
        media_type, extension = "image/jpeg", "jpg"
    elif content.startswith(b"%PDF-"):
        media_type, extension = "application/pdf", "pdf"
    else:
        raise HTTPException(422, "仅接收 PNG、JPEG、PDF 佐证原件；不处理脚本或主动内容")
    signature = sha256(content).hexdigest()
    # Deduplicate only within the accessible case, never reveal a global hash hit.
    existing = db.query(SourceReference, EvidenceObject).join(
        EvidenceObject, SourceReference.evidence_object_id == EvidenceObject.id
    ).filter(SourceReference.case_id == case_id, EvidenceObject.sha256 == signature,
             EvidenceObject.availability == "available").first()
    if existing:
        return {"reference_id": existing[0].id, "evidence_object_id": existing[1].id,
                "sha256": signature, "availability": "available", "reused": True}
    material = EvidenceObject(storage_key=f"evidence-{uuid4().hex}.{extension}", sha256=signature,
                              media_type=media_type, sensitivity="sensitive", availability="available", content=content)
    db.add(material)
    db.flush()
    title = (file.filename or "佐证原件").replace("\\", "/").split("/")[-1][:200]
    reference = SourceReference(case_id=case_id, evidence_object_id=material.id, kind="evidence", locator={"title": title})
    db.add(reference)
    db.flush()
    entry = CaseEvidence(case_id=case_id, title=title, evidence_type="photo" if extension != "pdf" else "document",
                         is_sensitive=True, evidence_object_id=material.id, source_reference_id=reference.id)
    db.add(entry)
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"evidence"})
    db.commit()
    return {"reference_id": reference.id, "evidence_object_id": material.id, "sha256": signature,
            "availability": "available", "reused": False}


@router.get("/{case_id:int}/source-references/{reference_id:int}/file")
def download_evidence(case_id: int, reference_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    reference = db.query(SourceReference).filter_by(case_id=case_id, id=reference_id).first()
    if reference is None or reference.evidence_object_id is None:
        raise HTTPException(404, "材料不存在或不可访问")
    material = db.get(EvidenceObject, reference.evidence_object_id)
    if material is None or material.availability != "available":
        raise HTTPException(409, "材料未入库或已撤销，不能下载")
    if material.content is None or sha256(material.content).hexdigest() != material.sha256:
        raise HTTPException(409, "材料内容校验失败")
    return Response(material.content, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="evidence-{material.id}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        "Content-Security-Policy": "sandbox",
    })
