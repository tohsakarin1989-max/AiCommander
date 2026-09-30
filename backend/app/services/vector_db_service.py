"""旧向量接口兼容层：只读统一历史索引，不再创建或读取 Chroma。"""
import math

from sqlalchemy import select

from app.models.case import Case
from app.services.case_history_retrieval import source_values
from app.services.local_embedding_service import get_local_embedder


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
        from app.services.case_history_fragment_search import search_fragments
        result = search_fragments(db, query=query_text, source_case_id=exclude, limit=top_k,
            source_types={'case'}, candidate_area_ids=areas, semantic_only=True,
            min_similarity=min_similarity, embedding_model=get_local_embedder())
        coverage = result['coverage']
        missing = coverage['vector_missing'] + coverage['missing_index_cases']
        self.status = {'state': result['semantic_index_state'] if result['semantic_index_state'] == 'unavailable'
                       else 'ready' if coverage['complete'] else 'partial',
                       'complete': coverage['complete'], 'authorized_cases': coverage['authorized_cases'],
                       'scanned_cases': coverage['scanned_cases'], 'missing_vectors': missing,
                       'model_version': result['query_context']['embedding_model_version'],
                       'recency_limit': None, 'retrieval_mode': 'fragment_index', 'coverage': coverage}
        return [{'case_id': item['case_id'], 'similarity': item['semantic_similarity'],
                 'distance': item['semantic_distance'], 'score_kind': 'cosine_similarity_not_probability',
                 'shared_conditions': item['shared_conditions'], 'different_conditions': item['different_conditions'],
                 'metadata': {'case_id': item['case_id'], 'operational_area_id': item['operational_area_id']},
                 'versions': {'source_hash': item['versions']['source_text_hash'],
                              'model_version': item['versions']['embedding_model_version']},
                 'fragment': item['fragment'], 'evidence_refs': item['evidence_refs']}
                for item in result['items'] if item['semantic_similarity'] is not None]
