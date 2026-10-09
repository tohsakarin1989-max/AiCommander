"""Small shared production-ledger contract, never an implicit unit/CRS guesser."""
import csv
import io


GROUPS = {
    "geometry": ["longitude", "latitude", "coordinate_system", "coordinate_unit"],
    "water_cut": ["water_cut_min", "water_cut_max", "water_cut_unit", "water_cut_basis"],
    "production": ["production_output", "production_output_unit", "production_period", "production_basis"],
}
VALUE_STATES = ["set", "not_provided", "unknown", "clear", "withdraw"]
FIELDS = [
    ("external_id", "井号", "text", "同一来源的稳定设施编号；不同编号不因同名而合并"),
    ("name", "井名", "text", "设施名称，不用于跨来源自动认定同一设施"),
    ("asset_type", "类型", "text", "例如 well、station、pipeline；不得更换已有身份类型"),
    ("longitude", "经度", "number", "与纬度、坐标系、单位作为一组处理"),
    ("latitude", "纬度", "number", "必须显式选择坐标系与轴顺序，不能从数值猜测"),
    ("address", "地址", "text", "可选，不提供不代表清空"),
    ("oil_type", "油品", "text", "生产资料明确登记的油品"),
    ("owner_unit", "所属单位", "text", "来源登记值"),
    ("production_unit", "生产单位", "text", "来源登记值"),
    ("production_status", "生产状态", "text", "来源登记状态，不推断现场状态"),
    ("facility_category", "设施类别", "text", "生产设施用途分类"),
    ("water_cut_min", "含水率下限", "number", "0—100 的百分比数值，与上限、单位及口径整体采用"),
    ("water_cut_max", "含水率上限", "number", "0—100 的百分比数值"),
    ("water_cut_unit", "含水率单位", "text", "明确填写 % 或 percent；不自动换算其他口径"),
    ("water_cut_basis", "含水率测量口径", "text", "例如质量含水率、体积含水率；未说明时保留未知"),
    ("production_output", "产量", "number", "非负有限数值；必须同时说明单位、统计周期与口径"),
    ("production_output_unit", "产量单位", "text", "例如吨、立方米，不自动跨单位比较"),
    ("production_period", "产量周期", "text", "例如日、月或明确时间区间"),
    ("production_basis", "产量口径", "text", "例如毛油、净油；未说明时保留未知"),
    ("is_high_production", "高产井", "boolean", "明确的 是/否、true/false、1/0"),
    ("production_valid_from", "生产条件有效起始", "datetime", "含时区 ISO 时间；不是接收文件时间"),
    ("production_valid_to", "生产条件有效截止", "datetime", "含时区 ISO 时间，右开区间"),
    ("valid_from", "资料有效起始", "datetime", "设施整体资料明确有效时间；不知道可留空"),
    ("valid_to", "资料有效截止", "datetime", "必须晚于已明确的有效起始"),
    ("coordinate_system", "坐标系声明", "text", "可选检测列；其值必须与管理员选择的模板一致"),
    ("coordinate_unit", "坐标单位声明", "text", "可选检测列；degree 或 meter，与模板一致"),
    ("geometry_state", "坐标处理", "state", "set/not_provided/unknown/clear/withdraw；清空、未知、撤销均不再供坐标计算"),
    ("water_cut_state", "含水率处理", "state", "空值默认为未提供；明确清空/撤销必须通过此列"),
    ("production_state", "产量处理", "state", "字段组整体处理，不能跨来源拼接缺失口径"),
]


def field_contract():
    return {"schema_version": "map-ledger-7.2-1", "fields": [
        {"key": key, "label": label, "type": kind, "description": description,
         "group": next((group for group, fields in GROUPS.items() if key in fields), None),
         "required": key in {"name", "asset_type", "longitude", "latitude"}}
        for key, label, kind, description in FIELDS],
        "groups": GROUPS, "value_states": VALUE_STATES}


def example_csv():
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([field[1] for field in FIELDS])
    example = {"external_id": "DEMO-001", "name": "脱敏示例井", "asset_type": "well",
        "longitude": 125.1, "latitude": 46.6, "oil_type": "原油", "water_cut_min": 30,
        "water_cut_max": 35, "water_cut_unit": "%", "water_cut_basis": "质量含水率",
        "production_output": 10, "production_output_unit": "吨", "production_period": "日",
        "production_basis": "净油", "is_high_production": "是", "coordinate_system": "wgs84",
        "coordinate_unit": "degree"}
    writer.writerow([example.get(field[0], "") for field in FIELDS])
    return stream.getvalue().encode("utf-8-sig")


def validate_contract(data):
    mapping = data.get("field_mapping") or {}
    if set(mapping) - {row[0] for row in FIELDS}:
        raise ValueError("unknown_import_field|字段映射包含未登记字段")
    units = data.get("field_units") or {}
    if set(units) - {"water_cut_unit", "production_output_unit"}:
        raise ValueError("unknown_field_unit|不支持的单位约束")
    structure = data.get("expected_structure") or {}
    if set(structure) - {"headers", "sheet_name", "header_row"}:
        raise ValueError("invalid_template_structure|模板结构字段无效")
    headers = structure.get("headers", [])
    if structure.get("sheet_name") is not None and (not isinstance(structure["sheet_name"], str) or len(structure["sheet_name"]) > 200):
        raise ValueError("invalid_template_structure|工作表名称无效")
    if structure.get("header_row") is not None and (type(structure["header_row"]) is not int or not 1 <= structure["header_row"] <= 100):
        raise ValueError("invalid_template_structure|表头行无效")
    if not isinstance(headers, list) or len(headers) > 200 or any(not isinstance(h, str) or len(h) > 200 for h in headers):
        raise ValueError("invalid_template_structure|模板表头无效")
    if len(set(h for h in headers if h)) != len([h for h in headers if h]):
        raise ValueError("duplicate_header|重复列名必须先处理，不能静默覆盖")
    if any(not isinstance(v, str) or not v or len(v) > 80 for v in units.values()):
        raise ValueError("invalid_field_unit|单位约束无效")


def detect_drift(template, structure):
    issues = []
    headers = structure["headers"]
    expected = template.expected_structure or {}
    # Mappings bind column names, not positions. Reordering or adding an unused
    # comment column is safe; changed mapped names are checked below.
    names = [name for name in headers if name]
    if len(names) != len(set(names)):
        issues.append({"field": "headers", "code": "duplicate_header", "message": "重复列名必须先核对"})
    for key in ("sheet_name", "header_row"):
        if expected.get(key) is not None and expected[key] != structure[key]:
            issues.append({"field": key, "code": "structure_drift", "message": "工作表或表头位置已变化",
                           "old": expected[key], "new": structure[key]})
    for key, column in (template.field_mapping or {}).items():
        if column not in headers:
            issues.append({"field": key, "code": "mapped_column_missing", "message": "已映射列不存在：" + column})
    return issues


def structure_changes(template, structure):
    """Non-blocking changes retained in the receipt, separate from drift."""
    expected = (template.expected_structure or {}).get("headers") or []
    actual = structure.get("headers") or []
    if not expected or expected == actual:
        return []
    return [{"code": "unmapped_structure_change", "severity": "information",
             "message": "列顺序或未映射列已变化；按已确认列名读取，实际列位置继续留存",
             "added": [name for name in actual if name not in expected],
             "removed": [name for name in expected if name not in actual],
             "reordered": [name for name in actual if name in expected] != [name for name in expected if name in actual]}]
