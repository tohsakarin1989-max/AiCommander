"""Conservative owner-bound query reuse; unknown dependencies mean no reuse.

Small/medium corpora are fingerprinted rather than trusting a timestamp or only
previous hits. Above the explicit budget, computation proceeds without cache.
This avoids losing newly inserted facilities, cases or newly built indexes.
"""
from app.models.agent_run import AgentRun
from app.services.intelligent_query_context import result_hash


def corpus_fingerprint(db):
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.case_history_index import CaseHistoryIndex
    from app.models.knowledge_asset import KnowledgeAsset
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.map_foundation import MapSource, MapSnapshot, JurisdictionAssetVersion, MapFieldDecision
    from app.models.case_source import CaseRevision, SourceReference, EvidenceObject, CaseLocation, CaseSourceLink
    from app.models.case_facility_association import CaseFacilityAssociation
    from app.models.event import Event
    from app.services.business_answer import _hash, _case_versions
    models = (Case, CaseAnalysisProfile, CaseHistoryIndex, KnowledgeAsset, JurisdictionAsset,
        MapSource, MapSnapshot, JurisdictionAssetVersion, MapFieldDecision, CaseRevision,
        SourceReference, EvidenceObject, CaseLocation, CaseSourceLink, CaseFacilityAssociation, Event)
    versions, remaining = [], 2000
    for model in models:
        primary = list(model.__table__.primary_key.columns)
        rows = db.query(model).populate_existing().order_by(*primary).limit(remaining + 1).all()
        if len(rows) > remaining:
            return None
        remaining -= len(rows)
        if model is Case:
            hashes = _case_versions(db, rows)
            versions.append((model.__tablename__, [(row.id, hashes[row.id]) for row in rows]))
        else:
            # Evidence content is deferred and potentially large; its stored
            # SHA/availability plus metadata is sufficient, never load the blob.
            if model is EvidenceObject:
                versions.append((model.__tablename__, [(row.id, row.sha256, row.availability, row.sensitivity) for row in rows]))
            else:
                versions.append((model.__tablename__, [([getattr(row, key.key) for key in primary], _hash(row)) for row in rows]))
    return result_hash(versions)


def fingerprint(db, *, owner, scope, question, payload):
    from app.config import settings
    corpus = corpus_fingerprint(db)
    if corpus is None:
        return None
    return result_hash({'contract': 'query-reuse-9.2-1', 'owner': owner, 'scope': scope,
        'question': question.strip(), 'payload': payload, 'corpus': corpus,
        'semantic_config': {'enabled': settings.ENABLE_VECTOR_DB,
                            'bundle': settings.LOCAL_EMBEDDING_BUNDLE,
                            'manifest': settings.LOCAL_EMBEDDING_MANIFEST_SHA256,
                            'model': settings.CASE_SEMANTIC_MODEL_ID}})


def find_reusable(db, *, owner, scope, fingerprint_value):
    if fingerprint_value is None:
        return None
    from app.services.intelligent_query_tasks import read_query
    rows = db.query(AgentRun).filter(AgentRun.task_type == 'intelligent_query',
        AgentRun.created_by == owner, AgentRun.data_version == scope,
        AgentRun.input_payload['reuse_fingerprint'].as_string() == fingerprint_value,
        AgentRun.status.in_(['queued', 'running', 'waiting_clarification', 'completed', 'degraded']))
    for row in rows.order_by(AgentRun.created_at.desc()).limit(5):
        if row.status in {'completed', 'degraded'}:
            answer = (row.result_summary or {}).get('answer') or {}
            if answer.get('completeness') in {'service_unavailable', None} or (row.result_summary or {}).get('error_code'):
                continue
        try:
            result = read_query(db, row.id)
        except (PermissionError, ValueError):
            continue
        if result.get('availability', {}).get('state') == 'historical':
            continue
        return {**result, 'reused': True, 'reuse_reason': 'same_owner_scope_sources_question'}
    return None
