"""授权集合内精确余弦计算；不建近似 ANN 索引，不查询旧 Chroma 内容。"""
from datetime import datetime, timezone
import math
import re

from sqlalchemy import select

from app.models.case_history_index import CaseHistoryEmbedding, CaseHistoryIndex
from app.services.local_embedding_service import normalized_vector


def store_embedding(db, source: CaseHistoryIndex, values, model_version: str):
    if not isinstance(model_version, str) or not re.fullmatch(r'[a-zA-Z0-9:._-]{1,100}', model_version):
        raise ValueError('invalid_embedding_version')
    vector = normalized_vector(values, len(values))
    if not 1 <= len(vector) <= 4096:
        raise ValueError('invalid_embedding_dimension')
    # Source row is the sole parent; write never creates cases or trust from supplied text.
    db.flush()
    row = db.scalar(select(CaseHistoryEmbedding).where(
        CaseHistoryEmbedding.case_id == source.case_id, CaseHistoryEmbedding.source_type == source.source_type,
        CaseHistoryEmbedding.source_id == source.source_id, CaseHistoryEmbedding.model_version == model_version)
        .execution_options(populate_existing=True))
    if row is None:
        row = CaseHistoryEmbedding(case_id=source.case_id, source_type=source.source_type,
                                   source_id=source.source_id, model_version=model_version)
        db.add(row)
    row.source_hash, row.dimension, row.embedding = source.source_hash, len(vector), vector
    row.updated_at = datetime.now(timezone.utc)


def exact_distances(db, *, sources: dict, vector: list, model_version: str) -> dict:
    """sources 来自当前业务源核对，键为(case_id, source_type, source_id)，值为源 hash。"""
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('history_vector_scope_required')
    query_vector = normalized_vector(vector, len(vector))
    if not sources:
        return {}
    if len(sources) > 1000:
        raise ValueError('history_vector_batch_limit')
    filters = (CaseHistoryEmbedding.case_id.in_({key[0] for key in sources}),
               CaseHistoryEmbedding.model_version == model_version,
               CaseHistoryEmbedding.dimension == len(query_vector))
    result = {}
    with db.no_autoflush:
        if db.get_bind().dialect.name == 'postgresql':
            # No LIMIT before current-source and permission checks; no approximate index.
            distance = CaseHistoryEmbedding.embedding.cosine_distance(query_vector).label('distance')
            rows = db.execute(select(CaseHistoryEmbedding.case_id, CaseHistoryEmbedding.source_type,
                CaseHistoryEmbedding.source_id, CaseHistoryEmbedding.source_hash, distance).where(*filters))
            for case_id, source_type, source_id, source_hash, score in rows:
                key = (case_id, source_type, source_id)
                if sources.get(key) == source_hash and score is not None and math.isfinite(score):
                    result[key] = float(score)
        elif db.get_bind().dialect.name == 'sqlite':
            for row in db.scalars(select(CaseHistoryEmbedding).where(*filters).execution_options(populate_existing=True)):
                key = (row.case_id, row.source_type, row.source_id)
                if sources.get(key) != row.source_hash:
                    continue
                candidate = normalized_vector(row.embedding, row.dimension)
                result[key] = max(0.0, min(2.0, 1 - sum(a * b for a, b in zip(query_vector, candidate))))
        else:
            raise ValueError('history_vector_database_unsupported')
    return result
