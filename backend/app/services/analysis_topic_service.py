"""Owner-scoped continuing topics. GETs only read; refreshes reuse stored profiles.

Every operation reloads current authorization. Background refresh has a durable
lease: pausing or requeuing invalidates late work, and a killed worker can recover.
No model, broker, road engine, case save or formal relationship write occurs here.
"""
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4

from sqlalchemy import or_, update

from app.models.analysis_topic import AnalysisTopic, TopicSnapshot, TopicDefinitionRevision
from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.user import User
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import _identity
from app.services.intelligent_query_tools import AggregateProfiles
from app.services.profile_aggregate import build_aggregate, present_aggregate
from app.services.case_semantic_evidence import SourceText, TextReference
from app.services.topic_projections import freeze_references, resolve_references, snapshot_views
from app.services.topic_definitions import (TopicWindow, record_definition, validate_source,
    validate_question, source_filters)
from app.services.topic_revision_fence import current_revision
from app.services.outbox_claim_service import OutboxClaimService


def _owner(db):
    user = _identity(db)
    if user.role not in {'admin', 'analyst'}:
        raise PermissionError('topic_role_forbidden')
    stamp = result_hash({'user_id': user.id, 'role': user.role, 'session_version': user.session_version,
                         'areas': db.info['authorized_area_ids']})
    return user, stamp


def _owned(db, topic_id):
    user, stamp = _owner(db)
    topic = db.query(AnalysisTopic).filter_by(id=topic_id, created_by=user.id).populate_existing().first()
    if topic is None:
        raise ValueError('topic_not_found')
    if topic.scope_version != stamp:
        raise PermissionError('topic_scope_changed')
    return topic


def _view(topic):
    return {'id': topic.id, 'title': topic.title, 'notes': topic.notes, 'filters': topic.filters,
            'question': topic.question or topic.title, 'question_kind': topic.question_kind,
            'window': topic.window, 'source_context': topic.source_context,
            'definition_revision': topic.definition_revision,
            'paused': topic.paused, 'refresh_state': topic.refresh_state, 'last_error': topic.last_error,
            'created_at': topic.created_at, 'next_refresh_at': topic.next_refresh_at}


def create_topic(db, title, filters, notes='', *, question=None, question_kind='condition_changes',
                 window=None, source_context=None):
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120 or len(notes) > 4000:
        raise ValueError('invalid_topic')
    args = AggregateProfiles.model_validate(filters)
    user, stamp = _owner(db)
    source_context = validate_source(db, source_context)
    validate_question(question_kind, source_context)
    window = TopicWindow.model_validate(window or {'mode': 'fixed'}).model_dump(exclude_none=True)
    question = question or title
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError('invalid_topic_question')
    if source_context and source_context['kind'] in {'case', 'facility'}:
        required = source_filters(db, source_context)
        values = args.model_dump(mode='json', exclude={'page', 'page_size'})
        for key, value in required.items():
            if values.get(key) not in (None, value):
                raise ValueError('topic_context_conflict')
            values[key] = value
        args = AggregateProfiles.model_validate(values)
    allowed = db.info['authorized_area_ids']
    if args.operational_area_id is not None and allowed is not None and args.operational_area_id not in allowed:
        raise PermissionError('topic_area_forbidden')
    # Bound durable queue admission and serialize concurrent creates per owner.
    db.execute(update(User).where(User.id == user.id).values(id=User.id))
    if db.query(AnalysisTopic).filter_by(created_by=user.id, paused=False).count() >= 100:
        db.rollback()
        raise ValueError('topic_capacity_reached')
    topic = AnalysisTopic(id=str(uuid4()), created_by=user.id, title=title.strip(), notes=notes,
        filters=args.model_dump(mode='json', exclude={'page', 'page_size'}), scope_version=stamp,
        question=question.strip(), question_kind=question_kind, window=window, source_context=source_context,
        definition_revision=1, requested_generation=1, last_data_revision=current_revision(db),
        paused=False, refresh_state='queued', next_refresh_at=datetime.now(timezone.utc))
    db.add(topic)
    db.flush()
    record_definition(db, topic)
    db.commit()
    return _view(topic)


