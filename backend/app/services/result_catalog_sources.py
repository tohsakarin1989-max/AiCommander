"""Private source descriptors for a disposable catalog, not public readers.

No descriptor grants access. The worker can inspect raw rows in an unscoped
service Session; delivery always goes through each material's current validator.
Only metadata and a hash are persisted; transient source records never become
another fact store or a public response.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.encoders import jsonable_encoder

from app.models.agent_run import AgentRun
from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
from app.models.case_result import CaseResultSnapshot
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.deployment_advisor import DeploymentRecommendation, SituationBrief
from app.models.knowledge_asset import KnowledgeAsset
from app.models.meeting import Meeting
from app.models.report import Report
from app.models.result_material import FacilityMaterial, MeetingFrozenInput
from app.services.intelligent_query_context import result_hash

MODELS = {'case': CaseResultSnapshot, 'topic': TopicSnapshot, 'facility': FacilityMaterial,
          'situation': SituationBrief, 'meeting': Report, 'query': AgentRun,
          'experience': KnowledgeAsset, 'conclusion': Conclusion}
SCHEMAS = {'topic': 'topic-snapshot-6.5-1', 'facility': 'facility-material-6.5-1',
           'situation': 'situation-material-6.5-1', 'meeting': 'meeting-material-6.5-1',
           'query': 'query-material-6.5-1', 'experience': 'experience-material-6.5-1',
           'conclusion': 'legacy-conclusion-material-6.5-1'}


def source_query(db, kind):
    query = db.query(MODELS[kind])
    if kind == 'query':
        query = query.filter(AgentRun.task_type == 'intelligent_query',
                             AgentRun.status.in_(('completed', 'degraded')))
    return query


def _record(row):
    if row is None:
        return None
    values = dict(vars(row))
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return jsonable_encoder(values)


def _rows(query, model):
    # Read columns rather than refreshing ORM instances: a GET must not discard
    # a caller's pending edits, and an old identity-map entry is not a freshness check.
    return [SimpleNamespace(**row._mapping) for row in query.with_entities(
        *(getattr(model, column.key) for column in model.__table__.columns))]


def _one(query, model):
    rows = _rows(query.limit(1), model)
    return rows[0] if rows else None


def source_state(db, kind, identifier):
    """Fingerprint root plus mutable children, not just the root's updated_at."""
    model = MODELS[kind]
    if model.id.type.python_type is int:
        identifier = int(identifier)
    row = _one(source_query(db, kind).filter(model.id == identifier), model)
    if row is None:
        raise LookupError('catalog_source_missing')
    related = {}
    if kind == 'topic':
        topic = _one(db.query(AnalysisTopic).filter_by(id=row.topic_id), AnalysisTopic)
        # Ownership/scope changes are dependencies; pause/refresh state is not content.
        related['topic'] = None if topic is None else {'id': topic.id, 'created_by': topic.created_by,
                                                       'scope_version': topic.scope_version}
    if kind in {'meeting', 'conclusion'} and row.meeting_id:
        related['meeting'] = _record(_one(db.query(Meeting).filter_by(meeting_id=row.meeting_id), Meeting))
        related['frozen'] = _record(_one(db.query(MeetingFrozenInput).filter_by(meeting_id=row.meeting_id), MeetingFrozenInput))
    if kind == 'situation':
        related['recommendations'] = [_record(item) for item in _rows(db.query(DeploymentRecommendation)
            .filter_by(brief_id=row.id).order_by(DeploymentRecommendation.rank, DeploymentRecommendation.id), DeploymentRecommendation)]
    if kind == 'conclusion':
        related['reviews'] = [_record(item) for item in _rows(db.query(ConclusionReview)
            .filter_by(conclusion_id=row.id).order_by(ConclusionReview.id), ConclusionReview)]
    record = _record(row)
    return row, {'record': record, 'related': related}


def metadata(kind, row):
    digest = getattr(row, 'content_sha256', None)
    schema = SCHEMAS.get(kind)
    created = row.generated_at if kind == 'situation' else row.created_at
    if kind == 'case':
        schema = row.content['schema_version']
        title = f"案件 #{row.content['case_id']} · 画像第 {row.content['versions']['profile_version']} 版"
        subject = ('case', row.case_id)
    elif kind == 'topic':
        title = (row.payload.get('definition') or {}).get('title') or f'专题成果第 {row.revision} 版（历史名称未冻结）'
        subject = ('topic', row.topic_id)
    elif kind == 'facility':
        title, subject = row.title, ('facility', row.asset_id)
    elif kind == 'situation':
        title = f"{'每日' if row.period_type == 'daily' else '每周'}态势 · {row.period_start.date()}"
        subject = ('area', row.operational_area_id)
    elif kind == 'meeting':
        title, subject = f'多视角会议 · {row.meeting_id}', ('meeting', row.meeting_id)
    elif kind == 'query':
        title, subject, digest = row.query[:200], ('query', row.id), result_hash(row.result_summary)
    elif kind == 'experience':
        title, subject = row.title, ('case', row.source_case_id)
    else:
        title, subject = f'历史结论 #{row.id}', ('case', row.case_id)
    if (not isinstance(title, str) or len(title) > 240 or not isinstance(schema, str)
            or len(schema) > 80 or len(str(subject[1])) > 80):
        raise ValueError('catalog_metadata_invalid')
    return {'title': title, 'material_created_at': created, 'subject_kind': subject[0],
            'subject_id': str(subject[1]), 'content_sha256': digest, 'schema_version': schema}
