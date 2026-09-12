"""后台分批维护检索特征；读取只复用当前哈希/规则对应的索引。"""
from datetime import datetime, timezone
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_history_index import CaseHistoryIndex, CaseHistoryIndexCursor
from app.models.case_pipeline import OutboxEvent
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash
from app.services.case_semantic_service import SEMANTIC_RULE_VERSION, TEXT_FIELDS, build_semantic_profile

INDEX_VERSION = "history-lexical-5.1-2"
CURSOR_NAME = "case-history"


def content_hash(content: dict) -> str:
    return text_hash(json.dumps(content, sort_keys=True, ensure_ascii=False))


def rule_version() -> str:
    return f"{INDEX_VERSION}:{SEMANTIC_RULE_VERSION}"


def cached_features(row: CaseHistoryIndex | None, source_hash: str) -> tuple[set, set] | None:
    if row is None or row.source_hash != source_hash or row.rule_version != rule_version():
        return None
    payload = row.payload
    if not isinstance(payload, dict):
        return None
    terms, conditions = payload.get("terms"), payload.get("conditions")
    if (not isinstance(terms, list) or not all(isinstance(term, str) for term in terms)
            or not isinstance(conditions, list)
            or not all(isinstance(item, list) and len(item) == 3
                       and all(isinstance(value, str) for value in item) for item in conditions)):
        return None
    return set(terms), {tuple(item) for item in conditions}