def list_topics(db, *, page=1, page_size=20):
    user, stamp = _owner(db)
    query = db.query(AnalysisTopic).filter_by(created_by=user.id, scope_version=stamp)
    return {'total': query.count(), 'page': page, 'page_size': page_size,
            'items': [_view(row) for row in query.order_by(AnalysisTopic.created_at.desc(), AnalysisTopic.id)
                      .offset((page - 1) * page_size).limit(page_size)]}


def _snapshot(db, topic_id, revision=None):
    query = db.query(TopicSnapshot).filter_by(topic_id=topic_id)
    if revision is not None:
        query = query.filter_by(revision=revision)
    row = query.order_by(TopicSnapshot.revision.desc()).first()
    if revision is not None and row is None:
        raise ValueError('topic_snapshot_not_found')
    return row


def validate_snapshot_access(db, snapshot):
    """All members contribute to counts: withholding only a row would leak aggregates."""
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('topic_scope_required')
    if result_hash(snapshot.payload) != snapshot.content_sha256:
        raise PermissionError('topic_snapshot_invalid')
    validate_source(db, (snapshot.payload.get('definition') or {}).get('source_context'))
    validate_aggregate_access(db, snapshot.payload['aggregate'])
    change_ids = set().union(*(snapshot.changes.get(key, []) for key in (
        'added_case_ids', 'removed_case_ids', 'updated_case_ids', 'entered_group', 'left_group')))
    for offset in range(0, len(change_ids), 200):
        batch_ids = sorted(change_ids)[offset:offset + 200]
        visible = {row.id for row in db.query(Case.id).filter(Case.id.in_(batch_ids))}
        if visible != set(batch_ids):
            raise PermissionError('topic_source_restricted')
    events = snapshot.payload['events']['source_manifest']
    for offset in range(0, len(events), 200):
        ids = [row['event_id'] for row in events[offset:offset + 200]]
        visible = {row.id for row in _event_query(db).filter(Event.id.in_(ids))}
        if visible != set(ids):
            raise PermissionError('topic_source_restricted')
    resolve_references(db, snapshot.payload.get('references', {}))
    if snapshot.payload.get('facility_context'):
        from app.services.facility_material_service import validate_dossier_sources
        validate_dossier_sources(db, snapshot.payload['facility_context'], snapshot.payload['facility_sources'])
    context_result = (snapshot.payload.get('case_context') or {}).get('result', {}).get('data')
    if context_result:
        from app.services.case_result_service import CaseResultService
        result = CaseResultService.read(db, context_result['id'])
        if result['content_sha256'] != context_result['content_sha256']:
            raise PermissionError('topic_source_changed')
    context_profile = (snapshot.payload.get('case_context') or {}).get('profile', {}).get('data')
    if context_profile:
        profile = db.query(CaseAnalysisProfile).filter_by(id=context_profile['id']).first()
        if profile is None or result_hash(profile.payload) != result_hash(context_profile['payload']):
            raise PermissionError('topic_source_changed')


def validate_aggregate_access(db, aggregate):
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('topic_scope_required')
    sources = aggregate['source_manifest']
    for offset in range(0, len(sources), 100):
        batch = sources[offset:offset + 100]
        ids = {row['case_id'] for row in batch}
        if {row.id for row in db.query(Case.id).filter(Case.id.in_(ids))} != ids:
            raise PermissionError('topic_source_restricted')
        pids = {row['profile_id'] for row in batch if row['profile_id']}
        profiles = {row.id: row for row in db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.id.in_(pids))}
        if set(profiles) != pids or any(source['profile_id'] and (
            profiles[source['profile_id']].case_id != source['case_id'] or
            result_hash(profiles[source['profile_id']].payload) != source['profile_content_sha256']) for source in batch):
            raise PermissionError('topic_source_changed')


