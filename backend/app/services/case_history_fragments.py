"""后台生成有原文位置的检索片段；请求端只读取此派生层。"""
import json
import re

from sqlalchemy import delete, select

from app.models.case_history_index import CaseHistoryFragment, CaseHistoryPosting
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash
from app.services.case_semantic_service import SEMANTIC_RULE_VERSION, TEXT_FIELDS, build_semantic_profile
from app.services.local_embedding_service import LocalEmbeddingError, normalized_vector

FRAGMENT_INDEX_VERSION = 'history-fragments-6.3-1'
MAX_FRAGMENT_CHARS = 500
MAX_SOURCE_FRAGMENTS = 512
SENTENCES = re.compile(r'[^。；;！!？?\n]+[。；;！!？?]?')


def condition_term(condition):
    # Hashing keeps unrestricted source-derived clues bounded without changing equality.
    return text_hash(json.dumps(list(condition), ensure_ascii=False, separators=(',', ':')))


def fragment_reference(fragment):
    return {'field': fragment.field, 'source_sha256': fragment.field_hash,
            'start': fragment.start, 'end': fragment.end, 'quote': fragment.quote}


def current_semantics(db, case_id, values, revision):
    """读取绑定当前冻结修订的过程；引用校验不能替代来源版本校验。"""
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_process_contract import validate_process
    if revision is None:
        return {}, None
    profile = db.scalar(select(CaseAnalysisProfile).where(CaseAnalysisProfile.case_id == case_id,
        CaseAnalysisProfile.is_current.is_(True)).order_by(CaseAnalysisProfile.profile_version.desc()).limit(1))
    semantics = ((profile.payload or {}).get('semantics') or {}) if profile is not None else {}
    expected = snapshot_payload(freeze_sources({key: value for key, value in values.items() if key in TEXT_FIELDS}))
    process = semantics.get('process') or {}
    if (profile is None or profile.source_revision_id != revision.id
            or semantics.get('rule_version') != SEMANTIC_RULE_VERSION
            or (semantics.get('source_snapshot') or {}).get('sha256') != expected['sha256']
            or process.get('source_revision_id') != revision.id or process.get('source_hash') != revision.source_hash):
        return {}, None
    try:
        validate_process(process, expected)
    except (KeyError, TypeError, ValueError):
        return {}, None
    return semantics, profile.id


