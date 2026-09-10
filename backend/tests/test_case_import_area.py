import io
import json
import zipfile

import openpyxl
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api.cases import import_cases
from app.database import AreaWriteAccessError
from app.models.case import Case
from app.models.map_foundation import OperationalArea


def test_case_import_accepts_chinese_headers_and_preserves_original_description(db_session):
    result = import_cases(
        file=UploadFile(filename="案件.csv", file=io.BytesIO(
            "案发时间,案情描述,经度,纬度\n2026-09-10T10:00:00+08:00,测试原文,124,47\n".encode()
        )), dry_run=True, db=db_session,
    )
    assert result["valid"] == 1
    assert result["table"]["field_mapping"]["案情描述"] == "description"
    assert db_session.query(Case).count() == 0


def test_case_import_custom_mapping_and_source_error_line(db_session):
    result = import_cases(
        file=UploadFile(filename="案件.csv", file=io.BytesIO(
            "台账说明\n日期,内容\n\n错误日期,测试原文\n".encode()
        )), dry_run=True, db=db_session, header_row=2,
        field_mapping=json.dumps({"日期": "occurred_time", "内容": "description"}),
    )
    assert result["errors"][0]["row"] == 4
    assert db_session.query(Case).count() == 0


@pytest.mark.parametrize("column,value", [("longitude", "不是坐标"), ("oil_volume", "十吨"), ("police_reported", "可能")])
def test_case_import_rejects_invalid_provided_values_instead_of_discarding(db_session, column, value):
    result = import_cases(
        file=UploadFile(filename="案件.csv", file=io.BytesIO(
            f"occurred_time,description,{column}\n2026-09-10,测试原文,{value}\n".encode()
        )), dry_run=True, db=db_session,
    )
    assert len(result["errors"]) == 1
    assert result["valid"] == 0


def test_case_import_rejects_ambiguous_columns_before_any_write(db_session):
    with pytest.raises(HTTPException) as error:
        import_cases(file=UploadFile(filename="x.csv", file=io.BytesIO(
            "案发时间,description,案情描述\n2026-09-10,a,b\n".encode()
        )), db=db_session)
    assert error.value.status_code == 400
    assert db_session.query(Case).count() == 0


def test_case_import_unit_alias_conflict_is_not_silently_discarded(db_session):
    result = import_cases(file=UploadFile(filename="x.csv", file=io.BytesIO(
        "案发时间,案情描述,报告单位,保卫队\n2026-09-10,原文,甲,乙\n".encode()
    )), dry_run=True, db=db_session)
    assert result["valid"] == 0
    assert "冲突" in result["errors"][0]["error"]


@pytest.mark.parametrize("damage", ["missing-member", "broken-xml"])
def test_damaged_workbook_returns_client_error_not_server_error(damage, db_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.cases import router
    from app.database import get_db

    workbook = openpyxl.Workbook()
    workbook.active.append(["occurred_time", "description"])
    source = io.BytesIO()
    workbook.save(source)
    workbook.close()
    damaged = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(damaged, "w") as output:
        for name in original.namelist():
            if damage == "missing-member" and name == "[Content_Types].xml":
                continue
            value = b"<broken>" if damage == "broken-xml" and name == "xl/worksheets/sheet1.xml" else original.read(name)
            output.writestr(name, value)
    app = FastAPI()
    app.include_router(router, prefix="/cases")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, raise_server_exceptions=False) as client:
        result = client.post("/cases/import?dry_run=true", files={"file": ("broken.xlsx", damaged.getvalue())})
    assert result.status_code == 400


