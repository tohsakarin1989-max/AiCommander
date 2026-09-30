"""One catalog and reader, with type-specific bodies and current authorization.

Existing immutable stores remain authoritative. Only a facility material needs
new storage; listing or reading never builds an analysis or saves a projection.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import heapq
import json

from fastapi.encoders import jsonable_encoder

from app.models.agent_run import AgentRun
from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
from app.models.case import Case
from app.models.case_result import CaseResultSnapshot
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.deployment_advisor import SituationBrief
from app.models.knowledge_asset import KnowledgeAsset
from app.models.meeting import Meeting
from app.models.report import Report
from app.models.result_material import FacilityMaterial, ResultJudgment
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tasks import _identity


KINDS = ('case', 'topic', 'facility', 'situation', 'meeting', 'query', 'experience', 'conclusion')
BOUNDARY = '成果和人工判断都是具体版本的参考，不自动改写案件事实，不创建执法或部署执行任务。'
METADATA = ('kind', 'id', 'title', 'created_at', 'content_sha256', 'schema_version', 'subject', 'availability')


def _source(kind, identifier, digest):
    return {'kind': kind, 'id': str(identifier), 'content_sha256': digest}


def _meeting(db, identifier):
    from app.services.meeting_frozen_service import require_report_sources
    row = db.query(Report).filter_by(id=int(identifier)).first()
    meeting = db.query(Meeting).filter_by(meeting_id=row.meeting_id).first() if row else None
    if row is None or meeting is None:
        raise PermissionError('result_unavailable')
    frozen = require_report_sources(db, row)
    body = {'id': row.id, 'meeting_id': row.meeting_id, 'report_type': row.report_type,
        'content': row.content, 'consensus_points': row.consensus_points,
        'disagreement_points': row.disagreement_points, 'model_contributions': row.model_contributions,
        'source_state': 'frozen' if frozen else 'historical_unversioned',
        'boundary': '会议讨论不等于案件事实；历史未保存输入版本的报告只保留原来源，不补造冻结依据。'}
    sources = frozen['sources'] if frozen else []
    if frozen and (row.content or {}).get('source_manifest') != sources:
        raise PermissionError('meeting_report_sources_changed')
    return row, body, sources


def _read(db, kind, identifier, *, topic_document_preview=True):
    """Return metadata, typed body and deterministic document; no decisions yet."""
    from app.services.case_result_service import CaseResultService
    sources = []
    experience_review = None
    if kind == 'case':
        from app.services.case_result_document import build_case_result_document
        body = CaseResultService.read(db, identifier)
        content = body['content']
        digest, schema, created = body['content_sha256'], content['schema_version'], body['created_at']
        subject = {'kind': 'case', 'id': str(content['case_id'])}
        title = f"案件 #{content['case_id']} · 画像第 {content['versions']['profile_version']} 版"
        document = build_case_result_document(body)
        sources = [_source('case', identifier, digest)]
    elif kind == 'topic':
        from app.services import analysis_topic_service as topics
        from app.services.topic_document import build_topic_document
        row = db.query(TopicSnapshot).filter_by(id=identifier).first()
        if row is None:
            raise PermissionError('result_unavailable')
        selected = topics.read_topic(db, row.topic_id, revision=row.revision, page_size=100)
        body = {'snapshot': selected['snapshot']}
        body['views'] = topics.read_topic_views(db, row.topic_id, revision=row.revision, page_size=100)
        definition = row.payload.get('definition') or {}
        title = definition.get('title') or f'专题成果第 {row.revision} 版（历史名称未冻结）'
        subject = {'kind': 'topic', 'id': row.topic_id}
        digest, schema, created = row.content_sha256, 'topic-snapshot-6.5-1', row.created_at
        sources = [_source('case', value['id'], value['content_sha256']) for value in row.payload.get('references', {}).get('case_results', [])]
        document = build_topic_document(db, row.topic_id, row.revision, preview=topic_document_preview)
    elif kind == 'facility':
        from app.services.facility_material_service import read_facility_material
        row, body = read_facility_material(db, identifier)
        title, digest, created = row.title, row.content_sha256, row.created_at
        subject, schema = {'kind': 'facility', 'id': str(row.asset_id)}, 'facility-material-6.5-1'
        sources = [_source('facility', row.id, digest)]
    elif kind == 'situation':
        from app.services.deployment_advisor_service import DeploymentAdvisorService
        row = db.query(SituationBrief).filter_by(id=identifier).first()
        if row is None:
            raise PermissionError('result_unavailable')
        body = DeploymentAdvisorService.brief_to_dict(db, row)
        if body['status'] == 'unavailable':
            raise PermissionError('result_unavailable')
        body = deepcopy(body)
        for recommendation in body.get('recommendations', []):
            recommendation.pop('feedback', None)
        digest, created, schema = result_hash(jsonable_encoder(body)), row.generated_at, 'situation-material-6.5-1'
        title = f"{'每日' if row.period_type == 'daily' else '每周'}态势 · {row.period_start.date()}"
        subject = {'kind': 'area', 'id': str(row.operational_area_id)}
    elif kind == 'meeting':
        row, body, sources = _meeting(db, identifier)
        digest, created, schema = result_hash(body), row.created_at, 'meeting-material-6.5-1'
        title, subject = f'多视角会议 · {row.meeting_id}', {'kind': 'meeting', 'id': row.meeting_id}
    elif kind == 'query':
        from app.services.intelligent_query_tasks import read_query
        from app.services.intelligent_query_document import build_query_document
        body = read_query(db, identifier)
        document = build_query_document(body)
        digest, created, schema = document.content_sha256, body['created_at'], 'query-material-6.5-1'
        title, subject = body['query'][:200], {'kind': 'query', 'id': identifier}
    elif kind == 'experience':
        from app.services.knowledge_asset_service import KnowledgeAssetService
        row = db.query(KnowledgeAsset).filter_by(id=int(identifier)).first()
        if row is None:
            raise PermissionError('result_unavailable')
        body = KnowledgeAssetService.asset_payload(db, row)
        # Reviews have their own lifecycle; changing a review must not change
        # the original body identity. Keep all review fields visible separately.
        immutable = {key: body[key] for key in ('id', 'asset_type', 'version', 'title', 'content',
                     'evidence_refs', 'source_signature', 'source_data_version')}
        immutable['content'] = {key: value for key, value in immutable['content'].items()
                                if key not in {'manual_review_status', 'reviewed_at', 'reviewer', 'review_note'}}
        experience_review = {key: body[key] for key in ('status', 'reviewer_label', 'review_note', 'reviewed_at')}
        body = immutable
        digest, created, schema = result_hash(immutable), row.created_at, 'experience-material-6.5-1'
        title, subject = row.title, {'kind': 'case', 'id': str(row.source_case_id)}
        frozen = body['content'].get('frozen_result')
        if frozen:
            sources = [_source('case', frozen['id'], frozen['content_sha256'])]
    elif kind == 'conclusion':
        from app.services.legacy_conclusion_access import require_conclusion_result_access
        row = db.query(Conclusion).filter_by(id=int(identifier)).first()
        if row is None or db.query(Case.id).filter_by(id=row.case_id).first() is None:
            raise PermissionError('result_unavailable')
        require_conclusion_result_access(db, row)
        evidence = row.evidence if isinstance(row.evidence, dict) else {}
        source = evidence.get('source_result')
        if source:
            result = CaseResultService.read(db, source['result_id'])
            if result['content_sha256'] != source['content_sha256']:
                raise PermissionError('result_unavailable')
            sources = [_source('case', source['result_id'], source['content_sha256'])]
        if row.meeting_id:
            from app.services.meeting_frozen_service import require_meeting_sources
            meeting = db.query(Meeting).filter_by(meeting_id=row.meeting_id).first()
            if meeting is None:
                raise PermissionError('result_unavailable')
            require_meeting_sources(db, meeting)
        reviews = db.query(ConclusionReview).filter_by(conclusion_id=row.id).order_by(ConclusionReview.id).all()
        body = {'id': row.id, 'case_id': row.case_id, 'meeting_id': row.meeting_id,
            'summary': row.summary, 'evidence': row.evidence, 'status': row.status,
            'historical_reviews': [{'id': item.id, 'action': item.action, 'note': item.note,
                'created_at': item.created_at, 'reviewer_state': 'legacy_not_recorded'} for item in reviews],
            'boundary': '保留历史结论与人工记录；旧记录未保存判断人时明确未知，不补造正式事实。'}
        digest, created, schema = result_hash(jsonable_encoder(body)), row.created_at, 'legacy-conclusion-material-6.5-1'
        title, subject = f'历史结论 #{row.id}', {'kind': 'case', 'id': str(row.case_id)}
    else:
        raise ValueError('result_kind_invalid')
    if kind in {'facility', 'situation', 'meeting', 'experience', 'conclusion'}:
        from app.services.typed_material_document import build
        document = build(kind, identifier, digest, title, body, sources, BOUNDARY)
    envelope = {'kind': kind, 'id': str(identifier), 'title': title, 'created_at': created,
        'content_sha256': digest, 'schema_version': schema, 'subject': subject,
        'availability': 'available', 'body': body, 'sources': sources, 'boundary': [BOUNDARY]}
    from app.services.result_map_service import attach_map
    document = attach_map(envelope, document)
    envelope['document'] = {'schema_version': document.schema, 'blocks': [asdict(block) for block in document.blocks]}
    if experience_review is not None:
        envelope['experience_review'] = experience_review
    return envelope, document


def read_result(db, kind, identifier, *, include_judgments=True):
    _identity(db)
    with db.no_autoflush:
        result, _ = _read(db, kind, str(identifier))
        if not include_judgments:
            result.pop('experience_review', None)
        result['judgments'] = []
        if include_judgments:
            for row in db.query(ResultJudgment).filter_by(result_kind=kind, result_id=str(identifier),
                    content_sha256=result['content_sha256']).order_by(ResultJudgment.created_at, ResultJudgment.id):
                try:
                    for source in row.additional_sources:
                        other, _ = _read(db, source['kind'], source['id'])
                        if other['content_sha256'] != source['content_sha256']:
                            raise PermissionError('judgment_source_changed')
                except (PermissionError, ValueError):
                    # Neither note nor a count of withheld decisions leaks.
                    continue
                result['judgments'].append({key: getattr(row, key) for key in (
                    'id', 'decision', 'note', 'created_by', 'created_at', 'content_sha256', 'additional_sources')})
    return jsonable_encoder(result)


def catalog(db, *, query='', kind=None, limit=20, offset=0, subject_kind=None, subject_id=None, exclude_kinds=()):
    user = _identity(db)
    if kind is not None and kind not in KINDS or not 1 <= limit <= 100 or offset < 0 or offset > 10000:
        raise ValueError('result_catalog_arguments')
    models = {'case': (CaseResultSnapshot, CaseResultSnapshot.id, CaseResultSnapshot.created_at),
        'topic': (TopicSnapshot, TopicSnapshot.id, TopicSnapshot.created_at),
        'facility': (FacilityMaterial, FacilityMaterial.id, FacilityMaterial.created_at),
        'situation': (SituationBrief, SituationBrief.id, SituationBrief.generated_at),
        'meeting': (Report, Report.id, Report.created_at), 'query': (AgentRun, AgentRun.id, AgentRun.created_at),
        'experience': (KnowledgeAsset, KnowledgeAsset.id, KnowledgeAsset.created_at),
        'conclusion': (Conclusion, Conclusion.id, Conclusion.created_at)}
    def stream(source_kind):
        model, key, created = models[source_kind]
        rows = db.query(key, created)
        if source_kind == 'query':
            rows = rows.filter(AgentRun.task_type == 'intelligent_query', AgentRun.created_by == user.id,
                               AgentRun.status.in_(('completed', 'degraded')))
        if source_kind == 'topic':
            rows = rows.join(AnalysisTopic, AnalysisTopic.id == TopicSnapshot.topic_id).filter(AnalysisTopic.created_by == user.id)
        for identifier, instant in rows.order_by(created.desc(), key.asc()).yield_per(50):
            instant = instant.replace(tzinfo=timezone.utc) if instant and instant.tzinfo is None else instant
            yield (-(instant.timestamp() if instant else 0), source_kind, str(identifier))
    items, matched = [], 0
    for _, source_kind, identifier in heapq.merge(*(stream(value) for value in ([kind] if kind else KINDS)
                                                   if value not in exclude_kinds)):
        try:
            result, _ = _read(db, source_kind, identifier)
        except (PermissionError, ValueError, LookupError):
            continue
        if subject_kind is not None and result['subject']['kind'] != subject_kind:
            continue
        if subject_id is not None and str(result['subject']['id']) != str(subject_id):
            continue
        if query.strip().casefold() not in json.dumps(jsonable_encoder(result['body']), ensure_ascii=False).casefold() and query.strip().casefold() not in result['title'].casefold():
            continue
        if matched >= offset:
            items.append({key: result[key] for key in METADATA})
        matched += 1
        if len(items) > limit:
            break
    return jsonable_encoder({'items': items[:limit], 'has_more': len(items) > limit, 'offset': offset, 'limit': limit})
