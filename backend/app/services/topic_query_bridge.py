"""Reuse validated query conditions, not answers or arbitrary client context."""
from app.services.intelligent_query_context import CASE_TOOLS, freeze_context
from app.services.intelligent_query_tools import ProfileFilters


def save_query_as_topic(db, run_id, title, notes=''):
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
    for tool, defaults in conditions['tool_defaults'].items():
        if tool not in CASE_TOOLS:
            raise ValueError('topic_query_conditions_unsupported')
        ignored = set(ProfileFilters.model_fields) | {'start', 'end'}
        if any(value is not None and key not in ignored for key, value in defaults.items()):
            raise ValueError('topic_query_conditions_unsupported')
        if tool == 'aggregate_case_profiles' and 'conditions' in defaults:
            values['conditions'] = defaults['conditions']
    return create_topic(db, title, ProfileFilters.model_validate(values).model_dump(mode='json'), notes)


def query_topic(db, topic_id, revision, question):
    from app.services.analysis_topic_service import _owned, read_topic
    from app.services.intelligent_query_tasks import create_query
    topic = _owned(db, topic_id)
    read = read_topic(db, topic_id, revision=revision)
    source = {'topic_id': topic.id, 'revision': revision,
              'snapshot_id': read['snapshot']['id'], 'content_sha256': read['snapshot']['content_sha256']}
    # Empty filters are meaningful here: the saved topic explicitly selects all
    # authorized cases. It is not an accidentally empty page selection.
    filters = {key: value for key, value in topic.filters.items() if value is not None}
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
