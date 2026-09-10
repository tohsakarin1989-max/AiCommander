"""案件 API 与持久化共用的时间契约；无时区旧参数按 UTC 兼容解释。"""
from datetime import datetime, timezone


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
