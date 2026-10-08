"""Versioned production comparisons, not risk scores or inferred oil sources."""
from datetime import datetime, timezone
import math

VERSION = "facility-production-7.3-1"


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


def production_comparison(*, attributes: dict, verified: bool, case_fields: dict, case_facts: dict,
                          temporal_context=None) -> dict:
    """Only explicit percent intervals covering the recorded incident time compare.

    There is no implicit tolerance, guessed unit or high-production bonus.
    Unknown or expired data are not evidence of a mismatch.
    """
    result = {"version": VERSION, "state": "unknown", "support": [], "counter": [], "gaps": []}
    if not verified:
        result["gaps"].append("生产资料未核验，未用于条件加分")
        return result
    if temporal_context is not None:
        group = temporal_context.get("groups", {}).get("water_cut", {})
        result.update(coverage=group.get("coverage", "unknown"), segments=[])
        if group.get("coverage") != "full":
            result["gaps"].append("含水率资料未覆盖完整案发区间，保留未知；不是条件不符")
            return result
        measured = case_facts.get("water_cut")
        if not _number(measured):
            result["gaps"].append("案件未记录有效检斤含水率，不推测测量结果")
            return result
        for segment in group["segments"]:
            values = segment["values"] or {}
            low, high = values.get("water_cut_min"), values.get("water_cut_max")
            basis = values.get("water_cut_basis")
            case_basis = case_facts.get("water_cut_basis") or case_fields.get("water_cut_basis")
            comparable = (values.get("water_cut_unit") == "percent" and _number(low) and _number(high)
                          and low <= high and (not basis and not case_basis or basis == case_basis))
            state = "unknown" if not comparable else "matched" if low <= measured <= high else "different"
            result["segments"].append({**segment, "comparison_state": state})
        states = {row["comparison_state"] for row in result["segments"]}
        if states in ({"matched"}, {"different"}):
            result["state"] = states.pop()
            result["comparison"] = {"field": "water_cut", "unit": "percent", "case_value": measured,
                                    "segments": result["segments"]}
            result["support" if result["state"] == "matched" else "counter"].append(
                f"案件检斤含水率 {measured:g}% 在完整案发区间内均{'符合' if result['state'] == 'matched' else '不符合'}已记录台账条件")
        else:
            result["coverage"] = "partial" if "matched" in states or "different" in states else "unknown"
            result["gaps"].append("分段含水率条件变化或测量口径未对齐，不能将局部比较提升为整案支持或排除")
        result["counter"].append("含水率条件相符不证明实际来源，混合、取样和测量差异仍需核查")
        return result
    low, high = attributes.get("water_cut_min"), attributes.get("water_cut_max")
    if attributes.get("water_cut_unit") != "percent" or not _number(low) or not _number(high) or low > high:
        result["gaps"].append("台账缺少明确百分比单位及有效含水率区间")
        return result
    measured = case_facts.get("water_cut")
    if not _number(measured):
        result["gaps"].append("案件未记录有效检斤含水率，不推测测量结果")
        return result
    from app.services.facility_temporal_conditions import case_window
    window = case_window(case_fields)
    first = _instant(window.get("valid_at") or window.get("valid_from"))
    last = _instant(window.get("valid_at") or window.get("valid_to"))
    metadata = attributes.get("field_groups", {}).get("water_cut", {})
    start = _instant(metadata.get("valid_from") if metadata else attributes.get("production_valid_from"), require_timezone=True)
    end = _instant(metadata.get("valid_to") if metadata else attributes.get("production_valid_to"), require_timezone=True)
    if first is None or start is None or end is None or start >= end:
        result["gaps"].append("缺少案发时间或台账条件有效期，不将当前资料倒推至案发时")
        return result
    if not start <= first <= last < end:
        result["gaps"].append("台账含水率条件不覆盖案发时段，保留未知")
        return result
    result["comparison"] = {"field": "water_cut", "unit": "percent", "case_value": measured,
                            "facility_interval": [low, high], "valid_from": start.isoformat(), "valid_to": end.isoformat()}
    result["state"] = "matched" if low <= measured <= high else "different"
    message = f"案件检斤含水率 {measured:g}% {'位于' if result['state'] == 'matched' else '不在'}台账已记录区间 {low:g}%—{high:g}%"
    result["support" if result["state"] == "matched" else "counter"].append(message)
    result["counter"].append("含水率条件相符不证明实际来源，混合、取样和测量差异仍需核查")
    return result
