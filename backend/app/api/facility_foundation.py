"""v6.2 controlled identity decisions and source-bound facility recording."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.case_facility_association import CaseFacilityAssociation
from app.services.case_facility_association_service import record_association, revoke_association, view_association
from app.services.facility_execution_context import freeze_facility_context

router = APIRouter()


class IdentityDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=8, max_length=80)
    previous_decision_id: int | None = Field(default=None, gt=0)


class IdentityBindInput(IdentityDecisionInput):
    asset_id: int = Field(gt=0)


class AssociationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: int = Field(gt=0)
    source_reference_id: int = Field(gt=0)
    source_revision_id: int = Field(gt=0)
    relation_type: Literal["incident_site", "recovery_site", "mentioned"]
    note: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=8, max_length=80)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)


def _actor(request, db, *, admin=False):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "请先登录")
    db.info["principal_user_id"] = principal.user_id
    try:
        context = freeze_facility_context(db)
    except PermissionError:
        raise HTTPException(403, '当前账号不可访问') from None
    if admin and context.role != "admin":
        raise HTTPException(403, "仅地图管理员可修改设施身份对应")
    return context


@router.get('/identities')
def identities(request: Request, response: Response,
               source_id: int | None = Query(None, gt=0),
               asset_id: int | None = Query(None, gt=0), db: Session = Depends(get_db)):
    _actor(request, db, admin=True)
    response.headers['Cache-Control'] = 'no-store'
    from app.services.facility_identity_service import FacilityIdentityService
    try:
        with db.no_autoflush:
            return FacilityIdentityService.list_identity(db, source_id=source_id, asset_id=asset_id)
    except (PermissionError, LookupError):
        raise HTTPException(403, '来源或设施不可访问') from None
    except ValueError:
        raise HTTPException(422, '请选择来源或设施范围') from None


@router.get('/assets/{asset_id}/case-links')
def case_links(asset_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    _actor(request, db)
    response.headers['Cache-Control'] = 'no-store'
    from app.models.jurisdiction import JurisdictionAsset
    with db.no_autoflush:
        if db.query(JurisdictionAsset).filter_by(id=asset_id).first() is None:
            raise HTTPException(404, '设施不存在或不可访问')
        rows = db.query(CaseFacilityAssociation).filter_by(asset_id=asset_id).order_by(CaseFacilityAssociation.id).all()
        try:
            return {'items': [view_association(db, row) for row in rows]}
        except PermissionError:
            raise HTTPException(403, '资料不可访问') from None


def _write(db, response, action):
    response.headers["Cache-Control"] = "no-store"
    try:
        value = action()
        db.commit()
        return value
    except PermissionError:
        db.rollback()
        raise HTTPException(403, "该资料或写入范围不可访问") from None
    except LookupError:
        db.rollback()
        raise HTTPException(404, "来源或设施不存在或不可访问") from None
    except ValueError as error:
        db.rollback()
        changed = any(word in str(error) for word in ("conflict", "changed", "concurrent"))
        raise HTTPException(409 if changed else 422,
            "来源或决定已变化，请刷新后重新核对" if changed else "请核对来源、关系类型、有效期和说明") from None
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "对应记录已变化，请刷新重试") from None


@router.post("/identities/{identity_id}/bind")
def bind_identity(identity_id: int, payload: IdentityBindInput, request: Request,
                  response: Response, db: Session = Depends(get_db)):
    actor = _actor(request, db, admin=True)
    from app.services.facility_identity_service import FacilityIdentityService
    return _write(db, response, lambda: FacilityIdentityService.bind(db, identity_id,
        payload.asset_id, actor_id=actor.user_id, **payload.model_dump(exclude={"asset_id"})))


@router.post("/identities/{identity_id}/revoke")
def revoke_identity(identity_id: int, payload: IdentityDecisionInput, request: Request,
                    response: Response, db: Session = Depends(get_db)):
    actor = _actor(request, db, admin=True)
    from app.services.facility_identity_service import FacilityIdentityService
    return _write(db, response, lambda: FacilityIdentityService.revoke(db, identity_id,
        actor_id=actor.user_id, **payload.model_dump()))


@router.post("/assets/{asset_id}/case-links")
def associate_case(asset_id: int, payload: AssociationInput, request: Request,
                   response: Response, db: Session = Depends(get_db)):
    _actor(request, db)
    def action():
        row, created = record_association(db, asset_id=asset_id, **payload.model_dump())
        response.status_code = 201 if created else 200
        return {**view_association(db, row), "created": created}
    return _write(db, response, action)


@router.post("/case-links/{association_id}/revoke")
def revoke_case_link(association_id: int, payload: RevokeInput, request: Request,
                     response: Response, db: Session = Depends(get_db)):
    _actor(request, db)
    return _write(db, response, lambda: view_association(db,
        revoke_association(db, association_id, note=payload.note)))
