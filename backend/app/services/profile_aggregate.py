"""Whole-authorized-corpus profile aggregation, without extraction or business writes.

Only presentation is paginated. Every member is classified once; incomplete
scans and unavailable profiles are explicit, never interpreted as negative facts.
The private source manifest is retained by topic snapshots, not sent to models.
"""
from collections import Counter, defaultdict
from time import monotonic

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_search_service import CaseSearchService
from app.services.case_semantic_evidence import ASSERTION_KINDS, SourceText, TextReference
from app.services.topic_model_evidence import BOUNDARY as MODEL_BOUNDARY, model_evidence


VERSION = 'profile-aggregate-5.3-1'
CATEGORIES = ('method', 'oil', 'facility', 'place_condition', 'time_condition',
              'tool', 'vehicle', 'upstream_clue', 'downstream_clue')
BOUNDARY = ('分析案组仅表示原文条件相似，不等于正式串并案、真实团伙或当前案件事实。'
            '缺少表述不等于现实中不存在；引用校验不代表原文内容已证实。')


def checked_profile(db, case, profile, *, current_hash=None):
    """Validate all assertions in an existing profile, not only its first page."""
    if profile is None:
        return [], 'missing'
    if profile.source_hash != (current_hash or CasePipelineService.source_hash(db, case)):
        return [], 'stale'
    try:
        semantics = profile.payload['semantics']
        fields = semantics['source_snapshot']['fields']
        sources = {entry['field']: SourceText(**entry) for entry in fields}
        if len(fields) != len(sources):
            raise ValueError('duplicate_source')
        assertions = semantics['assertions']
        if not isinstance(assertions, list):
            raise ValueError('invalid_assertions')
        for assertion in assertions:
            reference = TextReference(**assertion['reference'])
            reference.validate(sources[reference.field])
            if assertion['kind'] not in ASSERTION_KINDS or any(
                not isinstance(assertion.get(key), str) or not assertion[key].strip()
                for key in ('category', 'value')
            ):
                raise ValueError('invalid_assertion')
        # Extraction limits affect completeness, even if every available quote validates.
        incomplete = any(isinstance(gap, dict) and gap.get('code') == 'extraction_limit'
                         for gap in semantics.get('information_gaps', []))
        return assertions, 'partial' if incomplete else 'ready'
    except (KeyError, TypeError, ValueError, AttributeError):
        return [], 'invalid'


def _states(assertions):
    values = defaultdict(set)
    for item in assertions:
        values[item['category'], item['value']].add(item['kind'])
    return {key: ('conflicting' if {'stated', 'negated'} <= kinds else None, kinds)
            for key, kinds in values.items()}


def _condition_state(condition, states, profile_state):
    if profile_state not in {'ready', 'partial'}:
        return 'unknown'
    candidates = [entry for (category, value), entry in states.items()
                  if category == condition.category and (condition.value is None or value == condition.value)]
    if condition.kind == 'missing':
        if candidates:
            return 'unmatched'
        return 'matched' if profile_state == 'ready' else 'unknown'
    if not candidates:
        # An unmentioned term is not evidence of negation or a failed condition.
        return 'unknown'
    if condition.kind == 'conflicting':
        return 'matched' if any(conflict for conflict, _ in candidates) else 'unmatched'
    if any(not conflict and condition.kind in kinds for conflict, kinds in candidates):
        return 'matched'
    return 'unmatched'


