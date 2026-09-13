"""旧向量接口兼容层：只读统一历史索引，不再创建或读取 Chroma。"""
import heapq
import math
import time

from sqlalchemy import func, select

from app.models.case import Case
from app.models.case_history_index import CaseHistoryIndex
from app.services.case_history_index_service import cached_features
from app.services.case_history_retrieval import source_values, business_conditions, compare
from app.services.case_history_vector_service import exact_distances
from app.services.case_semantic_evidence import freeze_sources, snapshot_payload
from app.services.case_semantic_service import TEXT_FIELDS, build_semantic_profile
from app.services.local_embedding_service import LocalEmbeddingError, get_local_embedder


class VectorDBService:
    """保持旧方法名及分数含义；状态独立返回，不把失败转成无匹配。"""

    def __init__(self):
        self.status = {'state': 'not_enabled', 'complete': False}

    def is_available(self, db=None) -> bool:
        if db is None or 'authorized_area_ids' not in db.info:
            self.status = {'state': 'scope_required', 'complete': False}
            return False
        model = get_local_embedder()
        self.status = {'state': model.state, 'complete': False, 'model_version': model.model_version}
        return model.state == 'ready'

    def add_case(self, case_id, case_data, embedding=None) -> bool:
        # Save Outbox/background rebuild is the only ingestion path. Never trust
        # caller-supplied text or vectors as a persisted business source.
        self.status = {'state': 'background_index_required', 'complete': False}
        return False

    def update_case(self, case_id, case_data) -> bool:
        return self.add_case(case_id, case_data)

    def delete_case(self, case_id) -> bool:
        # Derived rows follow the business case's transactional FK cascade.
        self.status = {'state': 'business_delete_required', 'complete': False}
        return False

    def search_similar_cases(self, query_text, top_k=10, min_similarity=0.5,
                             operational_area_ids=None, *, db=None):
        if not isinstance(query_text, str) or not query_text.strip() or len(query_text) > 2000:
            raise ValueError('invalid_vector_query')
        return self._search(db, query_text, top_k, min_similarity, operational_area_ids)

    def find_semantic_serial_cases(self, case_id, top_k=10, min_similarity=0.6,
                                   operational_area_ids=None, *, db=None):
        self._require_scope(db)
        if type(case_id) is not int or case_id <= 0:
            raise ValueError('invalid_vector_case_id')
        with db.no_autoflush:
            case = db.scalar(select(Case).where(Case.id == case_id).execution_options(populate_existing=True))
            if case is None:
                raise PermissionError('vector_source_unavailable')
            if operational_area_ids is not None and case.operational_area_id not in operational_area_ids:
                raise PermissionError('vector_source_unavailable')
            text = '。'.join(value for value in source_values(case).values() if value)
            return self._search(db, text, top_k, min_similarity, operational_area_ids, exclude=case_id)

    @staticmethod
    def _require_scope(db):
        if db is None or 'authorized_area_ids' not in db.info:
            raise PermissionError('vector_scope_required')

    def _search(self, db, query_text, top_k, min_similarity, areas, exclude=None):
        self._require_scope(db)
        if (type(top_k) is not int or not 1 <= top_k <= 100
                or type(min_similarity) not in (int, float)
                or not math.isfinite(min_similarity) or not 0 <= min_similarity <= 1):
            raise ValueError('invalid_vector_parameters')
        if areas is not None and (not isinstance(areas, (list, tuple))
                or any(type(area) is not int or area <= 0 for area in areas)):
            raise ValueError('invalid_vector_scope')
        if not self.is_available(db):
            return []
        model = get_local_embedder()
        started = time.monotonic()
        try:
            vector = model.encode(query_text)
        except LocalEmbeddingError:
            self.status = {'state': 'unavailable', 'complete': False, 'model_version': model.model_version}
            return []
        conditions = business_conditions(build_semantic_profile({'description': query_text}))
        with db.no_autoflush:
            query = db.query(Case)
            if areas is not None:
                query = query.filter(Case.operational_area_id.in_(areas))
            if exclude is not None:
                query = query.filter(Case.id != exclude)
            upper = query.with_entities(func.max(Case.id)).scalar()
            total = query.filter(Case.id <= upper).count() if upper is not None else 0
            cursor, scanned, missing = 0, 0, 0
            heap = []
            while upper is not None and cursor < upper:
                if time.monotonic() - started > 5:
                    break
                cases = (query.filter(Case.id > cursor, Case.id <= upper).order_by(Case.id).limit(100)
                         .execution_options(populate_existing=True).all())
                if not cases:
                    break
                sources = {(case.id, 'case', str(case.id)): snapshot_payload(freeze_sources(source_values(case)))['sha256']
                           for case in cases}
                distances = exact_distances(db, sources=sources, vector=vector, model_version=model.model_version)
                indexes = {row.case_id: row for row in db.scalars(select(CaseHistoryIndex).where(
                    CaseHistoryIndex.case_id.in_([case.id for case in cases]), CaseHistoryIndex.source_type == 'case')
                    .execution_options(populate_existing=True))}
                for case in cases:
                    key = (case.id, 'case', str(case.id))
                    distance = distances.get(key)
                    scanned += 1
                    if distance is None:
                        missing += 1
                        continue
                    similarity = max(-1., min(1., 1 - distance))
                    if similarity < min_similarity:
                        continue
                    cached = cached_features(indexes.get(case.id), sources[key])
                    candidate_conditions = cached[1] if cached else business_conditions(build_semantic_profile(
                        {field: getattr(case, field) for field in TEXT_FIELDS}))
                    comparison = compare(query_text, conditions, '', candidate_conditions)
                    if comparison['different_conditions'] and not comparison['shared_conditions']:
                        continue
                    item = {'case_id': case.id, 'similarity': round(similarity, 6), 'distance': distance,
                            'score_kind': 'cosine_similarity_not_probability',
                            'shared_conditions': comparison['shared_conditions'],
                            'different_conditions': comparison['different_conditions'],
                            'metadata': {'case_id': case.id, 'operational_area_id': case.operational_area_id},
                            'versions': {'source_hash': sources[key], 'model_version': model.model_version}}
                    entry = (similarity, -case.id, item)
                    if len(heap) < top_k:
                        heapq.heappush(heap, entry)
                    elif entry[:2] > heap[0][:2]:
                        heapq.heapreplace(heap, entry)
                cursor = cases[-1].id
            complete = scanned == total and missing == 0
            self.status = {'state': 'ready' if complete else 'partial', 'complete': complete,
                           'authorized_cases': total, 'scanned_cases': scanned, 'missing_vectors': missing,
                           'model_version': model.model_version, 'recency_limit': None}
            return [item for _, _, item in sorted(heap, key=lambda row: row[:2], reverse=True)]
