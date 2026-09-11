"""Bounded follow-up conditions, separate from answers and access permissions."""
import copy
import hashlib
import json

from app.services.intelligent_query_tools import TOOLS, CaseFilters

VERSION = 'query-context-4.3-1'
CASE_TOOLS = {'find_cases', 'count_cases', 'compare_periods', 'find_road_results', 'find_case_profiles'}
PAGE_FIELDS = {'page', 'page_size', 'limit'}


def result_hash(result):
    return hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                    default=str, allow_nan=False).encode()).hexdigest()


def empty_conditions():
    return {'case_filters': {}, 'tool_defaults': {}, 'area': None}


def remember(conditions, tool, arguments):
    state = copy.deepcopy(conditions)
    values = TOOLS[tool].model_validate(arguments).model_dump(mode='json', exclude_unset=True)
    state['tool_defaults'][tool] = {k: v for k, v in values.items() if k not in PAGE_FIELDS}
    if 'operational_area_id' in values:
        state['area'] = values['operational_area_id']
    if tool in CASE_TOOLS:
        canonical = dict(values)
        if tool == 'compare_periods':
            canonical['start_date'] = canonical.pop('start')
            canonical['end_date'] = canonical.pop('end')
        for key, value in canonical.items():
            if key in CaseFilters.model_fields:
                if value is None:
                    state['case_filters'].pop(key, None)
                else:
                    state['case_filters'][key] = value
    return state


def inherit(tool, arguments, conditions, *, question, change_basis=None):
    fields = TOOLS[tool].model_fields
    if (tool in CASE_TOOLS - {'find_road_results'}
            and conditions['tool_defaults'].get('find_road_results', {}).get('min_detour_ratio') is not None):
        # A case count cannot represent a road-result filter. Require a road
        # query or an explicit, traced removal instead of counting all cases.
        raise ValueError('query_context_tool_cannot_preserve_filters')
    defaults = dict(conditions['tool_defaults'].get(tool, {}))
    if tool in CASE_TOOLS:
        defaults = {k: v for k, v in defaults.items() if k not in CaseFilters.model_fields and k not in {'start', 'end'}}
        defaults.update(conditions['case_filters'])
        if tool == 'compare_periods':
            for source, target in [('start_date', 'start'), ('end_date', 'end')]:
                if source in defaults:
                    defaults[target] = defaults.pop(source)
        # Do not silently discard e.g. status/keyword when a comparison tool
        # cannot represent it. The planner can use two filtered count calls.
        if any(k not in fields and v is not None for k, v in defaults.items()):
            raise ValueError('query_context_tool_cannot_preserve_filters')
    if conditions['area'] is not None:
        defaults['operational_area_id'] = conditions['area']
    effective = {**defaults, **arguments}
    normalized = TOOLS[tool].model_validate(effective).model_dump(mode='json', exclude_unset=True)
    changes = [{'field': key, 'previous': value, 'current': normalized.get(key)}
               for key, value in defaults.items()
               if key in arguments and normalized.get(key) != value]
    if changes:
        # A quote is traceable model interpretation, not proof of intent or an
        # authorization grant. execute_tool still checks current read scope.
        if not isinstance(change_basis, str) or len(change_basis.strip()) < 2 or change_basis not in question:
            raise ValueError('query_context_change_basis_required')
        for change in changes:
            change['basis'] = change_basis
    return normalized, changes


def freeze_context(parent):
    result = parent.result_summary or {}
    if parent.status not in {'completed', 'degraded'} or not result.get('cards'):
        raise ValueError('query_parent_not_ready')
    conditions = empty_conditions()
    # Rebuild from the already validated inherited state and actual tool trace;
    # never accept context or prior answers from the HTTP client.
    previous = (parent.input_payload or {}).get('followup_context')
    if previous:
        conditions = copy.deepcopy(previous['conditions'])
    for entry in result.get('trace', []):
        if entry.get('tool') in TOOLS and 'arguments' in entry and not entry.get('error_code'):
            conditions = remember(conditions, entry['tool'], entry['arguments'])
    context = {'schema_version': VERSION, 'parent_query_id': parent.id,
               'parent_scope_version': parent.data_version, 'parent_result_hash': result_hash(result),
               'previous_question': parent.query,
               'previous_completed_at': parent.completed_at.isoformat() if parent.completed_at else None,
               'conditions': conditions,
               'boundary': '继承的是筛选条件，不是授权；旧结果是历史快照，新查询仍须调用业务工具。'}
    if len(json.dumps(context, ensure_ascii=False).encode()) > 32_768:
        raise ValueError('query_context_limit')
    return context
