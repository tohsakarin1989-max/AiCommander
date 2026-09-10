"""显式完整日期区间解析；不推断缺省年月日、时区或案发事实。"""
from dataclasses import asdict
from datetime import datetime
import re

from app.services.case_semantic_evidence import SourceText, TextReference


DATE_TIME = (
    r"[0-9]{4}(?:年[0-9]{1,2}月[0-9]{1,2}日|-[0-9]{1,2}-[0-9]{1,2})"
    r"[ T]*[0-9]{1,2}(?::[0-9]{2}|时(?:[0-9]{1,2}分)?)"
)
INTERVAL = re.compile(rf"(?<![0-9])(?P<start>{DATE_TIME})\s*(?:至|到|—|~|～)\s*(?P<end>{DATE_TIME})(?![0-9:分])")
DATE_PARTS = re.compile(
    r"(?P<year>[0-9]{4})[年-](?P<month>[0-9]{1,2})[月-](?P<day>[0-9]{1,2})日?"
    r"[ T]*(?P<hour>[0-9]{1,2})(?::(?P<minute>[0-9]{2})|时(?:(?P<cn_minute>[0-9]{1,2})分)?)"
)
RELATIVE = re.compile(r"昨晚|昨天|前天|当晚|次日|近日|当天")
CLOCK_ONLY = re.compile(r"(?:凌晨|上午|下午|晚上)?[0-9一二三四五六七八九十两]{1,3}(?:点|时)(?:[0-9]{1,2}分)?")


def _parse(value: str) -> tuple[datetime, str]:
    match = DATE_PARTS.fullmatch(value)
    if match is None:
        raise ValueError("unsupported_time_expression")
    parts = match.groupdict()
    minute = parts["minute"] or parts["cn_minute"]
    instant = datetime(
        int(parts["year"]), int(parts["month"]), int(parts["day"]),
        int(parts["hour"]), int(minute or 0),
    )
    return instant, "minute" if minute is not None else "hour"


def extract_time_intervals(source: SourceText) -> tuple[list[dict], list[dict]]:
    intervals, gaps = [], []
    covered = []
    for match in INTERVAL.finditer(source.text):
        covered.append((match.start(), match.end()))
        ref = TextReference(source.field, source.sha256, match.start(), match.end(), match.group())
        ref.validate(source)
        try:
            start, start_precision = _parse(match["start"])
            end, end_precision = _parse(match["end"])
            if end < start:
                raise ValueError("reversed_interval")
        except ValueError:
            gaps.append({"code": "invalid_time_interval", "reference": asdict(ref)})
            continue
        intervals.append({
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "start_precision": start_precision, "end_precision": end_precision,
            "time_basis": "source_wall_clock", "timezone": None,
            "status": "unverified_expression", "is_official_fact": False,
            "reference": asdict(ref),
        })
    for match in RELATIVE.finditer(source.text):
        gaps.append({
            "code": "relative_time_requires_anchor",
            "reference": asdict(TextReference(source.field, source.sha256, match.start(), match.end(), match.group())),
        })
    for match in CLOCK_ONLY.finditer(source.text):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        gaps.append({
            "code": "time_expression_requires_context",
            "reference": asdict(TextReference(source.field, source.sha256, match.start(), match.end(), match.group())),
        })
    return intervals, gaps
