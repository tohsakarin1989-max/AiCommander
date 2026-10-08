"""8.2 explicit time bases and source changes over the whole authorized scope.

The old situation_change_service remains the legacy incident-time contract.
This module never substitutes entry time for a missing observation/incident.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json

from sqlalchemy import func

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_source import CaseRevision, DomainChange
from app.models.user import AuditLog
from app.services.situation_change_service import BUSINESS_TIMEZONE, ComparisonWindow
from app.services.situation_semantic_changes import semantic_window, semantic_changes

VERSION = 'situation-temporal-8.2-1'
BASES = {'discovery': '发现／查获', 'incident': '案发', 'entry': '录入'}
WITHDRAWAL_ACTION = 'case.record.withdrawn.v82'


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def closed_window(as_of, period):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('situation_timezone_required')
    end = as_of.astimezone(BUSINESS_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'weekly':
        end -= timedelta(days=end.weekday())
        length = timedelta(days=7)
    elif period == 'daily':
        length = timedelta(days=30)
    else:
        raise ValueError('invalid_period_type')
    end = end.astimezone(timezone.utc)
    return ComparisonWindow(end - 2 * length, end - length, end)


def time_range(case, basis):
    """Return a supported point or closed source interval, without guessing."""
    if basis in ('discovery', 'entry'):
        value = instant(getattr(case, 'discovered_at' if basis == 'discovery' else 'created_at'))
        return (value, value) if value else None
    if case.time_precision == 'exact':
        value = instant(case.occurred_time)
        return (value, value) if value else None
    if case.time_precision == 'interval':
        start, end = instant(case.occurred_from), instant(case.occurred_to)
        return (start, end) if start and end and end >= start else None
    # Pre-contract occurred_time does not certify that it was an incident time.
    return None


def membership(value, start, end):
    if value is None:
        return 'unknown'
    lower, upper = value
    if start <= lower and upper < end:
        return 'included'
    if lower < end and upper >= start:
        return 'uncertain'
    return 'outside'


def _scope(db, area_id):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('situation_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if allowed is not None and area_id not in allowed:
        raise PermissionError('situation_area_forbidden')


def record_withdrawal(db, case):
    """Same transaction as deletion; retain no case text, person or coordinates."""
    db.add(AuditLog(user_id=db.info.get('principal_user_id'), action=WITHDRAWAL_ACTION,
        detail={'schema': VERSION, 'operational_area_id': case.operational_area_id,
                'subject_kind': 'withdrawn_record',
                'boundary': '记录被删除或撤回，不表示现场情况没有发生。'}))


def case_changes(db, area_id, window, time_basis='discovery'):
    _scope(db, area_id)
    if time_basis not in BASES:
        raise ValueError('invalid_situation_time_basis')
    if not (window.previous_start < window.current_start < window.current_end) or (
            window.current_end - window.current_start != window.current_start - window.previous_start):
        raise ValueError('invalid_situation_comparison_window')
    # One explicit area and the request's current row policy. No recent-N cap.
    cases = db.query(Case).filter(Case.operational_area_id == area_id).populate_existing().order_by(Case.id).all()
    ranges = {case.id: time_range(case, time_basis) for case in cases}
    revisions = dict(db.query(CaseRevision.case_id, func.max(CaseRevision.id))
        .join(Case, Case.id == CaseRevision.case_id)
        .filter(Case.operational_area_id == area_id).group_by(CaseRevision.case_id).all())

    def snapshot(start, end):
        selected = [case for case in cases if membership(ranges[case.id], start, end) == 'included']
        ambiguous = [case.id for case in cases if membership(ranges[case.id], start, end) == 'uncertain']
        progress = db.query(CaseAnalysisProfile).join(Case, Case.id == CaseAnalysisProfile.case_id).filter(
            Case.operational_area_id == area_id, CaseAnalysisProfile.created_at >= start,
            CaseAnalysisProfile.created_at < end)
        dimensions = {}
        for field in ('case_type', 'oil_type'):
            counts = Counter(getattr(case, field) for case in selected)
            dimensions[field] = [{'value': value, 'count': count} for value, count in
                                 sorted(counts.items(), key=lambda pair: (pair[0] is None, pair[0] or ''))]
        identifiers = [case.id for case in selected]
        return {'start': start.isoformat(), 'end': end.isoformat(), 'case_count': len(selected),
                'case_ids': identifiers, 'uncertain_case_ids': ambiguous, 'uncertain_count': len(ambiguous),
                'dimensions': dimensions, 'profile_versions_generated': progress.count(),
                'profile_case_ids': [row[0] for row in progress.with_entities(CaseAnalysisProfile.case_id)
                                     .distinct().order_by(CaseAnalysisProfile.case_id).all()]}

    previous = snapshot(window.previous_start, window.current_start)
    current = snapshot(window.current_start, window.current_end)
    semantics = semantic_changes(
        semantic_window(db, area_id, window.previous_start, window.current_start, case_ids=previous['case_ids']),
        semantic_window(db, area_id, window.current_start, window.current_end, case_ids=current['case_ids']))
    newly_entered = [case for case in cases if membership(time_range(case, 'entry'), window.current_start,
                                                         window.current_end) == 'included']
    recent, late, entry_unknown = [], [], []
    for case in newly_entered:
        # When reading entry progress, separately explain the observation date;
        # do not make entry time its own proof of a new incident.
        reference = time_range(case, 'discovery' if time_basis == 'entry' else time_basis)
        if reference is None:
            entry_unknown.append(case.id)
        elif reference[1] < window.current_start:
            late.append(case.id)
        elif membership(reference, window.current_start, window.current_end) == 'included':
            recent.append(case.id)
        else:
            entry_unknown.append(case.id)
    corrections = db.query(DomainChange, CaseRevision).join(CaseRevision,
        CaseRevision.id == DomainChange.source_revision_id).join(Case, Case.id == CaseRevision.case_id).filter(
        Case.operational_area_id == area_id, DomainChange.change_type != 'created',
        DomainChange.created_at >= window.current_start, DomainChange.created_at < window.current_end)
    correction_rows = [{'case_id': revision.case_id, 'revision_id': revision.id,
                        'change_id': change.id, 'change_type': change.change_type}
                       for change, revision in corrections.order_by(DomainChange.id).all()]
    # Audit rows have no case FK by design; only the retained area is consulted,
    # after explicit current authorization. Never read generic HTTP audit bodies.
    withdrawals = db.query(AuditLog.id).filter(AuditLog.action == WITHDRAWAL_ACTION,
        AuditLog.detail['operational_area_id'].as_integer() == area_id,
        AuditLog.created_at >= window.current_start.replace(tzinfo=None),
        AuditLog.created_at < window.current_end.replace(tzinfo=None)).order_by(AuditLog.id).all()
    unknown = [case.id for case in cases if ranges[case.id] is None]
    unclear_place = [case.id for case in cases if not (case.location or '').strip()]
    missing_conditions = [case.id for case in cases if not (case.modus_operandi or '').strip()]
    manifest = [{'case_id': case.id, 'revision_id': revisions.get(case.id),
                 'time_value': [part.isoformat() for part in ranges[case.id]] if ranges[case.id] else None,
                 'case_type': case.case_type, 'oil_type': case.oil_type}
                for case in cases]
    origins = {
        'recent_registered': {'case_ids': recent, 'count': len(recent), 'label': '本期发现并录入（不等于本期发生）' if time_basis != 'incident' else '本期案发并录入'},
        'late_entry': {'case_ids': late, 'count': len(late), 'label': '本期补录的历史情况'},
        'entry_time_uncertain': {'case_ids': entry_unknown, 'count': len(entry_unknown), 'label': '本期录入但业务时间未知或跨周期'},
        'corrections': {'items': correction_rows, 'count': len(correction_rows), 'label': '本期原记录修订次数（非新增案件数）'},
        'withdrawals': {'audit_ids': [row[0] for row in withdrawals], 'count': len(withdrawals), 'label': '本期记录撤回／删除次数'},
        'boundary': '新增与补录按所选业务时间和录入时间区分；修订、撤回可重叠，不与案件数量相加。旧版本未保留撤回依据的部分无法补推。',
    }
    return {'algorithm_version': VERSION, 'timezone': 'Asia/Shanghai', 'time_basis': time_basis,
        'time_basis_label': BASES[time_basis], 'operational_area_id': area_id,
        'previous': previous, 'current': current, 'case_count_change': current['case_count'] - previous['case_count'],
        'source_manifest': manifest, 'change_origins': origins, 'semantic_changes': semantics,
        'quality': {'denominator': len(cases), 'denominator_label': '当前授权区域全部已登记记录',
            'unknown_time_count': len(unknown), 'unknown_time_case_ids': unknown,
            'unknown_time_ratio': len(unknown) / len(cases) if cases else None,
            'unclear_place_count': len(unclear_place), 'unclear_place_ratio': len(unclear_place) / len(cases) if cases else None,
            'unstructured_method_count': len(missing_conditions),
            'unstructured_method_ratio': len(missing_conditions) / len(cases) if cases else None,
            'boundary': '未填写结构化手法仅表示该字段缺失，不能证明原文或现实不存在该条件。'},
        'comparability': {'state': 'comparable', 'scope': [area_id], 'time_basis': time_basis,
            'equal_length': window.current_end - window.current_start == window.current_start - window.previous_start,
            'boundary': '同一当前授权范围和口径下的登记数量，不是发生率；未知及跨周期时间单列，不参与确定数量。'},
        'input_signature': hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'boundary': f'按{BASES[time_basis]}时间统计登记数量，未知不以录入时间替代；地图及道路资料更新不改变案件数量。区间左闭右开。'}


def snapshot_difference(db, previous, current):
    """Explain revisions to a frozen result, without leaking a withdrawn scope."""
    _scope(db, current['operational_area_id'])
    keys = ('algorithm_version', 'time_basis', 'operational_area_id')
    if any(previous.get(key) != current.get(key) for key in keys) or any(
            previous.get(part, {}).get(key) != current[part][key]
            for part in ('previous', 'current') for key in ('start', 'end')):
        return {'state': 'incomparable', 'items': [], 'reason': '范围、时间口径、周期或算法版本不同，不直接比较数量。'}
    old = {row['case_id']: row for row in previous.get('source_manifest', [])}
    new = {row['case_id']: row for row in current['source_manifest']}
    visible = {row[0] for row in db.query(Case.id).filter(Case.id.in_(old),
        Case.operational_area_id == current['operational_area_id']).all()}
    if visible != set(old):
        return {'state': 'incomparable', 'items': [], 'reason': '历史来源已撤回、不存在或不在当前范围，隐藏原数量和明细。'}
    added = sorted(set(new) - set(old))
    changed = sorted(key for key in set(old) & set(new) if old[key] != new[key])
    return {'state': 'comparable', 'items': [
        {'kind': 'records_added', 'case_ids': added, 'label': '新增登记；请结合补录分类，不直接视为近期新发生'},
        {'kind': 'records_revised', 'case_ids': changed, 'label': '原记录内容或时间更正'}],
        'material_changed': bool(added or changed), 'boundary': '来源修订影响统计解释，不自动判断因果。'}
