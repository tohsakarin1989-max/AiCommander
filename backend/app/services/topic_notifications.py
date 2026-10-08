"""Read-only object-grouped changes and explicit exact-version dismissals."""
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.analysis_topic import AnalysisTopic, TopicSnapshot, TopicChangeDismissal


def _reference(topic, snapshot):
    return {'topic_id': topic.id, 'snapshot_id': snapshot.id,
            'revision': snapshot.revision, 'content_sha256': snapshot.content_sha256}


def daily_changes(db):
    from app.services.analysis_topic_service import _owner, validate_snapshot_access
    try:
        owner, scope = _owner(db)
    except PermissionError:
        return []
    with db.no_autoflush:
        latest = db.query(TopicSnapshot.topic_id, func.max(TopicSnapshot.revision).label('revision')).join(
            AnalysisTopic, AnalysisTopic.id == TopicSnapshot.topic_id).filter(
            AnalysisTopic.created_by == owner.id, AnalysisTopic.scope_version == scope,
            AnalysisTopic.paused.is_(False), AnalysisTopic.notification_policy == 'meaningful').group_by(
            TopicSnapshot.topic_id).subquery()
        rows = db.query(AnalysisTopic, TopicSnapshot).join(TopicSnapshot,
            TopicSnapshot.topic_id == AnalysisTopic.id).join(latest,
            (latest.c.topic_id == TopicSnapshot.topic_id) & (latest.c.revision == TopicSnapshot.revision)).outerjoin(
            TopicChangeDismissal, (TopicChangeDismissal.snapshot_id == TopicSnapshot.id)
            & (TopicChangeDismissal.created_by == owner.id)
            & (TopicChangeDismissal.content_sha256 == TopicSnapshot.content_sha256)).filter(
            TopicChangeDismissal.snapshot_id.is_(None)).order_by(
            TopicSnapshot.created_at.desc(), TopicSnapshot.id)
        groups = {}
        for topic, snapshot in rows:
            items = snapshot.changes.get('meaningful_items', [])
            if not snapshot.changes.get('material_changed') or not items:
                continue
            try:
                validate_snapshot_access(db, snapshot)
            except (PermissionError, ValueError, LookupError):
                continue  # No summary, count or withheld-source placeholder.
            definition = snapshot.payload.get('definition') or {}
            source = definition.get('source_context') or {}
            object_ref = ({'kind': source['kind'], 'id': source['id']}
                          if source.get('kind') in {'case', 'facility'} else None)
            key = (f"{object_ref['kind']}:{object_ref['id']}" if object_ref else
                   f"topic:{topic.id}:definition:{definition.get('revision', snapshot.revision)}")
            title = definition.get('title') or topic.title
            reference = {**_reference(topic, snapshot), 'title': title,
                         'target_path': f'/topics?topic={topic.id}&revision={snapshot.revision}'}
            group = groups.setdefault(key, {'group_key': key, 'object': object_ref,
                'topic_id': topic.id, 'title': title, 'revision': snapshot.revision,
                'summary': items[0]['message'], 'items': [], 'sources': [],
                'target_path': reference['target_path']})
            group['sources'].append(reference)
            for item in items:
                if item not in group['items']:
                    group['items'].append(item)
        # Select groups only after collecting every currently readable source.
        return list(groups.values())[:3]


def dismiss_changes(db, sources):
    from app.services.analysis_topic_service import _owner, _owned, validate_snapshot_access
    owner, _ = _owner(db)
    if not 1 <= len(sources) <= 100 or len({row['snapshot_id'] for row in sources}) != len(sources):
        raise ValueError('topic_change_reference_invalid')
    checked = []
    for ref in sources:
        topic = _owned(db, ref['topic_id'])
        snapshot = db.query(TopicSnapshot).filter_by(id=ref['snapshot_id'], topic_id=topic.id).first()
        if snapshot is None or _reference(topic, snapshot) != ref:
            raise ValueError('topic_change_reference_conflict')
        validate_snapshot_access(db, snapshot)
        if not snapshot.changes.get('material_changed'):
            raise ValueError('topic_change_reference_invalid')
        checked.append(ref)
    insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
    for ref in checked:
        db.execute(insert(TopicChangeDismissal).values(created_by=owner.id,
            snapshot_id=ref['snapshot_id'], content_sha256=ref['content_sha256']).on_conflict_do_nothing(
                index_elements=['created_by', 'snapshot_id']))
    db.commit()
    return {'sources': checked, 'dismissed': len(checked)}
