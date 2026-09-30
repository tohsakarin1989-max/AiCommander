"""Organization rules versioned separately from completeness and runtime availability."""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class TimelinessPolicy:
    version: str = "report-entry-deadlines-1"
    enabled: bool = True
    report_limit_minutes: int = 60
    entry_limit_hours: int = 48

    def __post_init__(self):
        if not self.version or self.report_limit_minutes <= 0 or self.entry_limit_hours <= 0:
            raise ValueError("invalid_timeliness_policy")


DEFAULT_TIMELINESS_POLICY = TimelinessPolicy()


def utc_instant(value):
    """Persisted naive timestamps are UTC; convert explicit offsets, never strip them."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)


def time_precision(case):
    return getattr(case, "time_precision", None) or ("exact" if getattr(case, "occurred_time", None) else "unknown")


def evaluate_timeliness(case, policy=DEFAULT_TIMELINESS_POLICY):
    result = {
        "rule_version": policy.version, "status": "not_evaluable",
        "reason": "发生时间不是精确时刻，不能判断组织报送时限。",
        "report_limit_minutes": policy.report_limit_minutes, "entry_limit_hours": policy.entry_limit_hours,
        "reported_in_time": None, "entered_in_time": None,
    }
    if not policy.enabled:
        return {**result, "status": "disabled", "reason": "组织时限规则未启用。"}
    occurred = utc_instant(getattr(case, "occurred_time", None))
    if time_precision(case) != "exact" or occurred is None:
        return result
    for field, key, limit in (("report_time", "reported_in_time", policy.report_limit_minutes * 60),
                              ("created_at", "entered_in_time", policy.entry_limit_hours * 3600)):
        instant = utc_instant(getattr(case, field, None))
        if instant is not None:
            result[key] = 0 <= (instant - occurred).total_seconds() <= limit
    if any(result[key] is not None for key in ("reported_in_time", "entered_in_time")):
        result.update(status="evaluated", reason="仅按已记录的精确发生时刻评价组织时限，不代表案件办结状态。")
    else:
        result["reason"] = "缺少报送或录入时刻，组织时限暂不可评价。"
    return result
