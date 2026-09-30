"""Actual references plus conservative selection-range invalidation.

The selected corpus can gain a previously unseen case or a new road shortcut;
therefore absence from the old reference list is never treated as unaffected.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import delete, insert, update, select, or_, and_, inspect

from app.models.analysis_topic import AnalysisTopic, TopicDependency, TopicDataRevision
from app.models.case_pipeline import OutboxEvent
from app.services.topic_revision_fence import SOURCE_TABLES, current_revision

EVENT_TYPE = 'topic.source.changed'


def record_session_changes(session):
    """after_flush hook; metadata only, Core insert avoids recursive session flush."""
    changed = []
    for obj in set(session.new) | set(session.dirty) | set(session.deleted):
        table = getattr(obj, '__tablename__', '')
        if table not in SOURCE_TABLES:
            continue
        if obj in session.dirty and not session.is_modified(obj, include_collections=False):
            continue
        changed.append({'kind': table, 'id': str(getattr(obj, 'id', '')),
                        'area_id': getattr(obj, 'operational_area_id', None)})
    if not changed:
        return
    connection = session.connection()
    # Core business writes remain usable during an old-source migration test.
    # Actual topic jobs still require the installed fence and fail explicitly.
    if not connection.info.get('topic_v64_schema_ready'):
        if not inspect(connection).has_table('topic_data_revision'):
            return
        connection.info['topic_v64_schema_ready'] = True
    identifier = str(uuid4())
    revision = current_revision(session)
    session.connection().execute(insert(OutboxEvent.__table__).values(id=identifier,
        event_type=EVENT_TYPE, aggregate_type='topic_source', aggregate_id=identifier,
        idempotency_key=identifier, payload={'sources': changed[:100], 'conservative': len(changed) > 100,
                                           'data_revision': revision},
        status='pending', attempts=0, available_at=datetime.now(timezone.utc)))


def register_dependencies(db, topic, snapshot):
    db.execute(delete(TopicDependency).where(TopicDependency.topic_id == topic.id))
    refs = [('selection_scope', str(topic.filters.get('operational_area_id') or 'authorized'), topic.scope_version)]
    for item in snapshot.payload['aggregate']['source_manifest']:
        refs.append(('cases', str(item['case_id']), str(item.get('source_revision_id') or item['case_source_hash'])))
        if item['profile_id']:
            refs.append(('case_analysis_profiles', item['profile_id'], item['profile_content_sha256']))
    for kind, key in [('case_result_snapshots', 'case_results'), ('case_road_artifacts', 'roads'),
                      ('map_snapshots', 'maps'), ('situation_briefs', 'briefs')]:
        for item in snapshot.payload.get('references', {}).get(key, []):
            refs.append((kind, item['id'], item.get('content_sha256') or item.get('version')))
    source = (snapshot.payload.get('definition') or {}).get('source_context')
    if source and source['kind'] == 'facility':
        refs.append(('jurisdiction_assets', str(source['id']), None))
    for kind, identifier, version in set(refs):
        db.add(TopicDependency(id=str(uuid4()), topic_id=topic.id, snapshot_id=snapshot.id,
            kind=kind, object_id=identifier, source_version=version))


def consume_changes(db):
    """Combine up to 100 committed notifications; one pending generation per topic."""
    events = db.query(OutboxEvent).filter_by(event_type=EVENT_TYPE, status='pending').order_by(
        OutboxEvent.created_at, OutboxEvent.id).limit(100).with_for_update(skip_locked=True).all()
    if not events:
        return 0
    # Use scopes only for conservative scheduling, never for returning business data.
    sources = [source for event in events for source in event.payload.get('sources', [])]
    areas = {source.get('area_id') for source in sources}
    unrestricted = None in areas or any(event.payload.get('conservative') for event in events)
    now = datetime.now(timezone.utc)
    pairs = {(source['kind'], source['id']) for source in sources}
    dependent_ids = set()
    pairs = sorted(pairs)
    for offset in range(0, len(pairs), 200):
        dependent_ids.update(row.topic_id for row in db.query(TopicDependency.topic_id).filter(or_(
            *(and_(TopicDependency.kind == kind, TopicDependency.object_id == identifier)
              for kind, identifier in pairs[offset:offset + 200]))))
    topics = db.query(AnalysisTopic).filter(AnalysisTopic.paused.is_(False)).all()
    count = 0
    for topic in topics:
        if all(event.payload.get('data_revision', -1) <= topic.last_data_revision for event in events):
            continue
        area = topic.filters.get('operational_area_id')
        if topic.id not in dependent_ids and not unrestricted and area is not None and area not in areas:
            continue
        if topic.refresh_state == 'queued':
            continue
        topic.requested_generation += 1
        topic.refresh_state = 'queued'
        topic.next_refresh_at = now
        if topic.latest_job_id:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == topic.latest_job_id,
                OutboxEvent.status.in_(('pending', 'retry', 'processing'))).values(status='superseded', worker_id=None, lease_until=None))
        topic.latest_job_id = None
        count += 1
    for event in events:
        event.status = 'completed'
        event.processed_at = now
        event.payload = {**event.payload, 'policy': 'actual_references_and_selection_scope_conservative',
                         'data_revision': current_revision(db)}
    db.commit()
    return count
