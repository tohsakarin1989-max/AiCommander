"""
保卫人员信息 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.personnel import SecurityPersonnel

router = APIRouter()


class PersonnelCreate(BaseModel):
    name: str
    badge_number: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    status: str = "active"
    notes: Optional[str] = None


class PersonnelUpdate(BaseModel):
    name: Optional[str] = None
    badge_number: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class PersonnelResponse(BaseModel):
    id: int
    name: str
    badge_number: Optional[str]
    department: Optional[str]
    position: Optional[str]
    phone: Optional[str]
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[PersonnelResponse])
def list_personnel(
    status: Optional[str] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[SecurityPersonnel]:
    query = db.query(SecurityPersonnel)
    if status:
        query = query.filter(SecurityPersonnel.status == status)
    if department:
        query = query.filter(SecurityPersonnel.department == department)
    return query.order_by(SecurityPersonnel.name).all()


@router.post("", response_model=PersonnelResponse)
def create_personnel(data: PersonnelCreate, db: Session = Depends(get_db)) -> SecurityPersonnel:
    personnel = SecurityPersonnel(**data.model_dump())
    db.add(personnel)
    db.commit()
    db.refresh(personnel)
    return personnel


@router.put("/{personnel_id:int}", response_model=PersonnelResponse)
def update_personnel(
    personnel_id: int,
    data: PersonnelUpdate,
    db: Session = Depends(get_db),
) -> SecurityPersonnel:
    personnel = db.query(SecurityPersonnel).filter(SecurityPersonnel.id == personnel_id).first()
    if not personnel:
        raise HTTPException(status_code=404, detail="人员不存在")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(personnel, field, value)
    personnel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(personnel)
    return personnel


@router.delete("/{personnel_id:int}")
def delete_personnel(personnel_id: int, db: Session = Depends(get_db)) -> dict:
    personnel = db.query(SecurityPersonnel).filter(SecurityPersonnel.id == personnel_id).first()
    if not personnel:
        raise HTTPException(status_code=404, detail="人员不存在")
    db.delete(personnel)
    db.commit()
    return {"ok": True}
