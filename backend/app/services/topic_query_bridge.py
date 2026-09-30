"""Reuse validated query conditions, not answers or arbitrary client context."""
from app.services.intelligent_query_context import CASE_TOOLS, freeze_context
from app.services.intelligent_query_tools import ProfileFilters


def save_query_as_topic(db, run_id, title, notes='', *, question=None, window=None):
    from app.services import intelligent_query_tasks as queries
    from app.services.analysis_topic_service import create_topic
    queries.read_query(db, run_id)
    row, _ = queries._owned(db, run_id)
    conditions = freeze_context(row)['conditions']
    values = dict(conditions['case_filters'])
    if conditions['area'] is not None:
        values['operational_area_id'] = conditions['area']
    # A similarity ranking, road ratio or result completion window is not an
    # equivalent case/profile selection. Do not silently broaden the topic.
    context = {'kind': 'query', 'id': run_id}
    question_kind = 'condition_changes'
    for tool, defaults in conditions['tool_defaults'].items():
        if tool == 'read_facility_dossier':
            if context['kind'] not in {'query', 'facility'} or (context['kind'] == 'facility' and context['id'] != defaults['asset_id']):
                raise ValueError('topic_query_conditions_unsupported')
            context = {'kind': 'facility', 'id': defaults['asset_id']}
            question_kind = 'facility_context'
            values.update({key: defaults[key] for key in ('start_date', 'end_date', 'operational_area_id') if defaults.get(key) is not None})
            continue
        if tool in {'read_case_process', 'explain_case_result'}:
            if defaults.get('result_id') is not None:
                # A selected historical result is not a request to follow the
                # current case. Keep it readable through the result reader.
                raise ValueError('topic_query_conditions_unsupported')
            if context['kind'] not in {'query', 'case'} or (context['kind'] == 'case' and context['id'] != defaults['case_id']):
                raise ValueError('topic_query_conditions_unsupported')
            context = {'kind': 'case', 'id': defaults['case_id']}
            question_kind = 'case_gaps'
            values['case_id'] = defaults['case_id']
            continue
        if tool not in CASE_TOOLS:
            raise ValueError('topic_query_conditions_unsupported')
        ignored = set(ProfileFilters.model_fields) | {'start', 'end'}
        if any(value is not None and key not in ignored for key, value in defaults.items()):
            raise ValueError('topic_query_conditions_unsupported')
        if tool == 'aggregate_case_profiles' and 'conditions' in defaults:
            values['conditions'] = defaults['conditions']
    return create_topic(db, title, ProfileFilters.model_validate(values).model_dump(mode='json'), notes,
                        question=question, question_kind=question_kind, window=window, source_context=context)


def query_topic(db, topic_id, revision, question):
    from app.services.analysis_topic_service import _owned, read_topic
    from app.services.intelligent_query_tasks import create_query
    topic = _owned(db, topic_id)
    read = read_topic(db, topic_id, revision=revision)
    source = {'topic_id': topic.id, 'revision': revision,
              'snapshot_id': read['snapshot']['id'], 'content_sha256': read['snapshot']['content_sha256']}
    # Empty filters are meaningful here: the saved topic explicitly selects all
    # authorized cases. It is not an accidentally empty page selection.
    selected_filters = (read['snapshot'].get('definition') or {}).get('resolved_filters') or read['snapshot']['aggregate'].get('filters', topic.filters)
    filters = {key: value for key, value in selected_filters.items() if value is not None}
    return create_query(db, question, initial_context={'filters': filters}, topic_source=source)


def validate_topic_source(db, source):
    if source is None:
        return
    from app.services.analysis_topic_service import read_topic
    try:
        snapshot = read_topic(db, source['topic_id'], revision=source['revision'])['snapshot']
        if (snapshot['id'], snapshot['content_sha256']) != (source['snapshot_id'], source['content_sha256']):
            raise ValueError('changed')
    except (ValueError, KeyError, TypeError) as error:
        raise PermissionError('query_topic_source_changed') from error
