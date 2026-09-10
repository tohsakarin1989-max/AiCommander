"""One deterministic validator shared by previews, imports and row corrections."""
from datetime import date, datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

from app.services.case_import_table import FIELDS

TIME_ZONES = frozenset({"UTC", "Asia/Shanghai"})
TIME_FIELDS = frozenset({"occurred_time", "report_time"})
NUMBER_FIELDS = frozenset({"latitude", "longitude", "water_cut", "oil_volume"})
BOOL_FIELDS = frozenset({"police_reported", "case_filed"})


def allocation_order(row: dict[str, Any], time_zone: str, row_number: int) -> tuple[date, int]:
    """Acquire date-prefix uniqueness locks in the same order across batches."""
    try:
        occurred = normalize_case_row(row, time_zone=time_zone)["occurred_time"]
        return occurred.date(), row_number
    except (ValueError, TypeError):
        # Invalid rows never acquire a case-number lock and retain source order.
        return date.max, row_number


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == "None"


def _time(value: Any, time_zone: str) -> datetime | None:
    if _empty(value):
        return None
    text = str(value).strip()
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"无法解析时间格式: {text}")
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo(time_zone))


def _number(value: Any) -> float | None:
    if _empty(value):
        return None
    if isinstance(value, bool):
        raise ValueError("数值格式无效，请使用数字并确认单位")
    try:
        parsed = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("数值格式无效，请使用数字并确认单位") from exc
    if not math.isfinite(parsed):
        raise ValueError("数值必须为有限数")
    return parsed


def _boolean(value: Any) -> bool | None:
    if _empty(value):
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是", "已", "已报", "已立案"}:
        return True
    if text in {"0", "false", "no", "n", "否", "未", "未报", "未立案"}:
        return False
    raise ValueError("是否类字段仅接受明确的是/否或 true/false")


def normalize_case_row(row: dict[str, Any], *, time_zone: str = "UTC") -> dict[str, Any]:
    """Produce only allowlisted business arguments; never scope, IDs or commit flags."""
    if time_zone not in TIME_ZONES:
        raise ValueError("时区仅支持 UTC 或 Asia/Shanghai，请明确选择")
    if _empty(row.get("occurred_time")) or _empty(row.get("description")) or not str(row["description"]).strip():
        raise ValueError("缺少发生时间或描述")
    result: dict[str, Any] = {}
    for field in sorted(FIELDS - {"security_team"}):
        value = row.get(field)
        if field in TIME_FIELDS:
            result[field] = _time(value, time_zone)
        elif field in NUMBER_FIELDS:
            label = {"latitude": "纬度", "longitude": "经度"}.get(field)
            try:
                result[field] = _number(value)
            except ValueError as exc:
                if label:
                    raise ValueError(f"{label}坐标必须为有限数") from exc
                raise
            bound = {"latitude": 90, "longitude": 180}.get(field)
            if bound is not None and result[field] is not None and not -bound <= result[field] <= bound:
                raise ValueError(f"{label}坐标超出有效范围")
        elif field in BOOL_FIELDS:
            result[field] = _boolean(value)
        else:
            result[field] = None if _empty(value) else str(value)
    unit, team = row.get("report_unit"), row.get("security_team")
    if not _empty(unit) and not _empty(team) and str(unit).strip() != str(team).strip():
        raise ValueError("报告单位与保卫队内容冲突，请确认后只保留一个值")
    if _empty(unit) and not _empty(team):
        result["report_unit"] = str(team)
    return result


def case_row_preview(number: int, values: dict[str, Any]) -> dict[str, Any]:
    preview = {key: values[key] for key in (
        "occurred_time", "location", "latitude", "longitude", "report_time",
        "report_unit", "source_type", "description",
    )}
    for field in TIME_FIELDS:
        preview[field] = preview[field].isoformat() if preview[field] is not None else None
    preview["description"] = preview["description"][:120]
    return {"row": number, **preview}
