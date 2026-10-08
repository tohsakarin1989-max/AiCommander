"""Explicit private draft writes; all reads are owner/scope/expiry filtered."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.api.cases import CaseCreate, CaseUpdate
from app.database import AreaWriteAccessError, get_db
from app.services.case_draft_service import (
    DraftConflict, DraftIdentityError, DraftUnavailable, delete_draft, get_draft,
    list_drafts, save_draft, submit_draft,
)
from app.services.case_edit_service import CaseEditConflict, CaseEditUnavailable
from app.services.case_submission_service import SubmissionConflictError, SubmissionUnavailableError
from app.utils.datetimes import utc_datetime


router = APIRouter()


class DraftSaveRequest(BaseModel):
    expected_revision: int = Field(ge=0, strict=True)
    operational_area_id: int = Field(gt=0)
    target_case_id: int | None = Field(default=None, gt=0)
    base_case_revision: int | None = Field(default=None, ge=0, strict=True)
    schema_version: Literal[1] = 1
    form_snapshot: dict[str, Any]


class DraftResponse(BaseModel):
    id: str
    revision: int
    status: Literal["active", "submitted"]
    operational_area_id: int
    target_case_id: int | None
    base_case_revision: int | None
    schema_version: int
    form_snapshot: dict[str, Any]
    submission_key: str
    submitted_case_id: int | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("created_at", "updated_at", "expires_at")
    @classmethod
    def explicit_utc(cls, value):
        return utc_datetime(value)


class DraftPage(BaseModel):
    items: list[DraftResponse]
    total: int
    page: int
    page_size: int


class DraftSubmitRequest(BaseModel):
    expected_revision: int = Field(ge=1, strict=True)
    case_payload: dict[str, Any]
    confirm_only: bool = Field(default=False, strict=True)


def _raise(exc):
    def reject(status, detail):
        raise HTTPException(status, detail=detail, headers={"Cache-Control": "no-store"}) from exc

    if isinstance(exc, (DraftUnavailable, CaseEditUnavailable, SubmissionUnavailableError)):
        reject(404, str(exc))
    if isinstance(exc, DraftIdentityError):
        reject(401, str(exc))
    if isinstance(exc, AreaWriteAccessError):
        reject(403, str(exc))
    if isinstance(exc, CaseEditConflict):
        reject(409, {"code": "case_revision_conflict", "message": str(exc),
                     "current_revision": exc.current_revision})
    if isinstance(exc, DraftConflict):
        reject(409, {"code": "draft_revision_conflict", "message": str(exc),
                     "current_revision": exc.current_revision})
    if isinstance(exc, SubmissionConflictError):
        reject(409, {"code": "submission_conflict", "message": str(exc)})
    if isinstance(exc, ValidationError):
        reject(422, exc.errors(include_context=False))
    if isinstance(exc, ValueError):
        reject(422, str(exc))
    raise exc


@router.get("", response_model=DraftPage)
def get_drafts(response: Response, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               status: Literal["active", "submitted", "all"] = "active", db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return list_drafts(db, page=page, page_size=page_size, status=status)
    except (ValueError, PermissionError, LookupError) as exc:
        _raise(exc)


@router.get("/{draft_id}", response_model=DraftResponse)
def read_draft(draft_id: UUID, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return get_draft(db, str(draft_id))
    except (ValueError, PermissionError, LookupError) as exc:
        _raise(exc)


@router.put("/{draft_id}", response_model=DraftResponse)
def put_draft(draft_id: UUID, payload: DraftSaveRequest, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return save_draft(db, str(draft_id), **payload.model_dump())
    except (ValueError, PermissionError, LookupError) as exc:
        _raise(exc)


@router.delete("/{draft_id}", status_code=204)
def discard_draft(draft_id: UUID, expected_revision: int = Query(..., ge=1), db: Session = Depends(get_db)):
    try:
        delete_draft(db, str(draft_id), expected_revision=expected_revision)
    except (ValueError, PermissionError, LookupError) as exc:
        _raise(exc)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/{draft_id}/submit")
def commit_draft(draft_id: UUID, payload: DraftSubmitRequest, response: Response,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        draft = get_draft(db, str(draft_id))
        schema = CaseCreate if draft.mode == "create" else CaseUpdate
        case_payload = schema.model_validate(payload.case_payload)
        values = case_payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        request_payload = case_payload.model_dump(mode="json", exclude={"expected_revision"},
                                                  exclude_unset=draft.mode == "edit")
        result = submit_draft(db, str(draft_id), expected_revision=payload.expected_revision,
            request_payload=request_payload, values=values, idempotency_key=idempotency_key,
            confirm_only=payload.confirm_only)
        return {"id": result.id, "revision": result.revision, "status": result.status,
                "submitted_case_id": result.submitted_case_id, "case_id": result.submitted_case_id}
    except (ValueError, PermissionError, LookupError) as exc:
        _raise(exc)