def prepare_fragments(db, parent, values, *, embedder, revision=None):
    from app.services.case_history_retrieval import business_conditions, lexical_terms
    from app.services.case_history_index_service import rule_version
    version = f'{FRAGMENT_INDEX_VERSION}:{rule_version()}'
    revision_id = revision.id if revision is not None else None
    semantics, profile_id = current_semantics(db, parent.case_id, values, revision) if parent.source_type == 'case' else ({}, None)
    process = semantics.get('process') or {}
    stored = list(db.scalars(select(CaseHistoryFragment).where(
        CaseHistoryFragment.case_id == parent.case_id,
        CaseHistoryFragment.source_type == parent.source_type,
        CaseHistoryFragment.source_id == parent.source_id)))
    # Transient copies keep FK writes and row locks out of the model phase.
    existing = [CaseHistoryFragment(**{column.name: getattr(row, column.name)
                for column in CaseHistoryFragment.__table__.columns}) for row in stored]
    manifest = parent.payload.get('fragments') or {}
    unchanged = (manifest.get('version') == version and manifest.get('source_hash') == parent.source_hash
                 and manifest.get('source_revision_id') == revision_id
                 and manifest.get('process_profile_id') == profile_id
                 and manifest.get('count') == len(existing))
    if not unchanged:
        existing = []
        process_refs = {}
        if process:
            for event in process.get('events', []):
                ref = event.get('reference') or {}
                process_refs[(ref.get('field'), ref.get('start'), ref.get('end'))] = event
        omitted = 0
        for field, value in sorted(values.items()):
            if not isinstance(value, str) or not value.strip():
                continue
            spans = {}
            for sentence in SENTENCES.finditer(value):
                for start in range(sentence.start(), sentence.end(), MAX_FRAGMENT_CHARS):
                    end = min(start + MAX_FRAGMENT_CHARS, sentence.end())
                    spans[(start, end)] = start != sentence.start() or end != sentence.end()
            for process_field, start, end in process_refs:
                if process_field == field:
                    spans[(start, end)] = False
            for (start, end), cut_sentence in sorted(spans.items()):
                quote = value[start:end]
                if not quote.strip():
                    continue
                if len(existing) >= MAX_SOURCE_FRAGMENTS:
                    omitted += 1
                    continue
                semantic_field = field if field in TEXT_FIELDS else 'description'
                event = process_refs.get((field, start, end))
                if event:
                    conditions = {('action', item['value'], item['kind']) for item in event.get('actions', [])}
                    conditions.update((item['category'], item['value'], item['kind'])
                        for item in semantics.get('assertions', [])
                        if item['reference']['field'] == field and start <= item['reference']['start']
                        and item['reference']['end'] <= end)
                else:
                    conditions = (business_conditions(build_semantic_profile({semantic_field: quote}))
                                  if not cut_sentence and (field in TEXT_FIELDS or parent.source_type != 'case') else set())
                event_id = event.get('id') if event else None
                key = text_hash(f'{version}:{parent.case_id}:{parent.source_type}:{parent.source_id}:'
                                f'{parent.source_hash}:{revision_id}:{field}:{start}:{end}')
                row = CaseHistoryFragment(id=key, case_id=parent.case_id,
                    source_type=parent.source_type, source_id=parent.source_id,
                    source_hash=parent.source_hash, source_revision_id=revision_id,
                    rule_version=version, kind=('confirmed_experience' if parent.source_type != 'case'
                        else 'process' if event_id else 'statement'), field=field,
                    field_hash=text_hash(value), start=start, end=end, quote=quote,
                    conditions=[list(item) for item in sorted(conditions)], process_event_id=event_id,
                    embedding_state=embedder.state)
                existing.append(row)
        parent.payload = {**parent.payload, 'fragments': {'version': version,
            'source_hash': parent.source_hash, 'source_revision_id': revision_id,
            'process_profile_id': profile_id, 'process_state': 'current' if profile_id else 'not_ready',
            'count': len(existing), 'omitted': omitted, 'complete': omitted == 0}}
    changed = not unchanged
    for row in existing:
        if embedder.state != 'ready':
            continue
        if row.model_version == embedder.model_version and row.embedding_state == 'ready':
            continue
        try:
            vector = embedder.encode(row.quote)
            row.embedding = normalized_vector(vector, len(vector))
            row.dimension, row.model_version, row.embedding_state = len(vector), embedder.model_version, 'ready'
        except LocalEmbeddingError:
            row.embedding, row.dimension, row.model_version = None, None, None
            row.embedding_state = 'unavailable'
        changed = True
    def publish():
        if not changed:
            return
        db.execute(delete(CaseHistoryFragment).where(CaseHistoryFragment.case_id == parent.case_id,
            CaseHistoryFragment.source_type == parent.source_type, CaseHistoryFragment.source_id == parent.source_id))
        db.flush()
        db.add_all(existing)
        db.flush()
        for row in existing:
            postings = [('lexical', term) for term in sorted(lexical_terms(row.quote))]
            postings += [('structural', condition_term(item)) for item in row.conditions]
            db.add_all(CaseHistoryPosting(fragment_id=row.id, case_id=row.case_id, branch=branch, term=term)
                       for branch, term in postings)
    return int(changed), publish


def invalidate_experience_fragments(db, case_id):
    """经验人工状态改变时同事务移除派生项；后台轮询负责再生成。"""
    from app.models.case_history_index import CaseHistoryIndex
    for row in db.scalars(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == case_id,
        CaseHistoryIndex.source_type.in_(['experience_card', 'legacy_experience_card']))):
        db.delete(row)
