"""Import parsing must reject ambiguous mappings before any business write."""
import io

import openpyxl
import pytest

from app.services.case_import_table import parse_case_table


def workbook_bytes(rows, *, title="案件", cover=False):
    workbook = openpyxl.Workbook()
    if cover:
        workbook.active.title = "说明"
        workbook.active.append(["请读取案件工作表"])
        sheet = workbook.create_sheet(title)
    else:
        sheet = workbook.active
        sheet.title = title
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_chinese_headers_are_mapped_without_changing_values():
    table = parse_case_table("案件.csv", "案发时间,案情描述,发生地点,经度,纬度\n2026-09-10 10:00,测试原文,甲地,124,47\n".encode())
    assert table.rows[0].number == 2
    assert table.rows[0].values == {"occurred_time": "2026-09-10 10:00", "description": "测试原文", "location": "甲地", "longitude": "124", "latitude": "47"}


def test_select_sheet_header_and_preserve_physical_row_numbers():
    content = workbook_bytes([["某台账"], ["发生日期", "摘要"], [None, None], ["2026-09-10", "原文"]], cover=True)
    table = parse_case_table("案件.xlsx", content, worksheet="案件", header_row=2, field_mapping={"发生日期": "occurred_time", "摘要": "description"})
    assert table.worksheets == ("说明", "案件")
    assert table.rows[0].number == 4
    assert table.rows[0].values["description"] == "原文"


@pytest.mark.parametrize("header", ["occurred_time,description,description", "案发时间,案情描述,description"])
def test_duplicate_or_colliding_headers_are_rejected(header):
    with pytest.raises(ValueError, match="重复|冲突"):
        parse_case_table("x.csv", (header + "\n2026-09-10,a,b\n").encode())


@pytest.mark.parametrize("mapping", [{"不存在": "location"}, {"description": "operational_area_id"}, {"description": "__row_number"}])
def test_custom_mapping_cannot_select_missing_columns_or_security_fields(mapping):
    with pytest.raises(ValueError):
        parse_case_table("x.csv", b"occurred_time,description\n2026-09-10,test\n", field_mapping=mapping)


def test_surplus_csv_cells_are_not_silently_discarded():
    with pytest.raises(ValueError, match="第 2 行"):
        parse_case_table("x.csv", b"occurred_time,description\n2026-09-10,test,extra\n")


def test_named_sheet_must_exist():
    with pytest.raises(ValueError, match="工作表"):
        parse_case_table("x.xlsx", workbook_bytes([["occurred_time", "description"]]), worksheet="不存在")


def test_unknown_columns_are_reported_not_written():
    table = parse_case_table("x.csv", b"occurred_time,description,operational_area_id\n2026-09-10,test,99\n")
    assert table.ignored_headers == ("operational_area_id",)
    assert "operational_area_id" not in table.rows[0].values


def test_blank_csv_rows_do_not_change_error_line_numbers():
    table = parse_case_table("x.csv", b"occurred_time,description\n\n2026-09-10,test\n")
    assert table.rows[0].number == 3


def test_quoted_multiline_csv_preserves_record_start_line():
    table = parse_case_table("x.csv", b'occurred_time,description\n2026-09-10,"first\nsecond"\n2026-09-11,last\n')
    assert [row.number for row in table.rows] == [2, 4]


@pytest.mark.parametrize("header_row", [0, 101, True])
def test_header_row_is_bounded(header_row):
    with pytest.raises(ValueError, match="表头"):
        parse_case_table("x.csv", b"occurred_time,description\n", header_row=header_row)


def test_mapping_values_must_be_field_names():
    with pytest.raises(ValueError):
        parse_case_table("x.csv", b"occurred_time,description\n", field_mapping={"description": []})


def test_no_formula_text_is_evaluated():
    table = parse_case_table("x.csv", b'occurred_time,description\n2026-09-10,"=HYPERLINK(""https://example.invalid"")"\n')
    assert table.rows[0].values["description"].startswith("=HYPERLINK")