class CaseHistoryIndexService:
    @staticmethod
    def rebuild_case(db: Session, case: Case) -> int:
        # Import lazily: retrieval reads this cache, but never calls its write methods.
        from app.services.case_history_retrieval import business_conditions, lexical_terms, source_values
        from app.models.case_history_index import CaseHistoryEmbedding
        from app.services.local_embedding_service import get_local_embedder, LocalEmbeddingError
        from app.services.case_history_vector_service import store_embedding

        embedder = get_local_embedder()

        rows = {(row.source_type, row.source_id): row for row in db.scalars(
            select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == case.id)
            .execution_options(populate_existing=True))}
        values = source_values(case)
        sources = [("case", str(case.id), snapshot_payload(freeze_sources(values))["sha256"],
                    "。".join(value for value in values.values() if value), values)]
        assets = list(db.scalars(select(KnowledgeAsset).where(
            KnowledgeAsset.source_case_id == case.id,
            KnowledgeAsset.asset_type == "experience_card").order_by(KnowledgeAsset.version.desc())
            .execution_options(populate_existing=True)))
        confirmed = next((asset for asset in assets if asset.status == "confirmed"), None)
        if confirmed is not None:
            content = confirmed.content if isinstance(confirmed.content, dict) else {}
            text = str(content.get("summary") or "")
            sources.append(("experience_card", str(confirmed.id), content_hash(content), text, {"description": text}))
        elif not assets:
            card = ((case.features or {}).get("intelligence") or {}).get("experience_card") or {}
            if isinstance(card, dict) and card.get("manual_review_status") == "confirmed":
                text = str(card.get("summary") or "")
                sources.append(("legacy_experience_card", str(case.id), content_hash(card), text, {"description": text}))
        active = set()
        changed = 0
        for source_type, source_id, signature, text, source in sources:
            key = (source_type, source_id)
            active.add(key)
            row = rows.get(key)
            previous_payload = (dict(row.payload) if row is not None
                                and isinstance(row.payload, dict) else {})
            lexical_current = cached_features(row, signature) is not None
            if row is None:
                row = CaseHistoryIndex(case_id=case.id, source_type=source_type, source_id=source_id)
                db.add(row)
            if not lexical_current:
                row.source_hash = signature
                row.rule_version = rule_version()
                row.payload = {"terms": sorted(lexical_terms(text)),
                               "conditions": [list(item) for item in sorted(business_conditions(
                                   build_semantic_profile({field: value for field, value in source.items() if field in TEXT_FIELDS})))]}
                row.updated_at = datetime.now(timezone.utc)
                changed += 1
            if embedder.state == 'ready':
                current = db.scalar(select(CaseHistoryEmbedding.source_hash).where(
                    CaseHistoryEmbedding.case_id == case.id, CaseHistoryEmbedding.source_type == source_type,
                    CaseHistoryEmbedding.source_id == source_id, CaseHistoryEmbedding.model_version == embedder.model_version))
                if current != signature:
                    try:
                        store_embedding(db, row, embedder.encode(text), embedder.model_version)
                        row.payload = {**row.payload, 'embedding_state': 'ready', 'embedding_model': embedder.model_version}
                    except LocalEmbeddingError as error:
                        row.payload = {**row.payload, 'embedding_state': 'unavailable', 'embedding_error': str(error)}
                    if lexical_current:
                        changed += 1
            if source_type == 'case':
                # Incident time and authorization area affect history retrieval
                # even when the lexical source hash is unchanged.
                occurred = case.occurred_time
                occurred = (occurred.replace(tzinfo=timezone.utc) if occurred is not None
                            and occurred.tzinfo is None else occurred)
                dependency = content_hash({'source_hash': signature,
                    'occurred_time': occurred.isoformat() if occurred is not None else None,
                    'area_id': case.operational_area_id})
                if previous_payload.get('history_dependency_hash') != dependency:
                    from app.services.history_road_refresh import record_change
                    areas = [case.operational_area_id]
                    if key in rows:
                        areas.append(previous_payload.get('history_area_id'))
                    record_change(db, case_id=case.id, area_ids=areas)
                row.payload = {**row.payload, 'history_dependency_hash': dependency,
                               'history_area_id': case.operational_area_id}
        for key, row in rows.items():
            if key not in active:
                db.delete(row)
                changed += 1
        return changed

    @staticmethod
    def reconcile_batch(db: Session, *, limit: int = 100) -> dict:
        """调用方提交/回滚；锁住持久断点，失败不会跳过案件或丢失进度。"""
        if db.info.get("authorized_area_ids") is not None:
            raise PermissionError("history_index_background_session_required")
        if not 1 <= limit <= 500:
            raise ValueError("invalid_history_index_batch_size")
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise ValueError("unsupported_history_index_database")
        db.execute(insert(CaseHistoryIndexCursor).values(
            name=CURSOR_NAME, after_case_id=0, completed_passes=0).on_conflict_do_nothing())
        # UPDATE acquires the SQLite write lock and PostgreSQL row lock before reading the cursor.
        db.execute(update(CaseHistoryIndexCursor).where(CaseHistoryIndexCursor.name == CURSOR_NAME)
                   .values(updated_at=datetime.now(timezone.utc)))
        cursor = db.scalar(select(CaseHistoryIndexCursor).where(CaseHistoryIndexCursor.name == CURSOR_NAME)
                           .execution_options(populate_existing=True))
        # Reuse the event already committed with case save. Its profile-processing
        # status is independent: indexing must work even when that consumer failed.
        pending = list(db.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == 'case.analysis.requested',
            OutboxEvent.payload['history_index_pending'].as_boolean().is_(True))
            .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(limit)
            .execution_options(populate_existing=True)))
        priority_ids = set()
        for event in pending:
            if event.aggregate_type != 'case' or not event.aggregate_id.isdigit():
                raise ValueError('invalid_history_source_event')
            priority_ids.add(int(event.aggregate_id))
        priority_cases = list(db.scalars(select(Case).where(Case.id.in_(priority_ids))
            .order_by(Case.id).execution_options(populate_existing=True))) if priority_ids else []
        changed = sum(CaseHistoryIndexService.rebuild_case(db, case) for case in priority_cases)
        for event in pending:
            # The cursor lock serializes this consumer, not the profile consumer.
            # A rollback restores both vectors and this acknowledgement.
            event.payload = {**event.payload, 'history_index_pending': False}
        cases = list(db.scalars(select(Case).where(Case.id > cursor.after_case_id)
                               .order_by(Case.id).limit(limit).execution_options(populate_existing=True)))
        changed += sum(CaseHistoryIndexService.rebuild_case(db, case)
                       for case in cases if case.id not in priority_ids)
        if len(cases) < limit:
            cursor.after_case_id = 0
            cursor.completed_passes += 1
        else:
            cursor.after_case_id = cases[-1].id
        db.flush()
        from app.services.history_road_refresh import coalesce_changes
        history_refresh_id = coalesce_changes(db)
        from app.services.local_embedding_service import get_local_embedder
        model_state = get_local_embedder().state
        return {"scanned_cases": len(cases), "changed_sources": changed,
                "priority_cases": len(priority_cases), "acknowledged_events": len(pending),
                "after_case_id": cursor.after_case_id, "completed_passes": cursor.completed_passes,
                "index_version": rule_version(),
                "history_refresh_event_id": history_refresh_id,
                "semantic_index_state": 'building' if model_state == 'ready' else model_state}