def read_topic(db, topic_id, *, revision=None, page=1, page_size=20):
    topic = _owned(db, topic_id)
    snapshot = _snapshot(db, topic_id, revision)
    result = _view(topic)
    result['refresh_progress'] = None
    if topic.latest_job_id:
        from app.services.profile_aggregate_jobs import read_aggregate_job
        job = read_aggregate_job(db, topic.latest_job_id)
        result['refresh_progress'] = {'job_id': job['id'], 'state': job['status'],
            **job['progress'], 'as_of': job['as_of'], 'definition_revision': job['definition_revision']}
    result['snapshot'] = None
    if snapshot is not None:
        validate_snapshot_access(db, snapshot)
        result['snapshot'] = {
            'id': snapshot.id, 'revision': snapshot.revision, 'content_sha256': snapshot.content_sha256,
            'created_at': snapshot.created_at, 'changes': snapshot.changes,
            'aggregate': present_aggregate(snapshot.payload['aggregate'], page=page, page_size=page_size),
            'events': {k: v for k, v in snapshot.payload['events'].items() if k != 'source_manifest'},
            'result_kind': 'frozen_topic_snapshot',
            'definition': snapshot.payload.get('definition'),
            'facility_context': snapshot.payload.get('facility_context'),
            'case_context': snapshot.payload.get('case_context'),
            'population_boundary': snapshot.payload.get('population_boundary'),
        }
    return result


def topic_history(db, topic_id, *, page=1, page_size=20):
    _owned(db, topic_id)
    query = db.query(TopicSnapshot).filter_by(topic_id=topic_id)
    items = []
    # Validate all history before returning its total; inaccessible revisions do not leak counts.
    for snapshot in query.order_by(TopicSnapshot.revision.desc()):
        validate_snapshot_access(db, snapshot)
        items.append({'id': snapshot.id, 'revision': snapshot.revision, 'changes': snapshot.changes,
                      'content_sha256': snapshot.content_sha256, 'created_at': snapshot.created_at})
    return {'total': len(items), 'items': items[(page - 1) * page_size:page * page_size]}


def read_topic_evidence(db, topic_id, case_id, *, revision):
    """Resolve only a source already used by this frozen revision, never a new search."""
    _owned(db, topic_id)
    snapshot = _snapshot(db, topic_id, revision)
    validate_snapshot_access(db, snapshot)
    source = next((row for row in snapshot.payload['aggregate']['source_manifest']
                   if row['case_id'] == case_id), None)
    if source is None:
        raise ValueError('topic_source_not_found')
    result = {'snapshot_id': snapshot.id, 'content_sha256': snapshot.content_sha256,
              'source': source, 'assertions': [], 'boundary': '这是该版专题引用的历史画像原文，不等于当前案件事实。'}
    if source['state'] not in {'ready', 'partial'} or source['profile_id'] is None:
        result['information_gaps'] = ['该版画像缺失、过期或引用无效，未使用其表述作为分析依据。']
        return result
    profile = db.query(CaseAnalysisProfile).filter_by(id=source['profile_id']).first()
    if profile is None:
        raise PermissionError('topic_source_restricted')
    semantics = profile.payload['semantics']
    from app.services.topic_model_evidence import model_evidence
    result['model_extraction'] = model_evidence(profile, source['state'])
    try:
        texts = {item['field']: SourceText(**item) for item in semantics['source_snapshot']['fields']}
        for index, assertion in enumerate(semantics['assertions']):
            reference = TextReference(**assertion['reference'])
            reference.validate(texts[reference.field])
            result['assertions'].append({key: assertion[key] for key in ('category', 'value', 'kind', 'reference')} | {
                'evidence_ref': f"case_profile:{profile.id}:assertion:{index}"})
    except (KeyError, TypeError, ValueError) as error:
        raise PermissionError('topic_source_changed') from error
    return result


def read_topic_views(db, topic_id, *, revision, page=1, page_size=20):
    _owned(db, topic_id)
    snapshot = _snapshot(db, topic_id, revision)
    validate_snapshot_access(db, snapshot)
    return snapshot_views(db, snapshot, page=page, page_size=page_size)


