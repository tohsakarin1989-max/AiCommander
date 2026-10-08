"""Bounded history-index retries on the existing Outbox, without source copies."""
from datetime import timedelta, timezone
import uuid

from sqlalchemy import select

from app.models.case_pipeline import OutboxEvent
from app.services.case_semantic_evidence import text_hash

EVENT_TYPE = 'case.history.index.retry'
MAX_ATTEMPTS = 3


def current_input_stamp(db, case):
    """Current metadata only: no encode, index/cache writes, flush or commit."""
    from app.services.case_history_vector_reuse import FragmentVectorReuse
    from app.services.local_embedding_service import get_local_embedder
    with db.no_autoflush:
        return input_stamp(db, case, FragmentVectorReuse(db, get_local_embedder()))


def input_stamp(db, case, reuse):
    from app.models.knowledge_asset import KnowledgeAsset
    from app.services.case_history_fragments import FRAGMENT_INDEX_VERSION, _process_stamp
    from app.services.case_history_index_service import content_hash, rule_version
    from app.services.case_source_service import CaseSourceService, encode

    revision = CaseSourceService.latest_revision(db, case.id)
    source = CaseSourceService.source_payloads(db, [case])[case.id]
    assets = db.execute(select(KnowledgeAsset.id, KnowledgeAsset.status, KnowledgeAsset.content)
        .where(KnowledgeAsset.source_case_id == case.id,
               KnowledgeAsset.asset_type == 'experience_card').order_by(KnowledgeAsset.id)).all()
    stamp = {'source_hash': text_hash(encode(source)),
        'source_revision_id': revision.id if revision else None,
        'rule_version': rule_version(), 'fragment_version': FRAGMENT_INDEX_VERSION,
        'model_version': reuse.identity[1], 'encoder_fingerprint': reuse.fingerprint,
        'dimension': reuse.dimension, 'model_state': reuse.identity[0],
        'derived_input_hash': content_hash({'profile': _process_stamp(db, case.id),
            'assets': [(row.id, row.status, content_hash(row.content or {})) for row in assets],
            'legacy_card': ((case.features or {}).get('intelligence') or {}).get('experience_card')})}
    return {**stamp, 'input_hash': text_hash(encode(stamp))}


def may_attempt(debt, stamp, now):
    if debt is None or (debt.payload or {}).get('input_hash') != stamp['input_hash']:
        return True
    if debt.status == 'failed':
        return False
    available = debt.available_at
    if available is not None and available.tzinfo is None:
        available = available.replace(tzinfo=timezone.utc)
    return debt.status != 'retry' or available is None or available <= now


def error_code(exc):
    # Neither exception messages nor source/model output belong in a debt record.
    from app.services.local_embedding_service import LocalEmbeddingError
    if isinstance(exc, LocalEmbeddingError):
        return 'history_embedding_failed'
    if isinstance(exc, PermissionError):
        return 'history_source_unavailable'
    if isinstance(exc, ValueError) and str(exc) in {
        'history_source_changed', 'history_encoder_changed', 'history_schema_changed',
        'history_process_changed'}:
        return str(exc)
    return 'history_index_unexpected_error'


def failed(db, case_id, stamp, exc, stage, now, debt=None):
    if debt is None:
        debt = OutboxEvent(id=str(uuid.uuid4()), event_type=EVENT_TYPE, aggregate_type='case', aggregate_id=str(case_id),
            idempotency_key=f'history-index-retry:{case_id}', attempts=0, payload={})
        db.add(debt)
    previous = debt.payload or {}
    same_input = previous.get('input_hash') == stamp['input_hash']
    ordinary_failures = (previous.get('ordinary_failures', debt.attempts) if same_input else 0) + 1
    debt.attempts += 1
    debt.status = 'failed' if ordinary_failures >= MAX_ATTEMPTS else 'retry'
    debt.error = error_code(exc)
    debt.available_at = now + timedelta(seconds=60 * 2 ** (min(ordinary_failures, MAX_ATTEMPTS) - 1))
    debt.claimed_at = debt.lease_until = debt.worker_id = debt.processed_at = None
    debt.payload = {**stamp, 'failure_stage': stage, 'error_code': debt.error,
        'ordinary_failures': ordinary_failures,
        'first_failed_at': previous.get('first_failed_at', now.isoformat()) if same_input else now.isoformat(),
        'last_failed_at': now.isoformat()}
    return debt


def completed(debt, now):
    if debt is not None:
        debt.status, debt.processed_at, debt.error = 'completed', now, None
        debt.claimed_at = debt.lease_until = debt.worker_id = None
