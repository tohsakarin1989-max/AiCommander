from datetime import datetime
import json
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import knowledge
from app.database import Base, get_db
from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.models.map_foundation import OperationalArea
from app.services.case_history_retrieval import CaseHistoryRetrieval, HistoryUnavailable
from app.services.case_knowledge_service import CaseKnowledgeService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        db.add(OperationalArea(id=1, code="RETRIEVAL-DEFAULT", name="测试区域"))
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def corpus(db_session, monkeypatch):
    # 当前工作包验证完整遍历，不让机器快慢决定单元测试覆盖范围。
    monkeypatch.setattr("app.services.case_history_retrieval.SCAN_SECONDS", 60)
    db_session.info["authorized_area_ids"] = (1,)
    db_session.add(OperationalArea(id=2, code="RETRIEVAL-OTHER", name="其他测试区域"))
    db_session.commit()
    old = Case(case_number="OLD-MATCH", occurred_time=datetime(2000, 1, 1),
               location="测试井场", description="夜间打眼盗油并使用胶管。", operational_area_id=1)
    db_session.add(old)
    db_session.add_all([Case(case_number=f"RECENT-{i}", occurred_time=datetime(2026, 9, 1),
                             location="测试地点", description="测试无对应条件", operational_area_id=1)
                       for i in range(620)])
    db_session.add(Case(case_number="HIDDEN", occurred_time=datetime(2026, 9, 1),
                        location="秘密测试区域", description="夜间打孔盗油使用软管。", operational_area_id=2))
    db_session.commit()
    return old


def test_old_cases_are_recalled_across_all_authorized_history_without_writes(db_session, corpus):
    statements = []
    def capture(conn, cursor, sql, parameters, context, many):
        statements.append(sql.lstrip().split()[0].lower())
    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        result = CaseHistoryRetrieval.search(db_session, query="打孔盗油 软管", limit=1)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert result["items"][0]["case_number"] == "OLD-MATCH"
    assert result["items"][0]["shared_conditions"]
    assert result["coverage"]["authorized_cases"] == 621
    assert result["coverage"]["scanned_cases"] == 621
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["recency_limit"] is None
    assert not {"insert", "update", "delete"}.intersection(statements)
    assert "HIDDEN" not in json.dumps(result)
    assert result["semantic_index_state"] == "not_enabled"
    with pytest.raises(HistoryUnavailable):
        CaseHistoryRetrieval.search(db_session, query="软管", filters={"operational_area_id": 2})


def test_legacy_search_and_citations_share_all_history_and_keep_case_filter(db_session, corpus):
    writes = []
    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().split()[0].lower() in {'insert', 'update', 'delete'}:
            writes.append(sql)
    event.listen(db_session.bind, 'before_cursor_execute', capture)
    try:
        result = CaseKnowledgeService.search(db_session, '打孔盗油 软管', limit=3)
    finally:
        event.remove(db_session.bind, 'before_cursor_execute', capture)
    assert not writes
    assert result['items'][0]['source_type'] == 'case_profile'
    assert result['items'][0]['source_id'] == corpus.id
    assert result['history']['coverage']['scanned_cases'] == 621
    assert result['history']['coverage']['recency_limit'] is None
    assert 'HIDDEN' not in json.dumps(result)
    assert CaseKnowledgeService.citation_assist(db_session, '打孔盗油软管')['citations'][0]['route'] == f'/cases?caseId={corpus.id}'
    other = db_session.query(Case).filter(Case.case_number == 'RECENT-0').one()
    filtered = CaseKnowledgeService.search(db_session, '打孔盗油软管', case_id=other.id)
    assert not filtered['items']
    assert filtered['history']['coverage']['authorized_cases'] == 1


def test_legacy_partial_empty_result_is_not_a_completed_no_match(db_session, corpus, monkeypatch):
    monkeypatch.setattr('app.services.case_history_retrieval.SCAN_SECONDS', -1)
    result = CaseKnowledgeService.evidence_qa(db_session, '打孔盗油软管')
    assert result['state'] == 'partial'
    assert result['history']['coverage']['complete'] is False
    assert '不能判断没有' in result['answer']
    assert not result['citations']


def test_legacy_metadata_search_is_current_and_does_not_create_assertions(db_session, corpus):
    corpus.report_unit = '专用测试单位甲'
    db_session.commit()
    result = CaseKnowledgeService.search(db_session, '专用测试单位甲', case_id=corpus.id)
    assert result['items'][0]['case_id'] == corpus.id
    assert not result['items'][0]['shared_conditions']
    assert any(ref.get('reference', {}).get('field') == 'report_unit' for ref in result['items'][0]['evidence_refs'])
    version = result['items'][0]['versions']['source_text_hash']
    corpus.report_unit = '单位已变更'
    db_session.commit()
    updated = CaseHistoryRetrieval.search(db_session, query=corpus.case_number, filters={'case_id': corpus.id})
    assert updated['items'][0]['versions']['source_text_hash'] != version


