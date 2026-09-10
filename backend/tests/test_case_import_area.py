import io

import openpyxl
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api.cases import import_cases
from app.database import AreaWriteAccessError
from app.models.case import Case
from app.models.map_foundation import OperationalArea


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
