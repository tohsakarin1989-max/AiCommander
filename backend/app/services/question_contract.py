"""One bounded question/requirements contract for rule and model entry points.

Question interpretation is not an evidence source. Completion is derived from
validated tool output, never the planner's claim that it has finished.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VERSION = 'answer-snapshot-9.3-1'
TIME_LABELS = {'discovery': '发现／查获', 'incident': '案发', 'entry': '录入'}


class TimeScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    time_basis: Literal['discovery', 'incident', 'entry'] = 'incident'
    start: str | None = None
    end: str | None = None
    as_of: str | None = None
    period: str | None = None
    timezone: str = 'Asia/Shanghai'
    unknown_policy: str = 'separate_unknown_never_substitute_entry'
    interval_policy: str = 'possible_overlap_not_exact_occurrence'


class QuestionSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: str = 'question-spec-9.3-1'
    goal: str
    source_context: dict = Field(default_factory=dict)
    time_scope: TimeScope = Field(default_factory=TimeScope)
    required_points: list[str]
    interpretation: str = 'explicit_rule'


POINTS = {
    'case_history': ['historical_reference', 'differences', 'coverage'],
    'attention': ['categorized_basis', 'limitations'],
    'recent_changes': ['equal_periods', 'change_origins', 'unknown_times'],
    'count': ['authorized_total'],
    'comparison': ['comparable_values', 'differences'],
    'history': ['historical_reference', 'differences', 'coverage'],
    'lookup': ['source_records'],
    'material': ['frozen_material'],
}


def make_question_spec(question='', *, question_type=None, context=None, preset=None):
    context = context or {}
    conditions = context.get('conditions', {})
    filters = conditions.get('case_filters', {})
    source = context if question_type else {**filters, **((preset or {}).get('arguments') or {})}
    goal = question_type
    if goal is None:
        tool = (preset or {}).get('name')
        goal = {'case_count': 'count', 'case_process': 'lookup', 'case_result': 'material',
                'facility_dossier': 'lookup', 'facility_history': 'lookup',
                'coverage_scenario': 'comparison'}.get(tool)
    if goal is None:
        # Conservative requirements only, not a hidden natural-language executor.
        goal = ('history' if any(word in question for word in ('历史参考', '相似案件', '历史相似')) else
                'comparison' if any(word in question for word in ('比较', '对比', '变化', '差异')) else
                'count' if any(word in question for word in ('多少', '数量', '统计')) else 'lookup')
    basis = source.get('time_basis') or ('discovery' if question_type else 'incident')
    time_scope = TimeScope(time_basis=basis, start=source.get('start_date') or source.get('start'),
        end=source.get('end_date') or source.get('end'), as_of=source.get('as_of'), period=source.get('period'))
    return QuestionSpec(goal=goal, source_context=source, time_scope=time_scope,
        required_points=POINTS[goal], interpretation='explicit_rule' if question_type or preset else
        'bounded_requirements_not_language_acceptance').model_dump(mode='json')


def explicit_business_question(question, initial_context=None):
    """Exact documented shortcuts, not an asserted general language capability."""
    titles = {'这条记录有什么历史参考': 'case_history', '这片区域或这口井有哪些关注依据': 'attention',
              '最近发生了哪些实质变化': 'recent_changes'}
    kind = titles.get(question.strip().rstrip('？?。'))
    if kind is None:
        return None
    initial = initial_context or {}
    filters = initial.get('filters') or {}
    if any(key not in {'case_id', 'operational_area_id', 'time_basis'}
           and value is not None and value != [] for key, value in filters.items()):
        return None  # Never discard a keyword/type/date to force a shortcut.
    context = {}
    for key, value in {'case_id': initial.get('source_case_id') or filters.get('case_id'),
                       'area_id': filters.get('operational_area_id'),
                       'time_basis': filters.get('time_basis')}.items():
        if value is not None:
            context[key] = value
    return kind, context


def assess_requirements(spec, cards):
    """Return auditable missing answer points, including successful-but-wrong tools."""
    tools = {card.get('tool'): card for card in cards}
    met = set()
    for tool, card in tools.items():
        data = card.get('data') or {}
        if tool == 'count_cases' and 'count' in data:
            met.add('authorized_total')
        if tool in {'find_cases', 'find_places', 'find_case_profiles'} and 'total' in data:
            met.add('authorized_total')
        if tool == 'aggregate_case_profiles' and data.get('coverage', {}).get('complete'):
            met.update(('authorized_total', 'coverage'))
        if tool in {'compare_periods', 'business_recent_changes', 'compare_coverage_scenario'}:
            met.update(('comparable_values', 'differences', 'equal_periods'))
        if tool == 'business_recent_changes':
            met.update(('change_origins', 'unknown_times'))
        if tool == 'find_history':
            items = data.get('items') or []
            if items:
                met.add('historical_reference')
            if items and all('different_conditions' in item or item.get('contrast_evidence') for item in items):
                met.add('differences')
            if data.get('coverage', {}).get('complete'):
                met.add('coverage')
        if tool == 'business_attention':
            met.update(('categorized_basis', 'limitations'))
        if tool in {'find_cases', 'find_places', 'find_case_profiles', 'read_case_process',
                    'read_facility_dossier', 'read_facility_at'} and card.get('state') in {'ready', 'empty'}:
            met.add('source_records')
        if tool in {'explain_case_result', 'read_business_result', 'find_business_results', 'summarize_results'}:
            met.add('frozen_material')
        # A lookup can intentionally be answered by an authorized statistic or
        # an existing material; a comparison cannot be answered by either alone.
        if card.get('state') in {'ready', 'empty'}:
            met.add('source_records')
    required = spec['required_points']
    missing = [point for point in required if point not in met]
    return {'schema_version': 'answer-requirements-9.3-1', 'required': required,
            'satisfied': [point for point in required if point in met], 'missing': missing}


POINT_LABELS = {'historical_reference': '有出处的历史参考', 'differences': '关键差异或反向依据',
    'coverage': '完整检索范围', 'categorized_basis': '分类关注依据', 'limitations': '适用限制',
    'equal_periods': '同口径等长周期', 'change_origins': '变化来源', 'unknown_times': '未知与跨期时间',
    'authorized_total': '完整授权范围统计', 'comparable_values': '可比较的数值或条件',
    'source_records': '可核对的业务来源', 'frozen_material': '已有冻结材料'}


def unify_answer(answer, cards, spec, *, status=None, model_used=False):
    """Keep legacy schema identifiers readable, converge all new answer fields."""
    requirements = assess_requirements(spec, cards)
    gaps = list(answer.get('unanswered', answer.get('information_gaps', [])))
    gaps.extend('尚未回答：' + POINT_LABELS[point] + '。' for point in requirements['missing'])
    explicit = answer.get('completeness')
    completeness = explicit or ('service_unavailable' if not cards else
        'partial' if requirements['missing'] or any(card.get('state') in {'partial', 'unavailable'} for card in cards)
        else 'answered')
    if explicit == 'answered' and requirements['missing']:
        completeness = 'partial'
    if status in {'failed', 'degraded'} and completeness == 'answered':
        completeness = 'partial'
    evidence = answer.get('evidence') or [
        {'text': row['text'], 'evidence_refs': row['evidence_refs']} for row in answer.get('findings', [])]
    versions = answer.get('time_scope_versions') or {
        'source_context': spec['source_context'], 'algorithm_version': VERSION,
        'answered_at': datetime.now(timezone.utc).isoformat(), 'source_versions': [], 'scope_version': ''}
    direct = answer.get('direct_answer')
    if direct is None:
        direct = ' '.join(row['text'] for row in answer.get('findings', [])[:3]) or answer.get('summary', '当前没有足够依据回答。')
    if not explicit and completeness == 'partial':
        direct = '当前仅能部分回答。' + direct
    return {**answer, 'answer_contract_version': VERSION, 'question_spec': spec,
        'answer_requirements': requirements, 'completeness': completeness,
        'direct_answer': direct, 'summary': direct, 'evidence': evidence,
        'differences': answer.get('differences', []), 'unanswered': list(dict.fromkeys(gaps)),
        'information_gaps': list(dict.fromkeys(gaps)), 'time_scope_versions': versions,
        'time_scope': spec['time_scope'], 'capabilities': {
            'rule_answering': 'enabled', 'model_enhancement': 'used_in_this_run' if model_used else 'not_used',
            'model_acceptance': 'not_established_by_this_result'}}
