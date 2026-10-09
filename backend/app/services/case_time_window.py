"""One date-window contract without converting uncertain facts into exact dates."""
from sqlalchemy import and_, case as sql_case, func, or_

from app.models.case import Case
from app.utils.datetimes import utc_datetime


def filter_case_time_window(query, start=None, end=None, *, end_exclusive=True, time_basis=None):
    """Match exact instants or closed uncertainty intervals against [start, end).

    An interval whose endpoints are equal still represents interval input. Unknown
    time is included only when no date boundary is supplied. Naive old query
    parameters remain UTC-compatible; intake already normalizes fact timezones.
    The explicit inclusive option supports only the pre-existing legacy list API.
    """
    if time_basis not in {None, 'incident', 'discovery', 'entry'}:
        raise ValueError('invalid_time_basis')
    if start is None and end is None:
        return query
    start, end = utc_datetime(start), utc_datetime(end)
    if start is not None and end is not None and (start >= end if end_exclusive else start > end):
        raise ValueError("开始时间必须早于结束时间" if end_exclusive else "结束时间不能早于开始时间")
    if time_basis in {'discovery', 'entry'}:
        field = Case.discovered_at if time_basis == 'discovery' else Case.created_at
        query = query.filter(field.isnot(None))
        if start is not None:
            query = query.filter(field >= start)
        if end is not None:
            query = query.filter(field < end if end_exclusive else field <= end)
        return query
    exact = [Case.occurred_time.isnot(None)]
    interval = [Case.occurred_time.is_(None), Case.occurred_from.isnot(None),
                Case.occurred_to.isnot(None), Case.occurred_to >= Case.occurred_from]
    if time_basis == 'incident':
        # New explicit incident queries cannot certify an old generic timestamp.
        # The None path remains the declared legacy compatibility contract.
        exact.append(Case.time_precision == 'exact')
        interval.append(Case.time_precision == 'interval')
    if start is not None:
        exact.append(Case.occurred_time >= start)
        interval.append(Case.occurred_to >= start)
    if end is not None:
        exact.append(Case.occurred_time < end if end_exclusive else Case.occurred_time <= end)
        interval.append(Case.occurred_from < end if end_exclusive else Case.occurred_from <= end)
    return query.filter(or_(and_(*exact), and_(*interval)))


def case_time_label(case):
    """Render source precision, including a zero-width interval, without guessing."""
    if case.get("occurred_time"):
        return str(case["occurred_time"])
    if case.get("occurred_from") is not None and case.get("occurred_to") is not None:
        return f"时间区间：{case['occurred_from']} 至 {case['occurred_to']}"
    return case.get("time_expression") or "发生时间未知"


def case_time_fields(case):
    """Keep uncertainty in compact query and history projections, not only details."""
    return {
        **{field: utc_datetime(getattr(case, field)).isoformat() if getattr(case, field) else None
           for field in ("occurred_time", "occurred_from", "occurred_to")},
        "time_precision": case.time_precision or ("exact" if case.occurred_time else
            "interval" if case.occurred_from is not None and case.occurred_to is not None else "unknown"),
        "time_expression": case.time_expression,
        "time_timezone": case.time_timezone,
    }


def time_precision_counts(query, time_basis=None):
    """Count distinct time categories in the already-authorized filtered query."""
    if time_basis in {'discovery', 'entry'}:
        field = Case.discovered_at if time_basis == 'discovery' else Case.created_at
        total, exact = query.with_entities(func.count(Case.id), func.count(field)).one()
        return {'exact': exact, 'interval': 0, 'unknown': total - exact}
    if time_basis == 'incident':
        total, exact, interval = query.with_entities(func.count(Case.id),
            func.count(sql_case((and_(Case.time_precision == 'exact', Case.occurred_time.isnot(None)), 1))),
            func.count(sql_case((and_(Case.time_precision == 'interval', Case.occurred_time.is_(None),
                Case.occurred_from.isnot(None), Case.occurred_to.isnot(None), Case.occurred_to >= Case.occurred_from), 1)))).one()
        return {'exact': exact, 'interval': interval, 'unknown': total - exact - interval}
    total, exact, interval = query.with_entities(
        func.count(Case.id),
        func.count(sql_case((Case.occurred_time.isnot(None), 1))),
        func.count(sql_case((and_(Case.occurred_time.is_(None), Case.occurred_from.isnot(None),
                                 Case.occurred_to.isnot(None)), 1))),
    ).one()
    return {"exact": exact, "interval": interval, "unknown": total - exact - interval}


TIME_WINDOW_BOUNDARY = ("按精确时刻或时间区间与查询窗口相交筛选；区间只表示可能落入，"
                        "不是确定发生日期。同一案件可能命中相邻窗口，窗口计数不能相加当作去重案件总数。")
