"""Authorized import receipts and explicit failed-row correction."""
import csv
from typing import Any, Literal
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import openpyxl
try:
    from lxml.etree import XMLSyntaxError
except ImportError:
    XMLSyntaxError = ParseError

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db, require_area_write_access
from app.models.case_import import CaseImportTemplate
from app.services.case_import_table import FIELDS, MAX_BYTES, parse_case_table
from app.services.case_import_retry_service import get_batch_rows, retry_batch_rows

router = APIRouter()


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


@router.get("/batches/{batch_id}")
def get_import_batch(batch_id: str, db: Session = Depends(get_db)):
    return get_batch_rows(db, batch_id)


@router.post("/batches/{batch_id}/retry")
def retry_import_batch(batch_id: str, payload: RetryRequest, db: Session = Depends(get_db)):
    return retry_batch_rows(db, batch_id, payload.rows)


class ImportSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worksheet: str | None = Field(default=None, max_length=31)
    header_row: int = Field(default=1, ge=1, le=100, strict=True)
    time_zone: Literal["UTC", "Asia/Shanghai"] = "UTC"
    field_mapping: dict[str, str | None] = Field(default_factory=dict, max_length=200)

    @field_validator("field_mapping")
    @classmethod
    def validate_mapping(cls, value):
        if any(not key.strip() or len(key) > 10000 or (target is not None and target not in FIELDS)
               for key, target in value.items()):
            raise ValueError("字段映射无效")
        targets = [target for target in value.values() if target is not None]
        if len(targets) != len(set(targets)):
            raise ValueError("多列不能映射到同一个案件字段")
        import json
        if len(json.dumps(value)) > 20000:
            raise ValueError("字段映射过长")
        return value


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    operational_area_id: int | None = Field(default=None, gt=0)
    settings: ImportSettings

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("模板名称不能为空")
        return value.strip()


def _template_result(row):
    return {"id": row.id, "name": row.name, "operational_area_id": row.operational_area_id,
            "settings": row.settings, "created_at": row.created_at}


@router.get("/templates")
def list_import_templates(db: Session = Depends(get_db)):
    rows = db.query(CaseImportTemplate).order_by(CaseImportTemplate.created_at.desc(), CaseImportTemplate.id).limit(200).all()
    return [_template_result(row) for row in rows]


@router.post("/templates", status_code=201)
def save_import_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    area_id = require_area_write_access(db, payload.operational_area_id)
    template = CaseImportTemplate(id=str(uuid4()), name=payload.name, operational_area_id=area_id,
                                  settings=payload.settings.model_dump(), created_by=db.info.get("principal_user_id"))
    db.add(template)
    try:
        db.commit()
        db.refresh(template)
    except Exception:
        db.rollback()
        raise
    return _template_result(template)


@router.post("/inspect")
def inspect_import_file(file: UploadFile = File(...), worksheet: str | None = None, header_row: int = 1,
                        operational_area_id: int | None = None, db: Session = Depends(get_db)):
    require_area_write_access(db, operational_area_id)
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，限制为 10MB")
    try:
        table = parse_case_table(file.filename or "", content, worksheet=worksheet, header_row=header_row, inspect_only=True)
    except (ValueError, TypeError, csv.Error, openpyxl.utils.exceptions.InvalidFileException) as exc:
        raise HTTPException(status_code=400, detail=f"读取列名失败: {exc}") from exc
    except (KeyError, OSError, ParseError, XMLSyntaxError, BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="Excel 文件结构损坏或不完整") from exc
    return {"headers": table.headers, "worksheets": table.worksheets, "worksheet": table.worksheet,
            "header_row": table.header_row, "suggested_mapping": table.field_mapping, "total": len(table.rows)}
