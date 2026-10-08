"""v6.1 typed intake payloads; no arbitrary path, SQL or network execution."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.case_intake_contract import validate_geometry

OilUnit = Literal["tonne", "liter", "kg", "m3", "unknown"]


class CaseLocationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = Field(default=None, strict=True, gt=0)
    role: Literal["incident", "discovery", "mentioned", "source_candidate", "custody"]
    description: str | None = Field(default=None, max_length=2000)
    geometry: dict | None = None
    precision: Literal["exact", "area", "unknown"] = "unknown"
    source_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_location(self):
        validate_geometry(self.geometry)
        if self.precision == "exact" and (self.geometry or {}).get("type") != "Point":
            raise ValueError("精确地点需要点坐标")
        return self


class OilMeasurementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = Field(default=None, strict=True, gt=0)
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: OilUnit
    stage: Literal["involved", "seized", "transferred", "recovered", "unknown"] = "unknown"
    method: str | None = Field(default=None, max_length=200)
    measured_at: datetime | None = None
    water_cut: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    water_cut_basis: str | None = Field(default=None, max_length=200)
    source_note: str | None = Field(default=None, max_length=2000)


class SourceReferenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision_id: int
    field: Literal["description", "source_detail", "time_expression"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