def update_topic(db, topic_id, *, title=None, notes=None, paused=None, question=None,
                 question_kind=None, filters=None, window=None, expected_definition_revision=None):
    topic = _owned(db, topic_id)
    values = {}
    definition_changed = any(value is not None for value in (title, question, question_kind, filters, window))
    if definition_changed:
        if expected_definition_revision != topic.definition_revision:
            raise ValueError('topic_definition_conflict')
        if question is not None and not 1 <= len(question.strip()) <= 2000:
            raise ValueError('invalid_topic_question')
        if question is not None:
            values['question'] = question.strip()
        if question_kind is not None:
            validate_question(question_kind, topic.source_context)
            values['question_kind'] = question_kind
        if filters is not None:
            args = AggregateProfiles.model_validate(filters)
            allowed = db.info['authorized_area_ids']
            if args.operational_area_id is not None and allowed is not None and args.operational_area_id not in allowed:
                raise PermissionError('topic_area_forbidden')
            if topic.source_context and topic.source_context['kind'] in {'case', 'facility'}:
                for key, value in source_filters(db, topic.source_context).items():
                    if getattr(args, key) != value:
                        raise ValueError('topic_context_conflict')
            values['filters'] = args.model_dump(mode='json', exclude={'page', 'page_size'})
        if window is not None:
            values['window'] = TopicWindow.model_validate(window).model_dump(exclude_none=True)
        values.update(definition_revision=topic.definition_revision + 1,
            requested_generation=topic.requested_generation + 1, latest_job_id=None,
            refresh_state='paused' if topic.paused else 'queued', next_refresh_at=datetime.now(timezone.utc))
    if title is not None:
        if not 1 <= len(title.strip()) <= 120:
            raise ValueError('invalid_topic_title')
        values['title'] = title.strip()
    if notes is not None:
        if len(notes) > 4000:
            raise ValueError('invalid_topic_notes')
        values['notes'] = notes
    if paused is not None:
        if type(paused) is not bool:
            raise ValueError('invalid_topic_pause')
        if not paused and topic.paused:
            db.execute(update(User).where(User.id == topic.created_by).values(id=User.id))
            if db.query(AnalysisTopic).filter_by(created_by=topic.created_by, paused=False).count() >= 100:
                db.rollback()
                raise ValueError('topic_capacity_reached')
        values.update(paused=paused, lease_token=None, lease_until=None,
                      refresh_state='paused' if paused else 'queued', next_refresh_at=datetime.now(timezone.utc))
    if values:
        if topic.latest_job_id and (definition_changed or paused is not None):
            from app.models.case_pipeline import OutboxEvent
            db.execute(update(OutboxEvent).where(OutboxEvent.id == topic.latest_job_id,
                OutboxEvent.status.in_(('pending', 'retry', 'processing'))).values(
                status='superseded', worker_id=None, lease_until=None))
            values['latest_job_id'] = None
            values['requested_generation'] = topic.requested_generation + 1
        statement = update(AnalysisTopic).where(AnalysisTopic.id == topic.id)
        if definition_changed:
            statement = statement.where(AnalysisTopic.definition_revision == expected_definition_revision)
        changed = db.execute(statement.values(**values))
        if not changed.rowcount:
            raise ValueError('topic_definition_conflict')
        if definition_changed:
            db.flush()
            record_definition(db, _owned(db, topic_id))
        db.commit()
    return _view(_owned(db, topic_id))


def request_refresh(db, topic_id):
    topic = _owned(db, topic_id)
    if topic.paused:
        raise ValueError('topic_paused')
    if topic.refresh_state == 'running':
        return _view(topic)
    db.execute(update(AnalysisTopic).where(AnalysisTopic.id == topic.id).values(
        refresh_state='queued', next_refresh_at=datetime.now(timezone.utc), last_error=None,
        requested_generation=topic.requested_generation + 1, latest_job_id=None))
    db.commit()
    return _view(_owned(db, topic_id))


