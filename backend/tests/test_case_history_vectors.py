from sqlalchemy import select

from app.models.case_history_index import CaseHistoryEmbedding, CaseHistoryIndex
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_history_vector_service import exact_distances, store_embedding
from tests.test_case_history_index import db, make_case  # noqa: F401


def test_exact_vectors_require_current_sources_model_dimensions_and_scope(db):
    first, second = make_case(db), make_case(db, 'OTHER', area=2)
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    rows = list(db.scalars(select(CaseHistoryIndex).order_by(CaseHistoryIndex.case_id)))
    store_embedding(db, rows[0], [1., 0.], 'fixture-model')
    store_embedding(db, rows[1], [0., 1.], 'fixture-model')
    db.commit()
    sources = {(row.case_id, row.source_type, row.source_id): row.source_hash for row in rows}
    db.info['authorized_area_ids'] = (1, 2)
    result = exact_distances(db, sources=sources, vector=[1., 0.], model_version='fixture-model')
    assert result[(first.id, 'case', str(first.id))] == 0
    assert result[(second.id, 'case', str(second.id))] == 1
    db.info['authorized_area_ids'] = (1,)
    assert len(exact_distances(db, sources=sources, vector=[1., 0.], model_version='fixture-model')) == 1
    assert exact_distances(db, sources=sources, vector=[1., 0.], model_version='other-model') == {}
    assert exact_distances(db, sources=sources, vector=[1., 0., 0.], model_version='fixture-model') == {}
    sources[(first.id, 'case', str(first.id))] = 'changed-source'
    assert exact_distances(db, sources=sources, vector=[1., 0.], model_version='fixture-model') == {}
    db.info['authorized_area_ids'] = ()
    assert list(db.scalars(select(CaseHistoryEmbedding))) == []


def test_background_embedding_refresh_does_not_repeat_unchanged_inputs(db, monkeypatch):
    class Embedder:
        state, model_version = 'ready', 'fixture-local-model'
        calls = []
        def encode(self, text):
            self.calls.append(text)
            return [1., 0.]
    embedder = Embedder()
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: embedder)
    case = make_case(db)
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    assert len(embedder.calls) == 1
    assert len(list(db.scalars(select(CaseHistoryEmbedding)))) == 1
    case.description = '新的原文'
    db.commit()
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    assert len(embedder.calls) == 2
    db.delete(case)
    db.commit()
    assert not list(db.scalars(select(CaseHistoryEmbedding)))


def test_hybrid_retrieval_recalls_vector_only_match_and_marks_missing_vectors(db, monkeypatch):
    from app.services.case_history_retrieval import CaseHistoryRetrieval
    class Embedder:
        state, model_version = 'ready', 'test-vector-model'
        def encode(self, text):
            return [1., 0.]
    monkeypatch.setattr('app.services.case_history_retrieval.get_local_embedder', lambda: Embedder())
    case = make_case(db)
    case.description, case.location = '历史记录采用另一套完全不同的用词', '未知'
    db.commit()
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    index = db.scalar(select(CaseHistoryIndex))
    store_embedding(db, index, [1., 0.], 'test-vector-model')
    db.commit()
    db.info['authorized_area_ids'] = (1,)
    result = CaseHistoryRetrieval.search(db, query='ABC特殊查询XYZ')
    assert result['mode'] == 'hybrid_local'
    assert result['semantic_index_state'] == 'ready'
    assert result['items'][0]['case_id'] == case.id
    assert result['items'][0]['lexical_rank'] is None
    assert result['items'][0]['semantic_rank'] == 1
    assert result['coverage']['vector_sources'] == 1
    case.description = '向量尚未更新的新记录'
    db.commit()
    result = CaseHistoryRetrieval.search(db, query='ABC特殊查询XYZ')
    assert result['items'] == []
    assert result['semantic_index_state'] == result['state'] == 'partial'
    assert result['coverage']['vector_missing'] == 1
    assert result['coverage']['complete'] is False


def test_rank_fusion_keeps_negation_and_matches_full_reference_ranking():
    from app.services.history_rank_fusion import HistoryRankFusion
    collector = HistoryRankFusion()
    for number in range(250):
        collector.add({'score': (250-number)/250, 'source_id': number, 'versions': {},
                       'different_conditions': [], 'shared_conditions': []}, (number+250)/500)
    full = sorted(range(250), key=lambda number: (-(1/(60+number+1) + 1/(60+250-number)), number))[:20]
    assert [item['source_id'] for item in collector.finish(20)] == full
    negated = HistoryRankFusion()
    negated.add({'score': 0, 'versions': {}, 'different_conditions': [['action', '转运', 'negated']],
                 'shared_conditions': []}, 0.99)
    assert negated.finish(3) == []
