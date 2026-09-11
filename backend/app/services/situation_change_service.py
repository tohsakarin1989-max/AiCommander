"""Versioned, equal-window case changes; no deployment commands or model calls."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.services.situation_semantic_changes import semantic_window, semantic_changes

VERSION = 'situation-change-4.4-1'
BUSINESS_TIMEZONE = ZoneInfo('Asia/Shanghai')
CHANGE_RULE = {'version': 'case-change-threshold-4.4-1', 'minimum_increase': 3,
               'minimum_relative_increase': 0.25, 'calibrated_probability': False}


@dataclass(frozen=True)
class ComparisonWindow:
    previous_start: datetime
    current_start: datetime
    current_end: datetime


def closed_window(as_of: datetime, period: Literal['daily', 'weekly']) -> ComparisonWindow:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('situation_timezone_required')
    local_end = as_of.astimezone(BUSINESS_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'weekly':
        local_end -= timedelta(days=local_end.weekday())
        length = timedelta(days=7)
    elif period == 'daily':
        length = timedelta(days=1)
    else:
        raise ValueError('invalid_period_type')
    end = local_end.astimezone(timezone.utc)
    return ComparisonWindow(end - 2 * length, end - length, end)


def case_changes(db: Session, area_id: int, window: ComparisonWindow) -> dict[str, Any]:
    """Count full authorized case windows, not the loaded page or analysis completions."""
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('situation_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('situation_area_forbidden')

    def snapshot(start: datetime, end: datetime) -> dict[str, Any]:
        query = db.query(Case).filter(Case.operational_area_id == area_id,
            Case.occurred_time >= start, Case.occurred_time < end)
        dimensions = {}
        for field in ('case_type', 'oil_type'):
            column = getattr(Case, field)
            dimensions[field] = [{'value': value, 'count': count}
                for value, count in query.with_entities(column, func.count(Case.id))
                .group_by(column).order_by(column).all()]
        progress_query = db.query(CaseAnalysisProfile).join(
            Case, Case.id == CaseAnalysisProfile.case_id).filter(
            Case.operational_area_id == area_id, CaseAnalysisProfile.created_at >= start,
            CaseAnalysisProfile.created_at < end)
        return {'start': start.isoformat(), 'end': end.isoformat(), 'case_count': query.count(),
                'dimensions': dimensions, 'profile_versions_generated': progress_query.count(),
                'profile_case_ids': [row[0] for row in progress_query.with_entities(CaseAnalysisProfile.case_id)
                                     .distinct().order_by(CaseAnalysisProfile.case_id).all()],
                'case_ids': [row[0] for row in query.with_entities(Case.id).order_by(Case.id).all()],
                'semantic_terms': semantic_window(db, area_id, start, end)}

    previous = snapshot(window.previous_start, window.current_start)
    current = snapshot(window.current_start, window.current_end)
    semantics = semantic_changes(previous.pop('semantic_terms'), current.pop('semantic_terms'))
    return {'algorithm_version': VERSION, 'timezone': 'Asia/Shanghai',
            'previous': previous, 'current': current,
            'case_count_change': current['case_count'] - previous['case_count'],
            'semantic_changes': semantics,
            'boundary': '案件按案发时间；画像版本数量按生成时间，两者不可相互替代。区间左闭右开。'}


def change_recommendations(comparison: dict[str, Any], area_name: str) -> list[dict[str, Any]]:
    """Conservative attention triggers, not a statistical significance claim."""
    current, previous = comparison['current'], comparison['previous']
    signals = [('案件总数', previous['case_count'], current['case_count'])]
    for field, label in [('case_type', '案件类型'), ('oil_type', '油品')]:
        before = {row['value']: row['count'] for row in previous['dimensions'].get(field, [])}
        for row in current['dimensions'].get(field, []):
            if row['value']:
                signals.append((f"{label}：{row['value']}", before.get(row['value'], 0), row['count']))
    items = []
    seen_counts = set()
    for label, before, after in sorted(signals, key=lambda row: (-(row[2] - row[1]), row[0])):
        increase = after - before
        if increase < CHANGE_RULE['minimum_increase'] or increase / max(before, 1) < CHANGE_RULE['minimum_relative_increase']:
            continue
        # A single homogeneous increase must not become three equivalent tasks.
        if (before, after) in seen_counts:
            continue
        seen_counts.add((before, after))
        items.append({
            'title': f'关注{label}增加对应的设施与地点条件', 'target_area': area_name,
            'time_window': f"统计窗口 {current['start']} 至 {current['end']}，具体部署时段尚需现场条件支持",
            'suggested_action': '结合相关案件地点与既有通行条件，优先检查设施周边技防覆盖和可用资源；是否调整工作安排由人工决定。',
            'resource_assumption': '尚未核实可用人员、设备和通行条件，不预设新增力量或具体点位。',
            'expected_effect': '明确变化对应的关注范围；不表示已证明防控效果改善。',
            'evidence_refs': [f'case:{identifier}' for identifier in sorted(set(current['case_ids'] + previous['case_ids']))],
            'supporting_evidence': [f'{label}：上一等长周期 {before} 起，本期 {after} 起，增加 {increase} 起。',
                '触发规则：增加至少3起且相对增加至少25%；基期为0时只检查增加数量。这是关注规则，不是统计显著性或犯罪预测。'],
            'information_gaps': ['需结合补录情况、地点、道路和技防资料判断；数量变化本身不能证明风险上升。'],
            # Kept only for the old non-null database contract; API does not
            # expose this compatibility value as a probability or rank score.
            'confidence': 0.0,
        })
        if len(items) == 3:
            break
    return items
