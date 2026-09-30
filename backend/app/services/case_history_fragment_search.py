"""三路独立召回持久片段，限量复核来源；不在请求中逐案提取。"""
from datetime import datetime, timezone
import json
import math
import time

from sqlalchemy import and_, case as sql_case, func, or_, select

from app.models.case import Case
from app.models.case_history_index import CaseHistoryFragment as Fragment, CaseHistoryIndex, CaseHistoryPosting
from app.models.case_source import CaseRevision
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_history_fragments import FRAGMENT_INDEX_VERSION, condition_term, fragment_reference
from app.services.case_history_index_service import cached_features, content_hash, rule_version
from app.services.case_search_service import CaseSearchService
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash
from app.services.case_semantic_service import build_semantic_profile
from app.services.local_embedding_service import LocalEmbeddingError, get_local_embedder, normalized_vector

RETRIEVAL_VERSION = 'case-history-6.3-fragments-1'
FUSION_VERSION = 'history-rrf-three-6.3-1'
MIN_SEMANTIC_SUPPORT = 0.5


def _case_hash(case):
    from app.services.case_history_retrieval import source_values
    return snapshot_payload(freeze_sources(source_values(case)))['sha256']


def _source_condition_references(case, source_hash):
    return [{'id': f'case:{case.id}', 'source_text_hash': source_hash,
        'reference': {'field': field, 'source_sha256': text_hash(value), 'start': 0,
                      'end': len(value), 'quote': value}}
        for field in ('facility_type', 'oil_type', 'modus_operandi', 'location', 'upstream_source', 'downstream_destination')
        if isinstance((value := getattr(case, field)), str) and value]


def _parent_join():
    return and_(Fragment.case_id == CaseHistoryIndex.case_id,
                Fragment.source_type == CaseHistoryIndex.source_type,
                Fragment.source_id == CaseHistoryIndex.source_id)


def _latest_revision():
    return select(func.max(CaseRevision.id)).where(CaseRevision.case_id == Fragment.case_id).correlate(Fragment).scalar_subquery()


def _current_parent_revision():
    latest = select(func.max(CaseRevision.id)).where(CaseRevision.case_id == CaseHistoryIndex.case_id).correlate(CaseHistoryIndex).scalar_subquery()
    identifier = CaseHistoryIndex.payload['fragments']['source_revision_id'].as_integer()
    return or_(identifier == latest, and_(identifier.is_(None), latest.is_(None)))


def _sqlite_distance(db, vector):
    """SQLite 测试后端也在数据库内排序，不拉取全量向量/案件到请求。"""
    query = normalized_vector(vector, len(vector))
    def cosine(raw):
        try:
            values = normalized_vector(json.loads(raw), len(query))
            return max(0.0, min(2.0, 1 - sum(a * b for a, b in zip(values, query))))
        except (ValueError, TypeError, LocalEmbeddingError):
            return None
    db.connection().connection.driver_connection.create_function('history_fragment_cosine', 1, cosine)
    return func.history_fragment_cosine(Fragment.embedding)


