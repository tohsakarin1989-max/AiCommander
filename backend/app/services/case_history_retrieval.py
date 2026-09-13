"""统一历史召回的只读基线；流式遍历授权集合，不以最近 N 条冒充全库。

结构条件、词项与可选本地向量共用此契约；不可用时显式降级。
"""
from datetime import datetime, timezone
import heapq
import json
import re
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_history_index import CaseHistoryIndex
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_search_service import CaseSearchService
from app.services.case_history_index_service import cached_features, content_hash, rule_version
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload, text_hash
from app.services.case_semantic_service import SEMANTIC_RULE_VERSION, TEXT_FIELDS, build_semantic_profile
from app.services.local_embedding_service import get_local_embedder, LocalEmbeddingError
from app.services.case_history_vector_service import exact_distances
from app.services.history_rank_fusion import HistoryRankFusion, FUSION_VERSION


RETRIEVAL_VERSION = "case-history-5.1-hybrid-2"
BATCH_SIZE = 100
SCAN_SECONDS = 5.0
HISTORY_METADATA_FIELDS = ('case_number', 'case_type', 'source_type', 'report_unit', 'oil_nature')


class HistoryUnavailable(PermissionError):
    pass


def source_values(case: Case) -> dict:
    # Metadata remains searchable, but is not promoted into semantic assertions.
    return {field: getattr(case, field) for field in (*TEXT_FIELDS, *HISTORY_METADATA_FIELDS)}


def lexical_terms(text: str) -> set[str]:
    terms = set()
    for word in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", word) and len(word) > 2:
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
        else:
            terms.add(word)
    return terms


def business_conditions(semantics: dict) -> set[tuple[str, str, str]]:
    # 优先手法、地点和链条条件，不用姓名、车牌等身份要素打相似分。
    categories = {"method", "place_condition", "time_condition", "facility", "oil", "tool", "vehicle",
                  "upstream_clue", "downstream_clue"}
    result = {(item["category"], item["value"], item["kind"])
              for item in semantics.get("assertions", []) if item["category"] in categories}
    for fragment in (semantics.get("event_fragments") or {}).get("items", []):
        result.update(("action", action["value"], action["kind"]) for action in fragment["actions"])
    return result


def compare(query_text: str, query_conditions: set, candidate_text: str, candidate_conditions: set,
            *, candidate_terms: set | None = None) -> dict:
    terms = lexical_terms(query_text)
    lexical = len(terms & (candidate_terms if candidate_terms is not None else lexical_terms(candidate_text))) / max(1, len(terms))
    shared = query_conditions & candidate_conditions
    oppositions = {(category, value, kind) for category, value, kind in candidate_conditions
                   if any(category == c and value == v and kind != k for c, v, k in query_conditions)}
    # 只有词面相同、所有已知业务条件的极性均相反时，不把词面分充作相关依据。
    if oppositions and not shared:
        lexical = 0.0
    weights = {"method": 4, "action": 4, "place_condition": 3, "upstream_clue": 3, "downstream_clue": 3,
               "time_condition": 2, "facility": 2, "oil": 2, "tool": 2, "vehicle": 1}
    support = sum(weights.get(item[0], 1) for item in shared) / max(1, sum(weights.get(item[0], 1) for item in query_conditions))
    score = round(0.7 * support + 0.3 * lexical, 6)
    return {"score": score, "score_kind": "retrieval_support_not_probability",
            "shared_conditions": [list(item) for item in sorted(shared)],
            "different_conditions": [list(item) for item in sorted(oppositions)],
            "unmatched_query_conditions": [list(item) for item in sorted(query_conditions - candidate_conditions)]}


def _asset_access(db: Session, asset: KnowledgeAsset) -> bool:
    # 新检索不沿用经验资产仅检查主案的旧交付方式。
    if not isinstance(asset.evidence_refs, list) or not asset.evidence_refs:
        return False
    for reference in asset.evidence_refs:
        ref = reference.get("id") if isinstance(reference, dict) else reference
        if not isinstance(ref, str):
            return False
        if match := re.fullmatch(r"case:([1-9][0-9]*)", ref):
            exists = db.scalar(select(Case.id).where(Case.id == int(match[1])))
        elif match := re.fullmatch(r"case_evidence:([1-9][0-9]*)", ref):
            exists = db.scalar(select(CaseEvidence.id).where(CaseEvidence.id == int(match[1])))
        else:
            return False
        if exists is None:
            return False
    return True


