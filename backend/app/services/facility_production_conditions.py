"""Versioned production comparisons, not risk scores or inferred oil sources."""
from datetime import datetime, timezone
import math

VERSION = "facility-production-5.2-1"


def _number(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 100


def _instant(value, *, require_timezone=False):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if require_timezone and stamp.tzinfo is None:
            return None
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except ValueError:
        return None


def production_comparison(*, attributes: dict, verified: bool, case_fields: dict, case_facts: dict) -> dict:
    """Only explicit percent intervals covering the recorded incident time compare.

    There is no implicit tolerance, guessed unit or high-production bonus.
    Unknown or expired data are not evidence of a mismatch.
    """
    result = {"version": VERSION, "state": "unknown", "support": [], "counter": [], "gaps": []}
    if not verified:
        result["gaps"].append("生产资料未核验，未用于条件加分")
        return result
    low, high = attributes.get("water_cut_min"), attributes.get("water_cut_max")
    if attributes.get("water_cut_unit") != "percent" or not _number(low) or not _number(high) or low > high:
        result["gaps"].append("台账缺少明确百分比单位及有效含水率区间")
        return result
    measured = case_facts.get("water_cut")
    if not _number(measured):
        result["gaps"].append("案件未记录有效检斤含水率，不推测测量结果")
        return result
    at = _instant(case_fields.get("occurred_time"))
    start = _instant(attributes.get("production_valid_from"), require_timezone=True)
    end = _instant(attributes.get("production_valid_to"), require_timezone=True)
    if at is None or start is None or end is None or start >= end:
        result["gaps"].append("缺少案发时间或台账条件有效期，不将当前资料倒推至案发时")
        return result
    if not start <= at < end:
        result["gaps"].append("台账含水率条件不覆盖案发时段，保留未知")
        return result
    result["comparison"] = {"field": "water_cut", "unit": "percent", "case_value": measured,
                            "facility_interval": [low, high], "valid_from": start.isoformat(), "valid_to": end.isoformat()}
    result["state"] = "matched" if low <= measured <= high else "different"
    message = f"案件检斤含水率 {measured:g}% {'位于' if result['state'] == 'matched' else '不在'}台账已记录区间 {low:g}%—{high:g}%"
    result["support" if result["state"] == "matched" else "counter"].append(message)
    result["counter"].append("含水率条件相符不证明实际来源，混合、取样和测量差异仍需核查")
    return result