def validate_fragment_item(db, item):
    """保存/读取/追问/导出均复核实际原文，不依赖派生索引继续存在。"""
    from app.services.case_history_retrieval import _asset_access, source_values
    if type(item.get('case_id')) is not int or type(item.get('source_id')) is not int:
        raise ValueError('history_identifier_invalid')
    case = db.scalar(select(Case).where(Case.id == item['case_id']).execution_options(populate_existing=True))
    if case is None:
        raise ValueError('history_case_unavailable')
    source_type, source_id = item['source_type'], item['source_id']
    versions = item['versions']
    fragment = item['fragment']
    if fragment.get('source_revision_id') is not None and type(fragment['source_revision_id']) is not int:
        raise ValueError('history_revision_invalid')
    if source_type == 'case':
        if source_id != case.id or _case_hash(case) != versions['source_text_hash']:
            raise ValueError('history_case_changed')
        values = source_values(case)
        parent_hash = versions['source_text_hash']
        extra_refs = _source_condition_references(case, parent_hash)
        revision_id = db.scalar(select(func.max(CaseRevision.id)).where(CaseRevision.case_id == case.id))
        if fragment.get('source_revision_id') != revision_id:
            raise ValueError('history_revision_changed')
    elif source_type == 'experience_card':
        asset = db.scalar(select(KnowledgeAsset).where(KnowledgeAsset.id == source_id,
            KnowledgeAsset.source_case_id == case.id, KnowledgeAsset.asset_type == 'experience_card')
            .execution_options(populate_existing=True))
        if (asset is None or asset.status != 'confirmed' or not _asset_access(db, asset)
                or asset.version != versions['asset_version']
                or asset.source_signature != versions['source_signature']
                or content_hash(asset.content if isinstance(asset.content, dict) else {}) != versions['content_hash']
                or text_hash(json.dumps(asset.evidence_refs, sort_keys=True, ensure_ascii=False)) != versions['evidence_refs_hash']):
            raise ValueError('history_experience_changed')
        values = {'description': str((asset.content or {}).get('summary') or '')}
        parent_hash, extra_refs = versions['content_hash'], asset.evidence_refs
    elif source_type == 'legacy_experience_card':
        if db.scalar(select(KnowledgeAsset.id).where(KnowledgeAsset.source_case_id == case.id,
            KnowledgeAsset.asset_type == 'experience_card').limit(1)) is not None:
            raise ValueError('history_experience_replaced')
        card = ((case.features or {}).get('intelligence') or {}).get('experience_card') or {}
        if (source_id != case.id or card.get('manual_review_status') != 'confirmed'
                or content_hash(card) != versions['content_hash']):
            raise ValueError('history_experience_changed')
        values = {'description': str(card.get('summary') or '')}
        parent_hash, extra_refs = versions['content_hash'], [{'id': f'case:{case.id}'}]
    else:
        raise ValueError('history_source_unknown')
    reference = fragment['reference']
    text = values.get(reference['field'])
    start, end = reference['start'], reference['end']
    if (not isinstance(text, str) or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(text) or text_hash(text) != reference['source_sha256']
            or text[start:end] != reference['quote'] or item['snippet'] != reference['quote']):
        raise ValueError('history_fragment_changed')
    expected_id = text_hash(f"{versions['fragment_index_version']}:{case.id}:{source_type}:{source_id}:"
                            f"{parent_hash}:{fragment.get('source_revision_id')}:{reference['field']}:{start}:{end}")
    evidence_id = f'knowledge_asset:{source_id}' if source_type == 'experience_card' else f'case:{case.id}'
    expected_refs = [{'id': evidence_id, 'source_text_hash': parent_hash, 'reference': reference}, *extra_refs]
    if fragment['id'] != expected_id or item['evidence_refs'] != expected_refs:
        raise ValueError('history_fragment_evidence_changed')
    if fragment.get('kind') == 'process':
        from app.services.case_history_fragments import current_semantics
        from app.services.case_source_service import CaseSourceService
        semantics, profile_id = current_semantics(db, case.id, source_values(case), CaseSourceService.latest_revision(db, case.id))
        event = next((row for row in (semantics.get('process') or {}).get('events', [])
                      if row['id'] == fragment.get('process_event_id')), None)
        if (profile_id != versions.get('process_profile_id') or event is None
                or any(event['reference'].get(key) != value for key, value in reference.items())):
            raise ValueError('history_process_changed')
    return case