class CaseHistoryRetrieval:
    @staticmethod
    def search(db: Session, *, query: str = "", source_case_id: int | None = None,
               filters: dict | None = None, limit: int = 3) -> dict:
        if "authorized_area_ids" not in db.info:
            raise HistoryUnavailable("history_unavailable")
        area = (filters or {}).get("operational_area_id")
        allowed = db.info["authorized_area_ids"]
        if area is not None and allowed is not None and area not in allowed:
            raise HistoryUnavailable("history_unavailable")
        if not 1 <= limit <= 20 or len(query) > 2000:
            raise ValueError("invalid_history_query")
        started = time.monotonic()
        source = None
        with db.no_autoflush:
            if source_case_id is not None:
                source = db.scalar(select(Case).where(Case.id == source_case_id)
                                   .execution_options(populate_existing=True))
                if source is None:
                    raise HistoryUnavailable("history_unavailable")
            if not query.strip() and source is not None:
                query = "。".join(value for value in source_values(source).values() if value)
            if not query.strip():
                raise ValueError("history_query_required")
            query_context = {"query_sha256": text_hash(query),
                             "source_text_hash": snapshot_payload(freeze_sources(source_values(source)))["sha256"] if source is not None else None,
                             "scope_hash": text_hash(json.dumps(db.info["authorized_area_ids"], sort_keys=True)),
                             "filters": filters or {}, "retrieval_version": RETRIEVAL_VERSION}
            # 查询短文本只在内网解析；候选优先复用已生成的当前语义画像。
            query_conditions = business_conditions(build_semantic_profile({"description": query}))
            embedder = get_local_embedder()
            vector, vector_state = None, embedder.state
            if vector_state == 'ready':
                try:
                    vector = embedder.encode(query)
                except LocalEmbeddingError:
                    vector_state = 'unavailable'
            query_context['embedding_model_version'] = embedder.model_version if vector is not None else None
            query_context['fusion_version'] = FUSION_VERSION if vector is not None else None
            fusion = HistoryRankFusion() if vector is not None else None
            vector_sources, vector_missing, distances = 0, 0, {}
            filtered = CaseSearchService.filtered_query(db, **(filters or {}))
            if source_case_id is not None:
                filtered = filtered.filter(Case.id != source_case_id)
            upper = filtered.with_entities(func.max(Case.id)).scalar()
            total = filtered.filter(Case.id <= upper).count() if upper is not None else 0
            scanned, matched, cursor, serial = 0, 0, 0, 0
            indexed_sources, fallback_sources = 0, 0
            heap = []
            partial = False

            def offer(item):
                nonlocal serial, matched, vector_sources, vector_missing
                if fusion is not None:
                    key = (item['case_id'], item['source_type'], str(item['source_id']))
                    distance = distances.get(key)
                    vector_sources += int(distance is not None)
                    vector_missing += int(distance is None)
                    item['versions']['embedding_model_version'] = embedder.model_version if distance is not None else None
                    fusion.add(item, 1 - distance if distance is not None else None)
                    return
                if item["score"] <= 0:
                    return
                serial += 1
                matched += 1
                entry = (item["score"], -serial, item)
                if len(heap) < limit:
                    heapq.heappush(heap, entry)
                elif entry[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, entry)

            while upper is not None and cursor < upper:
                if time.monotonic() - started > SCAN_SECONDS:
                    partial = True
                    break
                cases = filtered.filter(Case.id > cursor, Case.id <= upper).order_by(Case.id).limit(BATCH_SIZE)\
                    .execution_options(populate_existing=True).all()
                if not cases:
                    break
                ids = [case.id for case in cases]
                indexes = {(row.case_id, row.source_type, row.source_id): row for row in db.scalars(
                    select(CaseHistoryIndex).where(CaseHistoryIndex.case_id.in_(ids))
                    .execution_options(populate_existing=True))}
                profiles = {}
                for profile in db.scalars(select(CaseAnalysisProfile).where(
                    CaseAnalysisProfile.case_id.in_(ids), CaseAnalysisProfile.is_current.is_(True)
                ).order_by(CaseAnalysisProfile.profile_version.desc()).execution_options(populate_existing=True)):
                    profiles.setdefault(profile.case_id, profile)
                assets, dedicated = {}, set()
                for asset in db.scalars(select(KnowledgeAsset).where(
                    KnowledgeAsset.source_case_id.in_(ids), KnowledgeAsset.asset_type == "experience_card"
                ).order_by(KnowledgeAsset.version.desc()).execution_options(populate_existing=True)):
                    dedicated.add(asset.source_case_id)
                    if asset.status == "confirmed":
                        assets.setdefault(asset.source_case_id, asset)
                if fusion is not None:
                    sources = {(case.id, 'case', str(case.id)): snapshot_payload(freeze_sources(source_values(case)))['sha256'] for case in cases}
                    for case in cases:
                        asset = assets.get(case.id)
                        if asset is not None and _asset_access(db, asset):
                            sources[(case.id, 'experience_card', str(asset.id))] = content_hash(asset.content if isinstance(asset.content, dict) else {})
                        elif case.id not in dedicated:
                            legacy = ((case.features or {}).get('intelligence') or {}).get('experience_card') or {}
                            if isinstance(legacy, dict) and legacy.get('manual_review_status') == 'confirmed':
                                sources[(case.id, 'legacy_experience_card', str(case.id))] = content_hash(legacy)
                    distances = exact_distances(db, sources=sources, vector=vector, model_version=embedder.model_version)
                for case in cases:
                    if time.monotonic() - started > SCAN_SECONDS:
                        partial = True
                        break
                    values = source_values(case)
                    snapshot = snapshot_payload(freeze_sources(values))
                    profile = profiles.get(case.id)
                    semantics = (profile.payload or {}).get("semantics") if profile is not None else None
                    semantic_snapshot = snapshot_payload(freeze_sources({field: values[field] for field in TEXT_FIELDS}))
                    valid_profile = bool(semantics and semantics.get("rule_version") == SEMANTIC_RULE_VERSION
                                         and (semantics.get("source_snapshot") or {}).get("sha256") == semantic_snapshot["sha256"])
                    cached = cached_features(indexes.get((case.id, "case", str(case.id))), snapshot["sha256"])
                    if not valid_profile and cached is None:
                        semantics = build_semantic_profile({field: values[field] for field in TEXT_FIELDS})
                    candidate_text = "。".join(value for value in values.values() if value)
                    indexed_sources += int(cached is not None)
                    fallback_sources += int(cached is None)
                    comparison = compare(query, query_conditions, candidate_text,
                                         cached[1] if cached is not None else business_conditions(semantics),
                                         candidate_terms=cached[0] if cached is not None else None)
                    version = {"source_text_hash": snapshot["sha256"], "profile_id": profile.id if valid_profile else None,
                               "profile_rule": profile.dictionary_version if valid_profile else None,
                               "retrieval_version": RETRIEVAL_VERSION,
                               "lexical_index_version": rule_version() if cached is not None else None}
                    snippet_field = "description" if case.description else "location"
                    snippet_source = getattr(case, snippet_field) or ""
                    metadata_refs = [
                        {"id": f"case:{case.id}", "source_text_hash": snapshot['sha256'],
                         "reference": {"field": field, "source_sha256": text_hash(values[field]),
                                       "start": 0, "end": len(values[field][:500]), "quote": values[field][:500]}}
                        for field in HISTORY_METADATA_FIELDS if values[field]
                        and lexical_terms(query).intersection(lexical_terms(values[field]))]
                    offer({"source_type": "case", "source_id": case.id, "case_id": case.id,
                           "case_number": case.case_number, "title": f"历史案件 {case.case_number}",
                           "snippet": (case.description or case.location or "")[:500],
                           "route": f"/cases?caseId={case.id}", "versions": version,
                           "evidence_refs": [{"id": f"case:{case.id}", "source_text_hash": snapshot["sha256"],
                                              "reference": {"field": snippet_field, "source_sha256": text_hash(snippet_source),
                                                            "start": 0, "end": len(snippet_source[:500]), "quote": snippet_source[:500]}}] + metadata_refs,
                           "profile_state": "current" if valid_profile else "lexical_fallback",
                           **comparison})
                    asset = assets.get(case.id)
                    if asset is not None and _asset_access(db, asset):
                        content = asset.content if isinstance(asset.content, dict) else {}
                        text = str(content.get("summary") or "")
                        cached = cached_features(indexes.get((case.id, "experience_card", str(asset.id))), content_hash(content))
                        indexed_sources += int(cached is not None)
                        fallback_sources += int(cached is None)
                        offer({"source_type": "experience_card", "source_id": asset.id, "case_id": case.id,
                               "case_number": case.case_number, "title": asset.title, "snippet": text[:500],
                               "route": f"/case-intelligence?caseId={case.id}",
                               "versions": {"asset_version": asset.version, "source_signature": asset.source_signature,
                                            "evidence_refs_hash": text_hash(json.dumps(asset.evidence_refs, sort_keys=True, ensure_ascii=False)),
                                            "content_hash": text_hash(json.dumps(content, sort_keys=True, ensure_ascii=False)),
                                            "retrieval_version": RETRIEVAL_VERSION},
                               "evidence_refs": asset.evidence_refs, "profile_state": "historical_confirmed",
                               **compare(query, query_conditions, text,
                                         cached[1] if cached is not None else business_conditions(build_semantic_profile({"description": text})),
                                         candidate_terms=cached[0] if cached is not None else None)})
                    elif case.id not in dedicated:
                        card = ((case.features or {}).get("intelligence") or {}).get("experience_card") or {}
                        if isinstance(card, dict) and card.get("manual_review_status") == "confirmed":
                            text = str(card.get("summary") or "")
                            cached = cached_features(indexes.get((case.id, "legacy_experience_card", str(case.id))), content_hash(card))
                            indexed_sources += int(cached is not None)
                            fallback_sources += int(cached is None)
                            offer({"source_type": "legacy_experience_card", "source_id": case.id, "case_id": case.id,
                                   "case_number": case.case_number, "title": f"已确认历史经验 {case.case_number}",
                                   "snippet": text[:500], "route": f"/case-intelligence?caseId={case.id}",
                                   "versions": {"content_hash": text_hash(json.dumps(card, sort_keys=True, ensure_ascii=False)),
                                                "retrieval_version": RETRIEVAL_VERSION},
                                   "evidence_refs": [{"id": f"case:{case.id}"}], "profile_state": "historical_confirmed",
                                   **compare(query, query_conditions, text,
                                             cached[1] if cached is not None else business_conditions(build_semantic_profile({"description": text})),
                                             candidate_terms=cached[0] if cached is not None else None)})
                    scanned += 1
                cursor = cases[-1].id
                if partial:
                    break
            if fusion is not None:
                vector_state = 'partial' if vector_missing or partial else 'ready'
                matched = len(fusion.scores)
                partial = partial or vector_missing > 0
            return {"schema_version": "case-history-5.1-1", "state": "partial" if partial else "ready",
                    "mode": "hybrid_local" if vector_sources else "lexical_fallback", "semantic_index_state": vector_state,
                    "source_case_id": source_case_id, "query_context": query_context,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "coverage": {"authorized_cases": total, "scanned_cases": scanned, "matched_sources": matched,
                                 "indexed_sources": indexed_sources, "fallback_sources": fallback_sources,
                                 "vector_sources": vector_sources, "vector_missing": vector_missing,
                                 "recency_limit": None, "complete": not partial, "budget_seconds": SCAN_SECONDS},
                    "items": fusion.finish(limit) if fusion is not None else [item for _, _, item in sorted(heap, key=lambda row: row[:2], reverse=True)],
                    "boundary": "历史相似条件仅供参考，须核对差异与适用性，不成为当前案件事实；词项支持度不是准确概率。"}