def test_case_import_targets_the_explicit_writable_area(db_session):
    area_a = OperationalArea(code="import-a", name="导入默认区", status="active")
    area_b = OperationalArea(code="import-b", name="导入目标区", status="active")
    db_session.add_all([area_a, area_b])
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area_a.id, area_b.id)
    db_session.info["default_operational_area_id"] = area_a.id
    db_session.info["area_access_levels"] = {area_a.id: "write", area_b.id: "write"}
    upload = UploadFile(
        filename="cases.csv",
        file=io.BytesIO(
            b"occurred_time,description\n2026-09-09 10:00,imported case\n"
        ),
    )

    result = import_cases(
        file=upload,
        dry_run=False,
        operational_area_id=area_b.id,
        db=db_session,
    )

    assert result["created"] == 1
    imported = db_session.query(Case).filter(Case.description == "imported case").one()
    assert imported.operational_area_id == area_b.id


def test_case_import_rejects_a_read_only_target_area(db_session):
    area = OperationalArea(code="import-read", name="导入只读区", status="active")
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id
    db_session.info["area_access_levels"] = {area.id: "read"}
    upload = UploadFile(
        filename="cases.csv",
        file=io.BytesIO(
            b"occurred_time,description\n2026-09-09 10:00,blocked case\n"
        ),
    )

    with pytest.raises(AreaWriteAccessError):
        import_cases(
            file=upload,
            dry_run=True,
            operational_area_id=area.id,
            db=db_session,
        )


def test_case_import_rejects_more_than_safe_batch_without_writes(db_session):
    area = OperationalArea(code="import-limit", name="导入批次限制区", status="active")
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id
    db_session.info["area_access_levels"] = {area.id: "write"}
    rows = ["occurred_time,description"] + [
        f"2026-09-09 10:00,case-{index}" for index in range(1001)
    ]
    upload = UploadFile(
        filename="too-many-cases.csv",
        file=io.BytesIO(("\n".join(rows) + "\n").encode()),
    )

    with pytest.raises(HTTPException) as error:
        import_cases(
            file=upload,
            dry_run=False,
            operational_area_id=area.id,
            db=db_session,
        )

    assert error.value.status_code == 400
    assert "1000" in str(error.value.detail)
    assert db_session.query(Case).count() == 0


def test_case_import_rejects_xlsx_tail_after_blank_row_without_writes(db_session):
    area = OperationalArea(code="import-xlsx-limit", name="Excel导入限制区", status="active")
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id
    db_session.info["area_access_levels"] = {area.id: "write"}
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["occurred_time", "description"])
    for index in range(1000):
        sheet.append(["2026-09-09 10:00", f"case-{index}"])
    sheet.append([None, None])
    sheet.append(["2026-09-09 10:00", "hidden-tail-case"])
    content = io.BytesIO()
    workbook.save(content)
    workbook.close()
    content.seek(0)
    upload = UploadFile(filename="too-many-cases.xlsx", file=content)

    with pytest.raises(HTTPException) as error:
        import_cases(
            file=upload,
            dry_run=False,
            operational_area_id=area.id,
            db=db_session,
        )

    assert error.value.status_code == 400
    assert "1000" in str(error.value.detail)
    assert db_session.query(Case).count() == 0


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [("nan", "125.1"), ("46.6", "inf"), ("91", "125.1"), ("46.6", "181")],
)
def test_case_import_rejects_invalid_coordinates_without_polluting_data(
    db_session,
    latitude,
    longitude,
):
    area = OperationalArea(code=f"coord-{latitude}-{longitude}", name="坐标校验区", status="active")
    db_session.add(area)
    db_session.commit()
    db_session.info["authorized_area_ids"] = (area.id,)
    db_session.info["default_operational_area_id"] = area.id
    db_session.info["area_access_levels"] = {area.id: "write"}
    upload = UploadFile(
        filename="invalid-coordinate.csv",
        file=io.BytesIO(
            (
                "occurred_time,description,latitude,longitude\n"
                f"2026-09-09 10:00,invalid-coordinate,{latitude},{longitude}\n"
            ).encode()
        ),
    )

    result = import_cases(
        file=upload,
        dry_run=False,
        operational_area_id=area.id,
        db=db_session,
    )

    assert result["created"] == 0
    assert result["errors"]
    assert "坐标" in result["errors"][0]["error"]
    assert db_session.query(Case).count() == 0
