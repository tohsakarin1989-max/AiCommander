import pytest

from app.agent_runtime.providers import build_narrator
from app.ai.model_factory import ModelFactory
from app.config import settings
from app.models.ai_model import AIModel
from app.services.vector_db_service import VectorDBService


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


def test_vector_search_filters_by_area_and_never_returns_raw_document():
    captured = {}

    class FakeEmbeddingService:
        @staticmethod
        def generate_embedding(_text):
            return [0.1, 0.2]

    class FakeCollection:
        @staticmethod
        def query(**kwargs):
            captured.update(kwargs)
            return {
                "ids": [["12"]],
                "distances": [[0.1]],
                "metadatas": [[{"case_id": 12, "operational_area_id": 7}]],
                "documents": [["不得离开向量库的案件原文"]],
            }

    service = VectorDBService.__new__(VectorDBService)
    service.client = object()
    service.collection = FakeCollection()
    service.embedding_service = FakeEmbeddingService()

    results = service.search_similar_cases(
        "脱敏查询",
        operational_area_ids=[7],
    )

    assert captured["where"] == {"operational_area_id": 7}
    assert "document" not in results[0]