def test_case_modified_deleted_and_revoked_do_not_leave_old_matches(db_session, corpus):
    corpus.description, corpus.location = "资料已修改", "未知"
    db_session.commit()
    assert CaseHistoryRetrieval.search(db_session, query="打孔盗油软管")["items"] == []
    corpus.description = "打眼盗油胶管"
    db_session.commit()
    db_session.info["authorized_area_ids"] = ()
    assert CaseHistoryRetrieval.search(db_session, query="打孔盗油软管")["items"] == []
    with pytest.raises(HistoryUnavailable):
        CaseHistoryRetrieval.search(db_session, source_case_id=corpus.id)
    db_session.info["authorized_area_ids"] = (1,)
    db_session.delete(corpus)
    db_session.commit()
    assert CaseHistoryRetrieval.search(db_session, query="打孔盗油软管")["items"] == []


def test_negated_action_is_not_a_positive_match(db_session):
    db_session.info["authorized_area_ids"] = (1,)
    db_session.add(Case(case_number="NEGATED", occurred_time=datetime(2020, 1, 1),
                        location="未知", description="未转运。", operational_area_id=1))
    db_session.commit()
    assert CaseHistoryRetrieval.search(db_session, query="转运")["items"] == []
    result = CaseHistoryRetrieval.search(db_session, query="未转运")
    assert result["items"][0]["shared_conditions"] == [["action", "转运", "negated"]]


def test_only_confirmed_experience_with_accessible_evidence_is_returned(db_session, corpus):
    asset = KnowledgeAsset(asset_type="experience_card", source_case_id=corpus.id, version=1,
                           title="历史经验", content={"summary": "特殊储存条件经验"}, evidence_refs=[{"id": f"case:{corpus.id}"}],
                           source_signature="a" * 64, source_data_version="b" * 64, status="draft")
    db_session.add(asset)
    db_session.commit()
    assert not CaseHistoryRetrieval.search(db_session, query="特殊储存")["items"]
    asset.status = "confirmed"
    db_session.commit()
    result = CaseHistoryRetrieval.search(db_session, query="特殊储存")
    assert result["items"][0]["source_type"] == "experience_card"
    asset.evidence_refs = [{"id": "case:999999"}]
    db_session.commit()
    assert not CaseHistoryRetrieval.search(db_session, query="特殊储存")["items"]


def test_budget_stop_is_partial_not_no_matching_history(db_session, corpus, monkeypatch):
    monkeypatch.setattr("app.services.case_history_retrieval.SCAN_SECONDS", -1)
    result = CaseHistoryRetrieval.search(db_session, query="打孔盗油")
    assert result["state"] == "partial" and result["coverage"]["complete"] is False
    assert result["coverage"]["scanned_cases"] == 0


def test_history_api_auth_success_and_invalid_context(db_session, corpus):
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")
    app.dependency_overrides[get_db] = lambda: db_session
    @app.middleware("http")
    async def identity(request: Request, next_call):
        if request.headers.get("x-test-reader"):
            request.state.principal = SimpleNamespace(role="viewer")
        return await next_call(request)
    with TestClient(app) as client:
        assert client.get("/api/knowledge/history?q=软管").status_code == 401
        headers = {"x-test-reader": "1"}
        response = client.get("/api/knowledge/history?q=软管", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["items"][0]["case_number"] == "OLD-MATCH"
        assert client.get("/api/knowledge/history?source_case_id=999999", headers=headers).status_code == 404
        assert client.get("/api/knowledge/history", headers=headers).status_code == 422
        legacy = client.get('/api/knowledge/search?q=软管', headers=headers)
        assert legacy.status_code == 200
        assert legacy.headers['cache-control'] == 'no-store'
        assert legacy.json()['items'][0]['case_number'] == 'OLD-MATCH'
        assert client.get('/api/knowledge/search?q=软管&limit=21', headers=headers).status_code == 422
        assert client.get('/api/knowledge/search?q=%20', headers=headers).status_code == 422
        db_session.info.pop('authorized_area_ids')
        assert client.get('/api/knowledge/search?q=软管', headers=headers).status_code == 404


def test_history_api_database_failure_is_not_an_empty_success(db_session, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    def failure(*args, **kwargs):
        raise SQLAlchemyError("private database details")
    monkeypatch.setattr(CaseHistoryRetrieval, "search", failure)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/knowledge")
    app.dependency_overrides[get_db] = lambda: db_session
    @app.middleware("http")
    async def identity(request, next_call):
        request.state.principal = SimpleNamespace(role="viewer")
        return await next_call(request)
    with TestClient(app) as client:
        response = client.get("/api/knowledge/history?q=软管")
        assert response.status_code == 503
        assert "不能据此判断没有匹配资料" in response.text
        assert "private" not in response.text
        legacy = client.get('/api/knowledge/search?q=软管')
        assert legacy.status_code == 503
        assert 'private' not in legacy.text