def _event_query(db):
    # Event permission does not grant visibility of a linked case or production asset.
    cases = db.query(Case.id)
    assets = db.query(JurisdictionAsset.id)
    return db.query(Event).filter(
        or_(Event.related_case_id.is_(None), Event.related_case_id.in_(cases.statement)),
        or_(Event.related_asset_id.is_(None), Event.related_asset_id.in_(assets.statement)))


def _event_summary(db, args, member_ids, *, deadline):
    query = _event_query(db)
    if args.operational_area_id is not None:
        query = query.filter(Event.operational_area_id == args.operational_area_id)
    if args.start_date is not None:
        query = query.filter(Event.occurred_time >= args.start_date)
    if args.end_date is not None:
        query = query.filter(Event.occurred_time < args.end_date)
    sources, independent, linked = [], 0, 0
    member_ids = set(member_ids)
    for event in query.order_by(Event.id).yield_per(200):
        if monotonic() >= deadline:
            raise ValueError('topic_scan_incomplete')
        if event.related_case_id is not None and event.related_case_id not in member_ids:
            continue
        if event.related_case_id is None:
            independent += 1
        else:
            linked += 1
        sources.append({'event_id': event.id, 'case_id': event.related_case_id,
                        'source_sha256': result_hash({column.name: getattr(event, column.name)
                                                    for column in Event.__table__.columns})})
    return {'independent_event_count': independent, 'case_linked_event_count': linked,
            'source_manifest': sources,
            'boundary': '事件是同辖区同时间窗的补充层，不套用案件语义条件。已关联案件事件单列，不加进案件总数；不按文字相似去重。'}


def _changes(db, previous, current):
    old = {row['case_id']: row for row in previous['aggregate']['source_manifest']} if previous else {}
    new = {row['case_id']: row for row in current['aggregate']['source_manifest']}
    old_members = {row['case_id'] for row in previous['aggregate']['members']} if previous else set()
    new_members = {row['case_id'] for row in current['aggregate']['members']}
    visible_old = set()
    old_ids = sorted(old)
    for offset in range(0, len(old_ids), 200):
        visible_old.update(row.id for row in db.query(Case.id).filter(Case.id.in_(old_ids[offset:offset + 200])))
    return {'added_case_ids': sorted(new.keys() - old.keys()), 'removed_case_ids': sorted((old.keys() - new.keys()) & visible_old),
            'updated_case_ids': sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
            'entered_group': sorted(new_members - old_members), 'left_group': sorted((old_members - new_members) & visible_old),
            'comparison_state': 'complete' if visible_old == old.keys() else 'restricted',
            'events_changed': previous is None or previous['events'] != current['events'],
            'references_changed': previous is None or previous.get('references') != current.get('references'),
            'boundary': '变更仅表示专题依据变化，不代表新事实已确认或案件已办结。'}


def refresh_topic(db, topic_id):
    """One bounded work slice. Small topics finish; large topics retain progress."""
    from app.services.profile_aggregate_jobs import create_aggregate_job, process_aggregate_job
    from app.models.case_pipeline import OutboxEvent
    topic = _owned(db, topic_id)
    if topic.paused:
        return {'id': topic_id, 'status': 'not_claimed'}
    if topic.refresh_state == 'running' and topic.latest_job_id is None and topic.lease_until and OutboxClaimService._aware(topic.lease_until) > datetime.now(timezone.utc):
        return {'id': topic_id, 'status': 'not_claimed'}
    existing = db.get(OutboxEvent, topic.latest_job_id) if topic.latest_job_id else None
    if existing is None or existing.status not in ('pending', 'retry', 'processing'):
        if existing is not None:
            topic.requested_generation += 1
        create_aggregate_job(db, topic.filters, topic=topic)
    topic.refresh_state = 'running'
    identifier = topic.latest_job_id
    db.commit()
    return {'topic_id': topic_id, **process_aggregate_job(db, identifier)}


