"""统一授权片段检索入口；结构、词项与语义分别召回，缺失明确降级。"""
import re
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_semantic_service import TEXT_FIELDS, build_semantic_profile
from app.services.local_embedding_service import get_local_embedder


RETRIEVAL_VERSION = "case-history-6.3-fragments-1"
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
    if "authorized_area_ids" not in db.info:
        return False
    if db.scalar(select(Case.id).where(Case.id == asset.source_case_id)) is None:
        return False
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
    def case_references(db: Session, *, source_case_id: int, filters: dict | None = None) -> dict:
        """One read-only daily view: at most two similar cases and one contrast."""
        from app.services.case_history_fragment_search import validate_fragment_item

        deadline, embedder, vectors = time.monotonic() + SCAN_SECONDS, get_local_embedder(), {}
        observed = {'similar': {}, 'contrast': {}}
        outputs = {}
        for purpose in ('similar', 'contrast'):
            outputs[purpose] = CaseHistoryRetrieval._search(db, source_case_id=source_case_id,
                filters=filters, limit=3, purpose=purpose, deadline=deadline, embedding_model=embedder,
                observations=observed[purpose], query_vector_cache=vectors)
        similar, contrast = outputs['similar'], outputs['contrast']
        binding_keys = ('source_text_hash', 'source_revision_id', 'scope_hash', 'filters', 'query_sha256')
        if any(similar['query_context'].get(key) != contrast['query_context'].get(key) for key in binding_keys):
            raise HistoryUnavailable('history_reference_source_changed')
        # Reserve the independent contrast slot; a case cannot appear twice via
        # its original record and a confirmed experience card.
        contrasting = contrast['items'][:1]
        seen = {row['case_id'] for row in contrasting}
        matching = []
        for row in similar['items']:
            if row['case_id'] not in seen and len(matching) < 2:
                matching.append(row)
                seen.add(row['case_id'])
        items = matching + contrasting
        for item in items:
            validate_fragment_item(db, item, source_case_id=source_case_id)
        coverage = dict(similar['coverage'])
        for key, observation in (('scanned_cases', 'checked_cases'), ('recalled_fragments', 'recalled_fragments'),
                                 ('validated_fragments', 'validated_fragments'), ('matched_sources', 'matched_sources')):
            coverage[key] = len(set().union(*(row.get(observation, set()) for row in observed.values())))
        coverage['branch_counts'] = {branch: len(set().union(*(
            row.get('branches', {}).get(branch, set()) for row in observed.values())))
            for branch in ('structural', 'lexical', 'semantic')}
        coverage['complete'] = all(row['coverage']['complete'] for row in outputs.values())
        coverage['scan_complete'] = all(row['coverage']['scan_complete'] for row in outputs.values())
        coverage['recall_truncated'] = any(row['coverage']['recall_truncated'] for row in outputs.values())
        coverage['recall_purposes'] = {key: row['coverage'] for key, row in outputs.items()}
        partial = any(row['state'] == 'partial' for row in outputs.values())
        return {**similar, 'purpose': 'mixed', 'items': items, 'coverage': coverage,
            'state': 'partial' if partial else 'ready', 'degraded': any(row['degraded'] for row in outputs.values()),
            'query_context': {**similar['query_context'], 'purpose': 'mixed'},
            'reference_mix': {'similar': len(matching), 'contrast': len(contrasting), 'limit': 3,
                              'deduplicated_by': 'case_id', 'version': 'case-references-8.1-1'},
            'boundary': '最多两项相似参考与一项独立差异对照，按案件去重，不够不凑；' + similar['boundary']}

    @staticmethod
    def search(db: Session, *, query: str = "", source_case_id: int | None = None,
               filters: dict | None = None, limit: int = 3, reuse_only: bool = False,
               query_conditions: set[tuple[str, str, str]] | None = None,
               deadline: float | None = None, exclude_case_sources: set[int] | None = None,
               cancelled=lambda: False, purpose: str = "similar") -> dict:
        if not 1 <= limit <= 20 or purpose not in {"similar", "contrast"}:
            raise ValueError("invalid_history_query")
        return CaseHistoryRetrieval._search(
            db, query=query, source_case_id=source_case_id, filters=filters, limit=limit,
            reuse_only=reuse_only, query_conditions=query_conditions, deadline=deadline,
            exclude_case_sources=exclude_case_sources, cancelled=cancelled, purpose=purpose,
        )

    @staticmethod
    def search_cases(db: Session, *, source_case_id: int, filters: dict | None = None,
                     limit: int = 200) -> dict:
        """Internal compatibility recall, not the public twenty-result query API."""
        if not 1 <= limit <= 200:
            raise ValueError("invalid_history_query")
        return CaseHistoryRetrieval._search(db, source_case_id=source_case_id, filters=filters,
                                            limit=limit, source_types={"case"})

    @staticmethod
    def search_experiences(db: Session, *, query: str, limit: int = 20,
                           status: str = "confirmed") -> dict:
        if not 1 <= limit <= 20 or status not in {"confirmed", "draft", "archived"}:
            raise ValueError("invalid_history_query")
        return CaseHistoryRetrieval._search(
            db, query=query, limit=limit, source_types={"experience_card", "legacy_experience_card"},
            experience_status=status,
        )

    @staticmethod
    def _search(db, **kwargs):
        from app.services.case_history_fragment_search import search_fragments
        return search_fragments(db, **kwargs)
