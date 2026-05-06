"""
重要部位信息模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database import Base


class KeyLocation(Base):
    __tablename__ = "key_locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    location_type = Column(String(50), nullable=False)  # oil_depot, pipeline_node, gas_station, refinery, storage, other
    latitude = Column(Float)
    longitude = Column(Float)
    address = Column(String(500))
    description = Column(String(1000))
    risk_level = Column(Integer, default=1)  # 1–5
    status = Column(String(20), default="active")  # active, inactive
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
