import pytest

from app.agent_runtime.providers import build_narrator
from app.ai.model_factory import ModelFactory
from app.config import settings
from app.models.ai_model import AIModel
from app.services.vector_db_service import VectorDBService
from tests.test_case_history_index import db, make_case  # noqa: F401


def _model(*, provider: str = "openai", api_base: str | None = None) -> AIModel:
    return AIModel(
        name="egress-test",
        provider=provider,
        model_name="fixture-model",
        api_key="not-decrypted-in-test",
        role="analyst",
        config={"api_base": api_base} if api_base else {},
    )


def test_raw_case_data_is_blocked_for_external_model_before_client_creation():
    with pytest.raises(ValueError, match="原始案件"):
        ModelFactory().create_llm(_model(), data_classification="raw")


def test_redacted_external_model_requires_explicit_policy(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_DATA_EGRESS_POLICY", "local_only")
    with pytest.raises(ValueError, match="禁止调用外部模型"):
        ModelFactory().create_llm(_model(), data_classification="redacted")


def test_trusted_local_model_endpoint_can_process_internal_data(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        "app.ai.model_factory.LLMProvider.create_openai_like_llm",
        lambda _model: sentinel,
    )

    result = ModelFactory().create_llm(
        _model(api_base="http://127.0.0.1:11434/v1"),
        data_classification="raw",
    )

    assert result is sentinel


def test_openai_agents_adapter_respects_global_local_only_policy(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_USE_EXTERNAL_MODEL", True)
    monkeypatch.setattr(settings, "AGENT_EXTERNAL_DATA_POLICY", "redacted_only")
    monkeypatch.setattr(settings, "AGENT_PROVIDER", "openai_agents")
    monkeypatch.setattr(settings, "MODEL_DATA_EGRESS_POLICY", "local_only")

    assert build_narrator() is None


def test_vector_search_filters_by_area_and_never_returns_raw_document(db, monkeypatch):
    from sqlalchemy import select
    from app.models.case_history_index import CaseHistoryIndex
    from app.services.case_history_index_service import CaseHistoryIndexService
    from app.services.case_history_vector_service import store_embedding
    from types import SimpleNamespace
    first = make_case(db)
    second = make_case(db, 'OUTSIDE', area=2)
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    for row in db.scalars(select(CaseHistoryIndex)):
        store_embedding(db, row, [1., 0.], 'scope-fixture')
    db.commit()
    monkeypatch.setattr('app.services.vector_db_service.get_local_embedder', lambda: SimpleNamespace(
        state='ready', model_version='scope-fixture', encode=lambda _: [1., 0.]))
    db.info['authorized_area_ids'] = (1,)
    service = VectorDBService()
    results = service.search_similar_cases('查询', operational_area_ids=[1, 2], db=db)
    assert [item['case_id'] for item in results] == [first.id]
    assert second.id not in [item['case_id'] for item in results]
    assert 'document' not in results[0] and first.description not in str(results)
    assert service.status['complete'] is True
    db.info['authorized_area_ids'] = ()
    assert service.search_similar_cases('查询', db=db) == []
    with pytest.raises(PermissionError):
        service.search_similar_cases('查询')
