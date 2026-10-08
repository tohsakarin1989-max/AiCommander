"""Shared 8.2 time projection; legacy dashboard callers keep their old contract."""
from collections import Counter
from datetime import timedelta, timezone

from app.models.case import Case
from app.models.case_source import CaseLocation
from app.services.case_analysis_applicability import exact_point
from app.services.situation_change_service import ComparisonWindow
from app.services.situation_temporal_changes import case_changes, time_range


def project(db, area_id, start, end, basis):
    comparison = case_changes(db, area_id, ComparisonWindow(start - (end - start), start, end), basis)
    ids = comparison['current']['case_ids']
    rows = db.query(Case).filter(Case.id.in_(ids)).order_by(Case.id).all()
    days = Counter()
    undated_trend = 0
    tz = timezone(timedelta(hours=8))
    for case in rows:
        lower, upper = time_range(case, basis)
        first, last = lower.astimezone(tz).date(), upper.astimezone(tz).date()
        if first == last:
            days[first.isoformat()] += 1
        else:
            undated_trend += 1
    by_case = {}
    for location in db.query(CaseLocation).filter(CaseLocation.case_id.in_(ids)).order_by(CaseLocation.id):
        by_case.setdefault(location.case_id, {}).setdefault(location.role, []).append(location)
    points = {}
    for case in rows:
        locations = by_case.get(case.id, {})
        roles = ('discovery', 'incident') if basis == 'entry' else (basis,)
        for role in roles:
            matches = locations.get(role, [])
            if matches:
                point = exact_point({'precision': matches[0].precision, 'geometry': matches[0].geometry}) if len(matches) == 1 else None
                if point:
                    points[case.id] = {**point, 'location_role': role}
                break  # Ambiguous discovery points do not silently become incident points.
    return comparison, dict(days), undated_trend, points