def build_aggregate(db, args, *, deadline=None, cancelled=lambda: False):
    """Return a frozen derived result and source references for subsequent access checks.

    No recent-N cutoff. The deadline is a computation budget, not a hidden dataset
    limit: if reached, all totals clearly describe only the visited population.
    """
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('query_read_scope_required')
    allowed = db.info['authorized_area_ids']
    if (args.operational_area_id is not None and allowed is not None
            and args.operational_area_id not in allowed):
        raise PermissionError('query_area_forbidden')
    deadline = deadline if deadline is not None else monotonic() + 90
    filters = args.model_dump(exclude={'conditions', 'page', 'page_size'})
    query = CaseSearchService.filtered_query(db, **filters)
    base_total = query.count()
    states, missing, counts, patterns = Counter(), Counter(), Counter(), defaultdict(list)
    model_states, model_candidate_count = Counter(), 0
    members, counterexamples, unknown, sources = [], [], [], []
    condition_counts = [Counter() for _ in args.conditions]
    after_id = 0
    complete = True
    while True:
        if cancelled():
            raise PermissionError('query_cancelled')
        if monotonic() >= deadline:
            complete = False
            break
        cases = query.filter(Case.id > after_id).order_by(Case.id).limit(100).all()
        if not cases:
            break
        ids = [case.id for case in cases]
        profiles = {}
        for profile in db.query(CaseAnalysisProfile).filter(
            CaseAnalysisProfile.case_id.in_(ids), CaseAnalysisProfile.is_current.is_(True)
        ).order_by(CaseAnalysisProfile.profile_version.desc(), CaseAnalysisProfile.id):
            profiles.setdefault(profile.case_id, profile)
        for case in cases:
            if cancelled():
                raise PermissionError('query_cancelled')
            if monotonic() >= deadline:
                complete = False
                break
            profile = profiles.get(case.id)
            current_hash = CasePipelineService.source_hash(db, case)
            assertions, state = checked_profile(db, case, profile, current_hash=current_hash)
            model = model_evidence(profile, state)
            model_states[model['state']] += 1
            model_candidate_count += len(model['items'])
            from app.services.intelligent_query_context import result_hash
            states[state] += 1
            source = {'case_id': case.id, 'operational_area_id': case.operational_area_id,
                      'profile_id': profile.id if profile else None,
                      'source_hash': profile.source_hash if profile else None,
                      'profile_version': profile.profile_version if profile else None,
                      'profile_content_sha256': result_hash(profile.payload) if profile else None,
                      'case_source_hash': current_hash,
                      'state': state}
            sources.append(source)
            by_term = _states(assertions)
            for category in CATEGORIES:
                if state == 'ready' and not any(key[0] == category for key in by_term):
                    missing[category] += 1
            judgments = [_condition_state(condition, by_term, state) for condition in args.conditions]
            for index, judgment in enumerate(judgments):
                condition_counts[index][judgment] += 1
            match = ('unmatched' if 'unmatched' in judgments else
                     'unknown' if 'unknown' in judgments else 'matched')
            counts[match] += 1
            ref = {'case_id': case.id, 'profile_id': source['profile_id'],
                   'profile_version': source['profile_version'], 'profile_state': state,
                   'condition_states': judgments, 'evidence_ref': f'case:{case.id}'}
            if match == 'matched':
                members.append(ref)
                for (category, value), (conflict, kinds) in by_term.items():
                    # Explicit conflicts are a separate group, not two corroborating facts.
                    for kind in (['conflicting'] if conflict else sorted(kinds)):
                        patterns[category, value, kind].append(case.id)
            elif match == 'unmatched':
                counterexamples.append(ref)
            else:
                unknown.append(ref)
        if not complete:
            break
        after_id = cases[-1].id
    scanned = len(sources)
    # Concurrent insertion/deletion cannot silently turn a partial scan into a census.
    if scanned != base_total or query.count() != base_total:
        complete = False
    rows = [{'category': category, 'value': value, 'kind': kind,
             'case_count': len(ids), 'case_ids': ids}
            for (category, value, kind), ids in sorted(patterns.items())]
    unavailable = sum(states[state] for state in ('missing', 'stale', 'invalid', 'partial'))
    result = {
        'schema_version': VERSION,
        'filters': args.model_dump(mode='json', exclude={'page', 'page_size'}),
        'coverage': {'authorized_cases': base_total, 'scanned_cases': scanned, 'complete': complete,
                     'profiles_complete': unavailable == 0, 'profile_states': dict(sorted(states.items()))},
        'statistics': {'matched': counts['matched'], 'unmatched': counts['unmatched'],
                       'unknown': counts['unknown'], 'denominator': scanned,
                       'unavailable_profile_count': unavailable,
                       'unavailable_profile_ratio': unavailable / scanned if scanned else None},
        'condition_statistics': [
            {'condition': condition.model_dump(), **{kind: count[kind] for kind in ('matched', 'unmatched', 'unknown')}}
            for condition, count in zip(args.conditions, condition_counts)
        ],
        'missingness': [{'category': category, 'missing_count': missing[category],
                         'denominator': states['ready'],
                         'ratio': missing[category] / states['ready'] if states['ready'] else None}
                        for category in CATEGORIES],
        'members': members, 'counterexamples': counterexamples, 'unknown': unknown,
        'model_extraction': {'profile_states': dict(sorted(model_states.items())),
                             'candidate_count': model_candidate_count, 'boundary': MODEL_BOUNDARY},
        'patterns': rows, 'source_manifest': sources, 'boundary': BOUNDARY,
    }
    return result


def present_aggregate(result, *, page=1, page_size=20):
    """Model/UI view: small representative page, but full-corpus denominators."""
    start = (page - 1) * page_size
    patterns = result['patterns']
    return {key: value for key, value in result.items()
            if key not in {'members', 'counterexamples', 'unknown', 'source_manifest', 'patterns'}} | {
        'total': result['statistics']['matched'], 'page': page, 'page_size': page_size,
        'items': result['members'][start:start + page_size],
        'counterexamples': result['counterexamples'][:3], 'unknown_examples': result['unknown'][:3],
        'patterns': [{**row, 'case_ids': row['case_ids'][:3], 'examples_only': True}
                     for row in patterns[start:start + page_size]],
        'pattern_total': len(patterns),
        'presentation_boundary': '总体计数来自全部已遍历案件；案例和条件列表均为分页展示，不代表全部成员。',
    }


def aggregate_results(db, args, *, deadline=None, cancelled=lambda: False):
    snapshot = build_aggregate(db, args, deadline=deadline, cancelled=cancelled)
    partial = not all(snapshot['coverage'][key] for key in ('complete', 'profiles_complete'))
    return present_aggregate(snapshot, page=args.page, page_size=args.page_size), partial
