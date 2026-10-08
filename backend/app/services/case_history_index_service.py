"""后台分批维护检索特征；读取只复用当前哈希/规则对应的索引。"""
from datetime import datetime, timezone
import json

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_history_index import CaseHistoryIndex, CaseHistoryIndexCursor
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import ChangeDelivery
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash
from app.services.case_semantic_service import SEMANTIC_RULE_VERSION, TEXT_FIELDS, build_semantic_profile

INDEX_VERSION = "history-lexical-6.3-1"
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
    def rebuild_case(db: Session, case: Case, *, publications: list | None = None, vector_reuse=None) -> int:
        # Import lazily: retrieval reads this cache, but never calls its write methods.
        from app.services.case_history_retrieval import business_conditions, lexical_terms, source_values
        from app.services.local_embedding_service import get_local_embedder
        from app.services.case_history_fragments import prepare_fragments
        from app.services.case_source_service import CaseSourceService
        from app.services.case_history_vector_reuse import FragmentVectorReuse

        if db.scalar(select(Case.id).where(Case.id == case.id)) is None:
            raise PermissionError('history_source_unavailable')
        embedder = get_local_embedder()
        vector_reuse = vector_reuse or FragmentVectorReuse(db, embedder)
        vector_reuse.require_current(embedder)
        captured_rule = rule_version()
        revision = CaseSourceService.latest_revision(db, case.id)
        captured_area, captured_time = case.operational_area_id, case.occurred_time

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
        changed, prepared, road_changes = 0, [], []
        for source_type, source_id, signature, text, source in sources:
            key = (source_type, source_id)
            active.add(key)
            stored = rows.get(key)
            previous_payload = (dict(stored.payload) if stored is not None
                                and isinstance(stored.payload, dict) else {})
            lexical_current = cached_features(stored, signature) is not None
            row = CaseHistoryIndex(case_id=case.id, source_type=source_type, source_id=source_id,
                source_hash=signature, rule_version=rule_version(), payload=previous_payload,
                updated_at=stored.updated_at if stored is not None else datetime.now(timezone.utc))
            if not lexical_current:
                row.source_hash = signature
                row.rule_version = rule_version()
                row.payload = {"terms": sorted(lexical_terms(text)),
                               "conditions": [list(item) for item in sorted(business_conditions(
                                   build_semantic_profile({field: value for field, value in source.items() if field in TEXT_FIELDS})))]}
                row.updated_at = datetime.now(timezone.utc)
                changed += 1
            fragment_changed, publish_fragments = prepare_fragments(db, row, source, embedder=embedder,
                revision=revision if source_type == 'case' else None, vector_reuse=vector_reuse)
            prepared.append((stored, row, publish_fragments))
            if lexical_current and fragment_changed:
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
                    areas = [case.operational_area_id]
                    if key in rows:
                        areas.append(previous_payload.get('history_area_id'))
                    road_changes.append(areas)
                row.payload = {**row.payload, 'history_dependency_hash': dependency,
                               'history_area_id': case.operational_area_id}
        inactive = [row for key, row in rows.items() if key not in active]
        changed += len(inactive)

        def publish():
            vector_reuse.require_current(get_local_embedder())
            if rule_version() != captured_rule:
                raise ValueError('history_schema_changed')
            statement = select(Case).where(Case.id == case.id).execution_options(populate_existing=True)
            if db.get_bind().dialect.name == 'postgresql':
                statement = statement.with_for_update()
            fresh = db.scalar(statement)
            current_revision = CaseSourceService.latest_revision(db, case.id) if fresh is not None else None
            if (fresh is None or snapshot_payload(freeze_sources(source_values(fresh)))["sha256"] != sources[0][2]
                    or fresh.operational_area_id != captured_area or fresh.occurred_time != captured_time
                    or (current_revision.id if current_revision else None) != (revision.id if revision else None)):
                raise ValueError('history_source_changed')
            for stored, candidate, publish_fragments in prepared:
                if candidate.source_type == 'experience_card':
                    asset_query = select(KnowledgeAsset).where(KnowledgeAsset.id == int(candidate.source_id))
                    if db.get_bind().dialect.name == 'postgresql':
                        asset_query = asset_query.with_for_update()
                    asset = db.scalar(asset_query.execution_options(populate_existing=True))
                    if (asset is None or asset.status != 'confirmed'
                            or content_hash(asset.content if isinstance(asset.content, dict) else {}) != candidate.source_hash):
                        raise ValueError('history_source_changed')
                if stored is None:
                    db.add(candidate)
                else:
                    stored.source_hash, stored.rule_version = candidate.source_hash, candidate.rule_version
                    stored.payload, stored.updated_at = candidate.payload, candidate.updated_at
                db.flush()
                publish_fragments()
            for row in inactive:
                db.delete(row)
            from app.services.history_road_refresh import record_change
            for areas in road_changes:
                record_change(db, case_id=case.id, area_ids=areas)

        if publications is not None:
            publications.append(publish)
        else:
            publish()
        return changed

    @staticmethod
    def reconcile_batch(db: Session, *, limit: int = 100) -> dict:
        """调用方提交/回滚；单案失败留下债务，取消仍回滚本批。"""
        from app.services import case_history_index_debt as debt_service
        from app.services.case_history_vector_reuse import FragmentVectorReuse
        from app.services.local_embedding_service import get_local_embedder

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
        now = datetime.now(timezone.utc)
        db.execute(insert(CaseHistoryIndexCursor).values(
            name=CURSOR_NAME, after_case_id=0, completed_passes=0).on_conflict_do_nothing())
        # UPDATE acquires the SQLite write lock and PostgreSQL row lock before reading the cursor.
        db.execute(update(CaseHistoryIndexCursor).where(CaseHistoryIndexCursor.name == CURSOR_NAME)
                   .values(updated_at=now))
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
        # Terminal failures are deliberately absent. A regular scan can activate
        # them only when the input stamp changes; an admin can explicitly retry.
        due = list(db.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == debt_service.EVENT_TYPE,
            OutboxEvent.status == 'retry', OutboxEvent.available_at <= now)
            .order_by(OutboxEvent.available_at, OutboxEvent.id).limit(limit)
            .execution_options(populate_existing=True)))
        priority_ids.update(int(event.aggregate_id) for event in due
                            if event.aggregate_type == 'case' and event.aggregate_id.isdigit())
        priority_cases = list(db.scalars(select(Case).where(Case.id.in_(priority_ids))
            .order_by(Case.id).execution_options(populate_existing=True))) if priority_ids else []
        cases = list(db.scalars(select(Case).where(Case.id > cursor.after_case_id)
                               .order_by(Case.id).limit(limit).execution_options(populate_existing=True)))
        candidates = priority_cases + [case for case in cases if case.id not in priority_ids]
        ids = {case.id for case in candidates} | priority_ids
        debts = {int(row.aggregate_id): row for row in db.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == debt_service.EVENT_TYPE,
            OutboxEvent.aggregate_type == 'case',
            OutboxEvent.aggregate_id.in_([str(key) for key in ids])))} if ids else {}
        reuse = FragmentVectorReuse(db, get_local_embedder())
        prepared, failures, skipped = [], [], []
        for case in candidates:
            publications, stamp = [], None
            try:
                with db.begin_nested():
                    stamp = debt_service.input_stamp(db, case, reuse)
                    if not debt_service.may_attempt(debts.get(case.id), stamp, now):
                        skipped.append(case.id)
                        continue
                    count = CaseHistoryIndexService.rebuild_case(db, case,
                        publications=publications, vector_reuse=reuse)
                prepared.append((case.id, stamp, count, publications))
            except Exception as exc:
                # A malformed source can fail before the ordinary stamp exists.
                # Persist a bounded, source-free debt instead of poisoning the scan.
                if stamp is None:
                    stamp = {'source_hash': None, 'source_revision_id': None,
                        'rule_version': rule_version(), 'model_version': reuse.identity[1],
                        'encoder_fingerprint': reuse.fingerprint, 'dimension': reuse.dimension,
                        'input_hash': text_hash(f'unreadable:{case.id}:{rule_version()}:{reuse.identity}')}
                    if not debt_service.may_attempt(debts.get(case.id), stamp, now):
                        skipped.append(case.id)
                        continue
                failures.append((case.id, stamp, exc, 'prepare'))
        # Finish every expensive model call before any business-row/FK publication lock.
        changed, succeeded = 0, priority_ids - {case.id for case in priority_cases}
        for case_id, stamp, count, publications in prepared:
            try:
                with db.begin_nested():
                    for publish in publications:
                        publish()
                    db.flush()
                changed += count
                succeeded.add(case_id)
            except Exception as exc:
                failures.append((case_id, stamp, exc, 'publish'))
        for case_id in succeeded:
            debt_service.completed(debts.get(case_id), now)
        for case_id, stamp, exc, stage in failures:
            debts[case_id] = debt_service.failed(db, case_id, stamp, exc, stage, now, debts.get(case_id))
        acknowledged = 0
        for event in pending:
            # The cursor lock serializes this consumer, not the profile consumer.
            # A rollback restores both vectors and this acknowledgement.
            case_id = int(event.aggregate_id)
            if case_id not in succeeded:
                if case_id not in {item[0] for item in failures}:
                    continue
            else:
                event.payload = {**event.payload, 'history_index_pending': False}
                acknowledged += 1
            if event.domain_change_id is not None:
                delivery = db.query(ChangeDelivery).filter_by(
                    change_id=event.domain_change_id, consumer="history_index").first()
                if delivery is not None:
                    debt = debts.get(case_id)
                    delivery.state = "completed" if case_id in succeeded else debt.status
                    delivery.attempts += 1
                    delivery.error = None if case_id in succeeded else debt.error
        if len(cases) < limit:
            cursor.after_case_id = 0
            cursor.completed_passes += 1
        else:
            cursor.after_case_id = cases[-1].id
        db.flush()
        from app.services.history_road_refresh import coalesce_changes
        history_refresh_id = coalesce_changes(db)
        model_state = get_local_embedder().state
        backlog = dict(db.execute(select(OutboxEvent.status, func.count()).where(
            OutboxEvent.event_type == debt_service.EVENT_TYPE,
            OutboxEvent.status.in_(['retry', 'failed'])).group_by(OutboxEvent.status)).all())
        return {"scanned_cases": len(cases), "changed_sources": changed,
                "priority_cases": len(priority_cases), "acknowledged_events": acknowledged,
                "after_case_id": cursor.after_case_id, "completed_passes": cursor.completed_passes,
                "index_version": rule_version(),
                "history_refresh_event_id": history_refresh_id,
                "state": 'degraded' if backlog or reuse.write_failures else 'ready',
                "failed_cases": len(failures), "deferred_cases": len(skipped),
                "failure_codes": sorted({debt_service.error_code(item[2]) for item in failures}),
                "retry_cases": backlog.get('retry', 0), "terminal_failed_cases": backlog.get('failed', 0),
                "reused_vectors": reuse.hits, "encoded_vectors": reuse.encoded,
                "vector_reuse_write_failures": reuse.write_failures,
                "semantic_index_state": 'building' if model_state == 'ready' else model_state}
