"""Typed saved business questions; no free-form question becomes executable code."""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.analysis_topic import TopicDefinitionRevision
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.services.intelligent_query_tools import AggregateProfiles


class TopicWindow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['fixed', 'rolling'] = 'fixed'
    days: int | None = Field(default=None, ge=1, le=366, strict=True)
    anchor_hour: int = Field(default=0, ge=0, le=23, strict=True)

    @model_validator(mode='after')
    def valid(self):
        if (self.mode == 'rolling') != (self.days is not None):
            raise ValueError('topic_window_days_required')
        return self


class TopicSourceContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['case', 'facility', 'query']
    id: Annotated[int, Field(strict=True, gt=0)] | Annotated[str, Field(strict=True, min_length=1, max_length=100)]


def definition_values(topic):
    return {'revision': topic.definition_revision, 'title': topic.title,
        'question_kind': topic.question_kind,
        'question': topic.question or topic.title, 'filters': topic.filters,
        'window': topic.window or {'mode': 'fixed'}, 'source_context': topic.source_context}


def validate_question(kind, source):
    if kind not in {'condition_changes', 'case_gaps', 'facility_context'}:
        raise ValueError('topic_question_kind_invalid')
    required = {'case_gaps': 'case', 'facility_context': 'facility'}.get(kind)
    if required and (not source or source['kind'] != required):
        raise ValueError('topic_question_source_required')


def record_definition(db, topic):
    db.add(TopicDefinitionRevision(id=str(uuid4()), topic_id=topic.id,
        revision=topic.definition_revision, payload=definition_values(topic)))


def resolve_definition(topic, now=None):
    value = definition_values(topic)
    now = now or datetime.now(timezone.utc)
    window = TopicWindow.model_validate(value['window'])
    filters = dict(value['filters'])
    if window.mode == 'rolling':
        # Business day is China time, frozen at task creation, not per resumed page.
        local = now.astimezone(timezone(timedelta(hours=8)))
        end = local.replace(hour=window.anchor_hour, minute=0, second=0, microsecond=0)
        if end > local:
            end -= timedelta(days=1)
        filters.update(start_date=(end - timedelta(days=window.days)).astimezone(timezone.utc).isoformat(),
                       end_date=end.astimezone(timezone.utc).isoformat())
    value.update(as_of=now.isoformat(), resolved_filters=AggregateProfiles.model_validate(filters).model_dump(mode='json', exclude={'page', 'page_size'}))
    return value


def validate_source(db, source):
    if source is None:
        return None
    value = TopicSourceContext.model_validate(source).model_dump()
    if value['kind'] == 'query':
        from app.services.intelligent_query_tasks import read_query
        read_query(db, str(value['id']))
        return value
    if type(value['id']) is not int or value['id'] < 1:
        raise ValueError('topic_source_invalid')
    model = Case if value['kind'] == 'case' else JurisdictionAsset
    if db.query(model.id).filter_by(id=value['id']).first() is None:
        raise PermissionError('topic_source_restricted')
    return value


def source_filters(db, source):
    source = validate_source(db, source)
    if source['kind'] == 'query':
        raise ValueError('topic_use_from_query')
    if source['kind'] == 'case':
        return {'case_id': source['id']}
    asset = db.query(JurisdictionAsset).filter_by(id=source['id']).one()
    return {'operational_area_id': asset.operational_area_id}


def context_case_ids(db, source, *, start_date=None, end_date=None):
    if not source or source['kind'] != 'facility':
        return None
    validate_source(db, source)
    from sqlalchemy import func
    from app.models.case_facility_association import CaseFacilityAssociation
    from app.models.case_source import CaseRevision, SourceReference, EvidenceObject
    from app.models.event import Event
    from app.services.case_facility_association_service import _reference_matches
    # Recorded links only. Spatial proximity and machine candidates stay separate.
    latest = db.query(CaseRevision.case_id, func.max(CaseRevision.revision).label('revision')).group_by(CaseRevision.case_id).subquery()
    rows = db.query(CaseFacilityAssociation.case_id, SourceReference, CaseRevision,
        EvidenceObject.availability).join(CaseRevision,
            (CaseRevision.id == CaseFacilityAssociation.source_revision_id)
            & (CaseRevision.case_id == CaseFacilityAssociation.case_id)).join(latest,
            (latest.c.case_id == CaseRevision.case_id) & (latest.c.revision == CaseRevision.revision)).join(
            SourceReference, (SourceReference.id == CaseFacilityAssociation.source_reference_id)
            & (SourceReference.case_id == CaseFacilityAssociation.case_id)).outerjoin(
            EvidenceObject, EvidenceObject.id == SourceReference.evidence_object_id).filter(
            CaseFacilityAssociation.asset_id == source['id'], CaseFacilityAssociation.revoked_at.is_(None))
    ids = {case_id for case_id, reference, revision, availability in rows.yield_per(200)
           if _reference_matches(reference, revision)
           and (reference.evidence_object_id is None or availability == 'available')}
    events = db.query(Event.related_case_id).filter(Event.related_asset_id == source['id'], Event.related_case_id.is_not(None))
    if start_date is not None:
        events = events.filter(Event.occurred_time >= start_date)
    if end_date is not None:
        events = events.filter(Event.occurred_time < end_date)
    ids.update(row.related_case_id for row in events)
    return sorted(ids)
