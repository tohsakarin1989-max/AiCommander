"""Comparable source windows only; device stocks are never added over time."""
from collections import defaultdict
from datetime import datetime, timezone

from app.models.deployment_advisor import TechDefenseEventAggregate, TechDefenseSource

VERSION = 'tech-window-change-4.4-1'


def _utc(value: datetime) -> datetime:
    # SQLAlchemy's SQLite datetime storage returns naive UTC values.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _period(rows, start, end):
    rows = sorted(rows, key=lambda row: (_utc(row.period_start), row.id))
    cursor = start
    segments, populations = [], set()
    for row in rows:
        left, right = _utc(row.period_start), _utc(row.period_end)
        if left != cursor or right <= left or right > end:
            return None  # Gap, overlap, crossing boundary or invalid interval.
        if any(type(getattr(row, key)) is not int or getattr(row, key) < 0 for key in
               ('online_count', 'offline_count', 'alert_count', 'redacted_vehicle_event_count')):
            return None
        segments.append([(left - start).total_seconds(), (right - start).total_seconds()])
        populations.add(row.online_count + row.offline_count)
        cursor = right
    if not rows or cursor != end or len(populations) != 1:
        return None
    last = rows[-1]
    return {'source_ids': [row.id for row in rows], 'segments': segments,
            'reported_device_count': populations.pop(), 'reported_online': last.online_count,
            'reported_offline': last.offline_count, 'last_summary_end': end.isoformat(),
            'alert_count': sum(row.alert_count for row in rows),
            'redacted_vehicle_event_count': sum(row.redacted_vehicle_event_count for row in rows)}


def tech_changes(db, area_id, window):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('tech_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('tech_area_forbidden')
    rows = db.query(TechDefenseEventAggregate).join(TechDefenseSource).filter(
        TechDefenseEventAggregate.operational_area_id == area_id,
        TechDefenseSource.operational_area_id == area_id, TechDefenseSource.status == 'active',
        TechDefenseEventAggregate.period_start < window.current_end,
        TechDefenseEventAggregate.period_end > window.previous_start).all()
    groups = defaultdict(list)
    for row in rows:
        groups[(row.source_id, row.device_type)].append(row)
    items = []
    for (source, kind), entries in sorted(groups.items()):
        previous = _period([r for r in entries if _utc(r.period_start) < window.current_start],
                           window.previous_start, window.current_start)
        current = _period([r for r in entries if _utc(r.period_end) > window.current_start],
                          window.current_start, window.current_end)
        comparable = (previous is not None and current is not None and
                      previous['segments'] == current['segments'] and
                      previous['reported_device_count'] == current['reported_device_count'])
        item = {'source_id': source, 'device_type': kind, 'state': 'comparable' if comparable else 'incomparable',
                'evidence_refs': [f'tech_aggregate:{row.id}' for row in sorted(entries, key=lambda r: r.id)],
                'information_gaps': ['设备身份与覆盖几何未提供，数量比较不证明具体设施或空间覆盖变化。']}
        if comparable:
            item.update(previous=previous, current=current,
                        offline_change=current['reported_offline'] - previous['reported_offline'],
                        alert_change=current['alert_count'] - previous['alert_count'])
        else:
            item['information_gaps'].append('两期摘要存在缺失、重叠、切分不一致或设备总数变化，不计算变化率。')
        items.append(item)
    return {'algorithm_version': VERSION, 'items': items,
            'information_gaps': [] if items else ['两期没有可读取的技防摘要，案件统计仍可使用。'],
            'boundary': '在线/离线数量使用每期最后一条摘要报告数，不跨时段累加；事件数量仅对无重叠完整区间求和。'}


def tech_recommendations(snapshot, area_name):
    items = []
    for item in sorted(snapshot['items'], key=lambda row: (-row.get('offline_change', 0), row['source_id'], row['device_type'])):
        if item['state'] != 'comparable' or item['offline_change'] < 1:
            continue
        population = item['current']['reported_device_count']
        if population <= 0 or item['offline_change'] / population < 0.1:
            continue
        items.append({'title': '关注同源技防摘要报告的离线数量增加', 'target_area': area_name,
            'time_window': '本建议有效期内，设备即时状态仍须确认',
            'suggested_action': '确认来源摘要对应的设备可用情况，并结合设施位置判断是否需要人工调整现有覆盖安排。',
            'resource_assumption': '未取得设备级资源清单，不预设替补点位、人员或维修任务。',
            'expected_effect': '提示已报告的可用性变化，不证明具体空间盲区或实际防控效果。',
            'supporting_evidence': [f"来源 {item['source_id']} / {item['device_type']}：末条摘要离线数由 {item['previous']['reported_offline']} 增至 {item['current']['reported_offline']}。",
                '初始关注规则：离线增加至少1台且占报告设备总数至少10%；未经实效校准。'],
            'evidence_refs': item['evidence_refs'], 'information_gaps': item['information_gaps'], 'confidence': 0.0})
    return items[:1]
