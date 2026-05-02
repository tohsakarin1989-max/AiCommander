"""
重要部位信息 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.key_location import KeyLocation

router = APIRouter()


class KeyLocationCreate(BaseModel):
    name: str
    location_type: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    description: Optional[str] = None
    risk_level: int = 1
    status: str = "active"


class KeyLocationUpdate(BaseModel):
    name: Optional[str] = None
    location_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    description: Optional[str] = None
    risk_level: Optional[int] = None
    status: Optional[str] = None


class KeyLocationResponse(BaseModel):
    id: int
    name: str
    location_type: str
    latitude: Optional[float]
    longitude: Optional[float]
    address: Optional[str]
    description: Optional[str]
    risk_level: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[KeyLocationResponse])
def list_key_locations(
    location_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[KeyLocation]:
    query = db.query(KeyLocation)
    if location_type:
        query = query.filter(KeyLocation.location_type == location_type)
    if status:
        query = query.filter(KeyLocation.status == status)
    return query.order_by(KeyLocation.name).all()


@router.post("", response_model=KeyLocationResponse)
def create_key_location(data: KeyLocationCreate, db: Session = Depends(get_db)) -> KeyLocation:
    loc = KeyLocation(**data.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.put("/{location_id:int}", response_model=KeyLocationResponse)
def update_key_location(
    location_id: int,
    data: KeyLocationUpdate,
    db: Session = Depends(get_db),
) -> KeyLocation:
    loc = db.query(KeyLocation).filter(KeyLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="部位不存在")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(loc, field, value)
    loc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(loc)
    return loc


@router.delete("/{location_id:int}")
def delete_key_location(location_id: int, db: Session = Depends(get_db)) -> dict:
    loc = db.query(KeyLocation).filter(KeyLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="部位不存在")
    db.delete(loc)
    db.commit()
    return {"ok": True}