def search_fragments(db, *, query='', source_case_id=None, filters=None, limit=3,
                     reuse_only=False, query_conditions=None, deadline=None,
                     exclude_case_sources=None, source_types=None, experience_status='confirmed',
                     cancelled=lambda: False, embedding_model=None, semantic_only=False,
                     min_similarity=MIN_SEMANTIC_SUPPORT, candidate_area_ids=None):
    from app.services.case_history_retrieval import (HistoryUnavailable, SCAN_SECONDS, business_conditions,
                                                    compare, lexical_terms, source_values, _asset_access,
                                                    get_local_embedder, build_semantic_profile)
    if 'authorized_area_ids' not in db.info:
        raise HistoryUnavailable('history_unavailable')
    area, allowed = (filters or {}).get('operational_area_id'), db.info['authorized_area_ids']
    if area is not None and allowed is not None and area not in allowed:
        raise HistoryUnavailable('history_unavailable')
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError('invalid_history_query')
    if query_conditions is not None and any(not isinstance(item, tuple) or len(item) != 3
        or any(not isinstance(value, str) or not value for value in item) for item in query_conditions):
        raise ValueError('invalid_history_conditions')
    started = time.monotonic()
    stop = min(started + SCAN_SECONDS, deadline) if deadline is not None else started + SCAN_SECONDS
    interrupted = lambda: cancelled() or time.monotonic() > stop
    version = f'{FRAGMENT_INDEX_VERSION}:{rule_version()}'
    with db.no_autoflush:
        source = None
        source_query = not query.strip() and source_case_id is not None
        if source_case_id is not None:
            source = db.scalar(select(Case).where(Case.id == source_case_id).execution_options(populate_existing=True))
            if source is None:
                raise HistoryUnavailable('history_unavailable')
            if not query.strip():
                query = '。'.join(value for value in source_values(source).values() if value)
        if not query.strip():
            raise ValueError('history_query_required')
        query_semantics = {}
        if source_query and source is not None and query_conditions is None:
            from app.services.case_history_fragments import current_semantics
            from app.services.case_source_service import CaseSourceService
            query_semantics, _ = current_semantics(db, source.id, source_values(source), CaseSourceService.latest_revision(db, source.id))
        conditions = query_conditions if query_conditions is not None else business_conditions(
            query_semantics or build_semantic_profile({'description': query}))
        terms = lexical_terms(query)
        filtered = CaseSearchService.filtered_query(db, **(filters or {}))
        if candidate_area_ids is not None:
            filtered = filtered.filter(Case.operational_area_id.in_(candidate_area_ids))
        if source_case_id is not None:
            filtered = filtered.filter(Case.id != source_case_id)
        case_ids = filtered.with_entities(Case.id).statement
        total = filtered.count()
        latest = _latest_revision()
        current_revision = or_(Fragment.source_type != 'case',
            Fragment.source_revision_id == latest,
            and_(Fragment.source_revision_id.is_(None), latest.is_(None)))
        clauses = [Fragment.case_id.in_(case_ids), Fragment.rule_version == version,
            CaseHistoryIndex.rule_version == rule_version(), Fragment.source_hash == CaseHistoryIndex.source_hash,
            CaseHistoryIndex.payload['fragments']['version'].as_string() == version,
            current_revision]
        if source_types is not None:
            clauses.append(Fragment.source_type.in_(source_types))
        if exclude_case_sources:
            clauses.append(or_(Fragment.source_type != 'case', ~Fragment.case_id.in_(exclude_case_sources)))
        # Only confirmed experiences enter this index. Draft/archived adapters
        # get an explicit unavailable population instead of mixing trust levels.
        excluded_status = experience_status != 'confirmed'
        if excluded_status:
            clauses.append(Fragment.source_type == '__no_confirmed_source__')
        base = select(Fragment).join(CaseHistoryIndex, _parent_join()).where(*clauses)
        fragment_total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
        indexed_case_ids = select(Fragment.case_id).join(CaseHistoryIndex, _parent_join()).where(
            Fragment.case_id.in_(case_ids), Fragment.source_type == 'case', Fragment.rule_version == version,
            CaseHistoryIndex.rule_version == rule_version(),
            CaseHistoryIndex.payload['fragments']['version'].as_string() == version, current_revision).distinct()
        indexed_cases = db.scalar(select(func.count()).select_from(indexed_case_ids.subquery())) or 0
        missing_cases = max(0, total - indexed_cases)
        # An empty source still has a complete manifest; count its parent as indexed.
        empty_parents = db.scalar(select(func.count()).select_from(CaseHistoryIndex).where(
            CaseHistoryIndex.case_id.in_(case_ids), CaseHistoryIndex.source_type == 'case',
            CaseHistoryIndex.rule_version == rule_version(),
            CaseHistoryIndex.payload['fragments']['version'].as_string() == version,
            _current_parent_revision(),
            CaseHistoryIndex.payload['fragments']['count'].as_integer() == 0)) or 0
        indexed_cases += empty_parents
        missing_cases = max(0, total - indexed_cases)
        # Rebuild selects the newest confirmed version per case, not every
        # historically confirmed version (or a newer draft/archived version).
        confirmed_versions = select(KnowledgeAsset.source_case_id,
            func.max(KnowledgeAsset.version).label('version')).where(
            KnowledgeAsset.source_case_id.in_(case_ids), KnowledgeAsset.asset_type == 'experience_card',
            KnowledgeAsset.status == 'confirmed').group_by(KnowledgeAsset.source_case_id).subquery()
        confirmed_assets = select(KnowledgeAsset.id).join(confirmed_versions, and_(
            KnowledgeAsset.source_case_id == confirmed_versions.c.source_case_id,
            KnowledgeAsset.version == confirmed_versions.c.version)).where(
            KnowledgeAsset.asset_type == 'experience_card', KnowledgeAsset.status == 'confirmed')
        missing_assets = db.scalar(select(func.count()).select_from(KnowledgeAsset).where(
            KnowledgeAsset.id.in_(confirmed_assets), ~KnowledgeAsset.id.in_(select(func.cast(CaseHistoryIndex.source_id, KnowledgeAsset.id.type)).where(
                CaseHistoryIndex.source_type == 'experience_card', CaseHistoryIndex.rule_version == rule_version())))) or 0
        incomplete_sources = db.scalar(select(func.count()).select_from(CaseHistoryIndex).where(
            CaseHistoryIndex.case_id.in_(case_ids), CaseHistoryIndex.payload['fragments']['complete'].as_boolean().is_(False))) or 0
        from app.models.case_pipeline import CaseAnalysisProfile
        revision_hash = select(CaseRevision.source_hash).where(CaseRevision.case_id == CaseHistoryIndex.case_id).order_by(
            CaseRevision.revision.desc()).limit(1).correlate(CaseHistoryIndex).scalar_subquery()
        current_profile = select(CaseAnalysisProfile.id).where(
            CaseAnalysisProfile.id == CaseHistoryIndex.payload['fragments']['process_profile_id'].as_string(),
            CaseAnalysisProfile.is_current.is_(True),
            CaseAnalysisProfile.payload['semantics']['process']['source_hash'].as_string() == revision_hash).correlate(CaseHistoryIndex).exists()
        process_current = db.scalar(select(func.count()).select_from(CaseHistoryIndex).where(
            CaseHistoryIndex.case_id.in_(case_ids), CaseHistoryIndex.source_type == 'case',
            CaseHistoryIndex.rule_version == rule_version(),
            CaseHistoryIndex.payload['fragments']['version'].as_string() == version,
            _current_parent_revision(), current_profile,
            CaseHistoryIndex.payload['fragments']['process_state'].as_string() == 'current')) or 0
        capacity = max(100, 3 * limit + 60)
        branches, branch_counts, truncated = {}, {}, False
        for branch, tokens in (('structural', {condition_term(item) for item in conditions}), ('lexical', terms)):
            if interrupted():
                branches[branch], branch_counts[branch] = [], 0
                continue
            if not tokens or semantic_only:
                branches[branch], branch_counts[branch] = [], 0
                continue
            score = func.count(CaseHistoryPosting.term).label('support')
            matches = select(Fragment.id, score).join(CaseHistoryIndex, _parent_join()).join(
                CaseHistoryPosting, CaseHistoryPosting.fragment_id == Fragment.id).where(*clauses,
                CaseHistoryPosting.branch == branch, CaseHistoryPosting.term.in_(tokens)).group_by(Fragment.id)
            rows = list(db.execute(matches.order_by(score.desc(), Fragment.id).limit(capacity + 1)))
            truncated |= len(rows) > capacity
            branches[branch] = [row.id for row in rows[:capacity]]
            branch_counts[branch] = len(rows[:capacity])
        embedder = embedding_model or get_local_embedder()
        semantic_state, vector = embedder.state, None
        if semantic_state == 'ready' and not interrupted():
            try:
                vector = embedder.encode(query)
            except LocalEmbeddingError:
                semantic_state = 'unavailable'
        vector_total, semantic_distances = 0, {}
        branches['semantic'], branch_counts['semantic'] = [], 0
        if vector is not None and not interrupted():
            vector_clauses = [Fragment.embedding_state == 'ready', Fragment.embedding.is_not(None),
                Fragment.model_version == embedder.model_version, Fragment.dimension == len(vector)]
            if db.get_bind().dialect.name == 'postgresql':
                vector_clauses.append(func.vector_dims(Fragment.embedding) == len(vector))
            vector_total = db.scalar(select(func.count()).select_from(base.where(*vector_clauses).subquery())) or 0
            distance = (sql_case((and_(Fragment.dimension == len(vector), func.vector_dims(Fragment.embedding) == len(vector)),
                                 Fragment.embedding.cosine_distance(vector)), else_=None) if db.get_bind().dialect.name == 'postgresql'
                        else _sqlite_distance(db, vector))
            matches = select(Fragment.id, distance.label('distance')).join(CaseHistoryIndex, _parent_join()).where(
                *clauses, *vector_clauses, distance <= 1 - min_similarity)
            rows = list(db.execute(matches.order_by(distance, Fragment.id).limit(capacity + 1)))
            truncated |= len(rows) > capacity
            branches['semantic'] = [row.id for row in rows[:capacity] if row.distance is not None and math.isfinite(row.distance)]
            semantic_distances = {row.id: float(row.distance) for row in rows[:capacity]
                                  if row.distance is not None and math.isfinite(row.distance)}
            branch_counts['semantic'] = len(branches['semantic'])
            if vector_total < fragment_total:
                semantic_state = 'partial'
        elif semantic_state == 'ready':
            semantic_state = 'partial'
        ids = set().union(*(set(items) for items in branches.values()))
        fragments = list(db.scalars(base.where(Fragment.id.in_(ids)))) if ids and not interrupted() else []
        parents = {(row.case_id, row.source_type, row.source_id): row for row in db.scalars(
            select(CaseHistoryIndex).where(CaseHistoryIndex.case_id.in_({row.case_id for row in fragments}))
            .execution_options(populate_existing=True))} if fragments else {}
        cases = {row.id: row for row in db.scalars(select(Case).where(Case.id.in_({row.case_id for row in fragments}))
            .execution_options(populate_existing=True))} if fragments else {}
        assets = {row.id: row for row in db.scalars(select(KnowledgeAsset).where(KnowledgeAsset.id.in_(
            [int(row.source_id) for row in fragments if row.source_type == 'experience_card']))
            .execution_options(populate_existing=True))} if fragments else {}
        ranks = {branch: {key: rank for rank, key in enumerate(items, 1)} for branch, items in branches.items()}
        valid, invalidated, checked_cases, invalidated_cases = [], 0, set(), set()
        for fragment in fragments:
            if interrupted():
                break
            case = cases.get(fragment.case_id)
            if case is None:
                invalidated += 1
                continue
            checked_cases.add(case.id)
            parent = parents.get((fragment.case_id, fragment.source_type, fragment.source_id))
            features = cached_features(parent, fragment.source_hash)
            if features is None:
                invalidated += 1
                invalidated_cases.add(case.id)
                continue
            parent_comparison = compare(query, conditions, '', features[1])
            if parent_comparison['different_conditions'] and not parent_comparison['shared_conditions']:
                continue
            versions = {'retrieval_version': RETRIEVAL_VERSION, 'lexical_index_version': rule_version(),
                'fragment_index_version': version, 'fusion_version': FUSION_VERSION,
                'embedding_model_version': fragment.model_version if fragment.id in ranks['semantic'] else None}
            if fragment.kind == 'process':
                versions['process_profile_id'] = parent.payload['fragments'].get('process_profile_id')
            if fragment.source_type == 'case':
                title, refs = f'历史案件 {case.case_number}', _source_condition_references(case, fragment.source_hash)
                versions['source_text_hash'] = fragment.source_hash
            elif fragment.source_type == 'experience_card':
                asset = assets.get(int(fragment.source_id))
                if asset is None:
                    invalidated += 1
                    continue
                title, refs = asset.title, asset.evidence_refs
                versions.update(asset_version=asset.version, source_signature=asset.source_signature,
                    evidence_refs_hash=text_hash(json.dumps(asset.evidence_refs, sort_keys=True, ensure_ascii=False)),
                    content_hash=fragment.source_hash)
            else:
                title, refs = f'已确认历史经验 {case.case_number}', [{'id': f'case:{case.id}'}]
                versions['content_hash'] = fragment.source_hash
            comparison = compare(query, conditions, fragment.quote, {tuple(row) for row in fragment.conditions})
            # Purely opposite assertions are evidence of difference, not a positive retrieval match.
            if comparison['different_conditions'] and not comparison['shared_conditions']:
                continue
            evidence = {'id': f'case:{case.id}' if fragment.source_type == 'case' else f'knowledge_asset:{fragment.source_id}',
                'source_text_hash': fragment.source_hash, 'reference': fragment_reference(fragment)}
            if fragment.source_type == 'legacy_experience_card':
                evidence['id'] = f'case:{case.id}'
            item = {'source_type': fragment.source_type, 'source_id': int(fragment.source_id),
                'case_id': case.id, 'case_number': case.case_number, 'title': title, 'snippet': fragment.quote,
                'route': f'/cases?caseId={case.id}', 'versions': versions, 'evidence_refs': [evidence, *refs],
                'profile_state': 'indexed_fragment', 'derived_state': 'available', **comparison,
                'source_shared_conditions': parent_comparison['shared_conditions'],
                'source_different_conditions': parent_comparison['different_conditions'],
                'source_conditions_boundary': '整份来源的共同条件；不表示这些条件属于同一过程事件。',
                'fragment': {'id': fragment.id, 'kind': fragment.kind, 'reference': fragment_reference(fragment),
                    'source_revision_id': fragment.source_revision_id, 'process_event_id': fragment.process_event_id},
                'structural_rank': ranks['structural'].get(fragment.id), 'lexical_rank': ranks['lexical'].get(fragment.id),
                'semantic_rank': ranks['semantic'].get(fragment.id),
                'semantic_distance': semantic_distances.get(fragment.id),
                'semantic_similarity': (round(1 - semantic_distances[fragment.id], 6)
                                        if fragment.id in semantic_distances else None),
                'operational_area_id': case.operational_area_id,
                'score': round(sum(1 / (60 + values[fragment.id]) for values in ranks.values() if fragment.id in values), 8),
                'matching_basis': '结构条件、词项与本地语义独立召回后融合；名次不是准确概率'}
            try:
                validate_fragment_item(db, item)
            except (KeyError, TypeError, ValueError):
                invalidated += 1
                invalidated_cases.add(case.id)
                continue
            valid.append(item)
        ranked, seen = [], set()
        for item in sorted(valid, key=lambda row: (-row['score'], row['fragment']['id'])):
            parent_key = (item['case_id'], item['source_type'], item['source_id'])
            if parent_key not in seen:
                seen.add(parent_key)
                ranked.append(item)
        timed_out = interrupted()
        vector_missing = max(0, fragment_total - vector_total) if embedder.state == 'ready' else 0
        if invalidated and embedder.state == 'ready':
            semantic_state = 'partial'
            vector_missing += invalidated
        missing = missing_cases + missing_assets + len(invalidated_cases)
        partial = bool(missing or invalidated or incomplete_sources or truncated or timed_out
                       or excluded_status or semantic_state in {'partial', 'unavailable'})
        source_revision_id = db.scalar(select(func.max(CaseRevision.id)).where(CaseRevision.case_id == source.id)) if source else None
        context = {'query_sha256': text_hash(query), 'source_text_hash': _case_hash(source) if source else None,
            'source_revision_id': source_revision_id,
            'scope_hash': text_hash(json.dumps(allowed, sort_keys=True)), 'filters': filters or {},
            'retrieval_version': RETRIEVAL_VERSION, 'embedding_model_version': embedder.model_version if vector else None,
            'fusion_version': FUSION_VERSION}
        if reuse_only:
            context.update(reuse_only=True, conditions=[list(item) for item in sorted(conditions)])
        if source_types:
            context.update(source_types=sorted(source_types), experience_status=experience_status)
        return {'schema_version': 'case-history-6.3-1', 'state': 'partial' if partial else 'ready',
            'mode': 'hybrid_local' if vector_total else 'lexical_fallback', 'retrieval_mode': 'fragment_index',
            'index_state': 'pending' if total and not indexed_cases else 'partial' if missing or invalidated or incomplete_sources else 'ready',
            'semantic_index_state': semantic_state, 'source_case_id': source_case_id, 'query_context': context,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'coverage': {'authorized_cases': total, 'scanned_cases': len(checked_cases), 'matched_sources': len(seen),
                'indexed_sources': indexed_cases + max(0, len(assets)), 'fallback_sources': missing,
                'vector_sources': vector_total, 'vector_missing': vector_missing, 'missing_derived_sources': missing,
                'scan_complete': not timed_out, 'recency_limit': None, 'complete': not partial, 'budget_seconds': SCAN_SECONDS,
                'indexed_cases': indexed_cases, 'missing_index_cases': missing_cases, 'missing_experience_indexes': missing_assets,
                'indexed_fragments': fragment_total, 'recalled_fragments': len(ids), 'validated_fragments': len(valid),
                'invalidated_fragments': invalidated, 'branch_counts': branch_counts, 'recall_limit': capacity,
                'recall_truncated': truncated, 'cancelled': bool(cancelled()), 'execution_mode': 'indexed_reference_lookup',
                'process_indexed_cases': process_current, 'process_missing_cases': max(0, total - process_current),
                'process_index_state': 'current' if process_current == total else 'partial' if process_current else 'not_ready'},
            'items': ranked[:limit],
            'boundary': '片段索引检索仅提供少量历史参考，不是全量统计；索引缺失、过期或预算未完成不能解释为没有历史资料。共同条件、不同表述和语义相近均须核对适用性，不成为当前案件事实，排序不是准确概率。'}