def publish_snapshot(db, topic_id, payload, *, data_revision, publication_fence):
    """Validate reads before the caller's final fences; never commit alone."""
    from app.services.topic_changes import semantic_changes, comparable_payload
    from app.services.topic_dependencies import register_dependencies
    topic = _owned(db, topic_id)
    previous = _snapshot(db, topic_id)
    unchanged = previous and result_hash(comparable_payload(previous.payload)) == result_hash(comparable_payload(payload))
    if not unchanged:
        changes = _changes(db, previous.payload if previous else None, payload)
        # A record moved out of scope cannot contribute historical counts or IDs
        # to a newly readable notification. Start a fresh comparison basis.
        comparable_previous = previous.payload if previous and changes['comparison_state'] == 'complete' else None
        changes.update(semantic_changes(comparable_previous, payload))
        snapshot = TopicSnapshot(id=str(uuid4()), topic_id=topic_id,
            revision=previous.revision + 1 if previous else 1, payload=payload,
            content_sha256=result_hash(payload), changes=changes)
        validate_snapshot_access(db, snapshot)
    publication_fence()
    topic.refresh_state = 'ready'
    topic.last_error = None
    topic.last_data_revision = data_revision
    topic.next_refresh_at = datetime.now(timezone.utc) + timedelta(hours=6)
    topic.lease_token = topic.lease_until = None
    if unchanged:
        return {'status': 'unchanged', 'revision': previous.revision}
    db.add(snapshot)
    db.flush()
    register_dependencies(db, topic, snapshot)
    return {'status': 'updated', 'revision': snapshot.revision}


def process_next_topic(db):
    """Lease recovery and periodic refresh; durable data stays in the internal DB."""
    from app.services.profile_aggregate_jobs import process_next_aggregate_job
    from app.services.topic_dependencies import consume_changes
    consume_changes(db)
    job = process_next_aggregate_job(db)
    if job:
        return job
    now = datetime.now(timezone.utc)
    revision = current_revision(db)
    candidate = db.query(AnalysisTopic.id, AnalysisTopic.created_by).filter(
        AnalysisTopic.paused.is_(False),
        or_(
            (AnalysisTopic.refresh_state != 'running') & (AnalysisTopic.next_refresh_at <= now),
            (AnalysisTopic.refresh_state == 'running') & (AnalysisTopic.lease_until <= now),
            (AnalysisTopic.refresh_state.notin_(('running', 'cancelled'))) & (AnalysisTopic.last_data_revision != revision),
        ),
    ).order_by(AnalysisTopic.next_refresh_at, AnalysisTopic.id).first()
    if candidate is None:
        return None
    topic_id, owner_id = candidate
    db.rollback()
    db.info['principal_user_id'] = owner_id
    try:
        return refresh_topic(db, topic_id)
    except PermissionError:
        db.rollback()
        db.execute(update(AnalysisTopic).where(AnalysisTopic.id == topic_id).values(
            paused=True, refresh_state='paused', lease_token=None, lease_until=None,
            last_error='topic_access_changed'))
        db.commit()
        return {'id': topic_id, 'status': 'access_changed'}
    except ValueError:
        return {'id': topic_id, 'status': 'failed'}


def definitions(db, topic_id):
    _owned(db, topic_id)
    return {'items': [{'revision': row.revision, 'definition': row.payload, 'created_at': row.created_at}
        for row in db.query(TopicDefinitionRevision).filter_by(topic_id=topic_id).order_by(TopicDefinitionRevision.revision.desc())]}


def cancel_refresh(db, topic_id):
    topic = _owned(db, topic_id)
    if topic.latest_job_id:
        from app.services.profile_aggregate_jobs import cancel_aggregate_job
        cancel_aggregate_job(db, topic.latest_job_id)
    else:
        topic.refresh_state = 'cancelled'
        topic.next_refresh_at = datetime.now(timezone.utc) + timedelta(hours=6)
        db.commit()
    return _view(_owned(db, topic_id))
