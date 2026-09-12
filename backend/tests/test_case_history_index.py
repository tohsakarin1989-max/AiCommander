"""可重建索引：当前授权、失效、后台断点和只读回退。"""
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.case import Case
from app.models.case_history_index import CaseHistoryIndex, CaseHistoryIndexCursor
from app.models.knowledge_asset import KnowledgeAsset
from app.models.map_foundation import OperationalArea
from app.models.case_pipeline import OutboxEvent
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_history_index_service import CaseHistoryIndexService, CURSOR_NAME
from app.services.case_history_retrieval import CaseHistoryRetrieval


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([OperationalArea(id=1, code="A", name="授权区"),
                         OperationalArea(id=2, code="B", name="其他区")])
        session.commit()
        yield session
    engine.dispose()


def make_case(db, number="H-1", area=1):
    case = Case(case_number=number, description="夜间打眼盗油使用胶管。", location="测试井场",
                occurred_time=datetime(2001, 1, 1), operational_area_id=area)
    db.add(case)
    db.commit()
    return case


def test_index_reused_without_candidate_reextraction_or_read_writes(db):
    case = make_case(db)
    assert CaseHistoryIndexService.reconcile_batch(db)["changed_sources"] == 1
    db.commit()
    assert CaseHistoryIndexService.reconcile_batch(db)["changed_sources"] == 0
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    from app.services.case_semantic_service import build_semantic_profile
    calls, writes = [], []
    def extract(values):
        calls.append(values)
        return build_semantic_profile(values)
    def capture(conn, cursor, sql, params, context, many):
        if sql.lstrip().split()[0].lower() in {"insert", "update", "delete"}:
            writes.append(sql)
    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        with patch("app.services.case_history_retrieval.build_semantic_profile", side_effect=extract):
            result = CaseHistoryRetrieval.search(db, query="打孔盗油软管")
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert calls == [{"description": "打孔盗油软管"}]
    assert not writes
    assert result["coverage"]["indexed_sources"] == 1
    assert result["coverage"]["fallback_sources"] == 0
    assert result["items"][0]["case_id"] == case.id
    assert result["semantic_index_state"] == "not_enabled"


def test_edit_rule_change_corrupt_payload_and_delete_invalidate_cache(db, monkeypatch):
    case = make_case(db)
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    case.description, case.location = "资料已修改", "未知"
    db.commit()
    result = CaseHistoryRetrieval.search(db, query="打孔盗油软管")
    assert result["items"] == [] and result["coverage"]["fallback_sources"] == 1
    case.description = "打眼盗油使用胶管"
    db.commit()
    db.info.pop("authorized_area_ids")
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    row = db.scalar(select(CaseHistoryIndex))
    row.payload = {"terms": ["软管"], "conditions": "invalid"}
    db.commit()
    assert CaseHistoryRetrieval.search(db, query="软管")["coverage"]["fallback_sources"] == 1
    monkeypatch.setattr("app.services.case_history_index_service.INDEX_VERSION", "future-rule")
    assert CaseHistoryRetrieval.search(db, query="软管")["coverage"]["fallback_sources"] == 1
    db.delete(case)
    db.commit()
    db.info.pop("authorized_area_ids")
    assert not list(db.scalars(select(CaseHistoryIndex)))


def test_revoked_scope_hides_index_even_when_session_identity_map_has_it(db):
    make_case(db)
    make_case(db, "HIDDEN", area=2)
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    assert len(list(db.scalars(select(CaseHistoryIndex)))) == 2
    db.info["authorized_area_ids"] = (1,)
    assert len(list(db.scalars(select(CaseHistoryIndex)))) == 1
    assert CaseHistoryRetrieval.search(db, query="胶管")["coverage"]["indexed_sources"] == 1
    db.info["authorized_area_ids"] = ()
    assert not list(db.scalars(select(CaseHistoryIndex)))
    assert CaseHistoryRetrieval.search(db, query="胶管")["items"] == []
    with pytest.raises(PermissionError):
        CaseHistoryIndexService.reconcile_batch(db)


def test_confirmed_experience_edit_and_evidence_revocation_rechecked(db):
    case = make_case(db)
    asset = KnowledgeAsset(asset_type="experience_card", source_case_id=case.id, version=1,
                           title="历史经验", content={"summary": "特殊储存条件经验"},
                           evidence_refs=[{"id": f"case:{case.id}"}], source_signature="a" * 64,
                           source_data_version="b" * 64, status="confirmed")
    db.add(asset)
    db.commit()
    assert CaseHistoryIndexService.reconcile_batch(db)["changed_sources"] == 2
    db.commit()
    db.info["authorized_area_ids"] = (1,)
    result = CaseHistoryRetrieval.search(db, query="特殊储存")
    assert result["items"][0]["source_type"] == "experience_card"
    assert result["coverage"]["indexed_sources"] == 2
    asset.content = {"summary": "资料已更新"}
    db.commit()
    assert CaseHistoryRetrieval.search(db, query="特殊储存")["items"] == []
    asset.content = {"summary": "特殊储存条件经验"}
    asset.evidence_refs = [{"id": "case:999999"}]
    db.commit()
    assert CaseHistoryRetrieval.search(db, query="特殊储存")["items"] == []
    db.info.pop("authorized_area_ids")
    asset.status = "rejected"
    db.commit()
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    assert len(list(db.scalars(select(CaseHistoryIndex)))) == 1


def test_persistent_cursor_rollback_resume_and_rotation(db):
    cases = [make_case(db, f"B-{i}") for i in range(5)]
    first = CaseHistoryIndexService.reconcile_batch(db, limit=2)
    db.commit()
    assert first["after_case_id"] == cases[1].id
    rebuild = CaseHistoryIndexService.rebuild_case
    def fail_second(session, case):
        if case.id == cases[3].id:
            raise RuntimeError("injected interruption")
        return rebuild(session, case)
    with patch.object(CaseHistoryIndexService, "rebuild_case", side_effect=fail_second):
        with pytest.raises(RuntimeError):
            CaseHistoryIndexService.reconcile_batch(db, limit=2)
    db.rollback()
    assert db.get(CaseHistoryIndexCursor, CURSOR_NAME).after_case_id == cases[1].id
    assert len(list(db.scalars(select(CaseHistoryIndex)))) == 2
    second = CaseHistoryIndexService.reconcile_batch(db, limit=2)
    db.commit()
    assert second["after_case_id"] == cases[3].id
    final = CaseHistoryIndexService.reconcile_batch(db, limit=2)
    db.commit()
    assert final["after_case_id"] == 0 and final["completed_passes"] == 1
    assert len(list(db.scalars(select(CaseHistoryIndex)))) == 5
    cases[0].description = "新的转运条件"
    db.commit()
    assert CaseHistoryIndexService.reconcile_batch(db, limit=2)["changed_sources"] == 1


def test_saved_event_prioritizes_old_case_and_ack_is_transactional(db):
    old = make_case(db, 'EARLY')
    make_case(db, 'NEXT')
    make_case(db, 'LAST')
    CaseHistoryIndexService.reconcile_batch(db, limit=1)
    db.commit()
    # The old case is behind the background cursor, but its committed event wins.
    background_events = db.query(OutboxEvent).count()
    old.description = '新增的囤储线索'
    event = CasePipelineService.enqueue_case_change(db, old, changed_fields={'description'})
    db.commit()
    assert event.payload['history_index_pending'] is True
    # Only the original profile event is added synchronously by save. History
    # refresh notifications above were produced by the background index pass.
    assert db.query(OutboxEvent).count() == background_events + 1
    result = CaseHistoryIndexService.reconcile_batch(db, limit=1)
    assert result['priority_cases'] == 1 and result['acknowledged_events'] == 1
    assert result['after_case_id'] == 2
    db.rollback()
    db.refresh(event)
    assert event.payload['history_index_pending'] is True
    result = CaseHistoryIndexService.reconcile_batch(db, limit=1)
    db.commit()
    assert result['priority_cases'] == 1
    assert event.payload['history_index_pending'] is False
    assert event.status == 'pending'  # Index consumer does not complete the profile job.
    db.info['authorized_area_ids'] = (1,)
    history = CaseHistoryRetrieval.search(db, query='囤储')
    assert old.id in {item['case_id'] for item in history['items']}
    assert history['coverage']['indexed_sources'] == 2


def test_deleted_case_event_acknowledged_without_recreating_case(db):
    case = make_case(db)
    event = CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    db.delete(case)
    db.commit()
    result = CaseHistoryIndexService.reconcile_batch(db, limit=1)
    db.commit()
    assert result['priority_cases'] == 0 and result['acknowledged_events'] == 1
    assert not list(db.scalars(select(CaseHistoryIndex)))
    assert event.payload['history_index_pending'] is False


def test_incremental_migration_roundtrip_preserves_business_records():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/c61d20a75e91_case_history_lexical_index.py"
    spec = spec_from_file_location("history_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE cases (id INTEGER PRIMARY KEY, description TEXT)")
        conn.exec_driver_sql("INSERT INTO cases VALUES (1, '原始记录')")
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            assert "case_history_indexes" in inspect(conn).get_table_names()
            module.downgrade()
        assert conn.exec_driver_sql("SELECT description FROM cases").scalar() == "原始记录"
        assert "case_history_indexes" not in inspect(conn).get_table_names()
    engine.dispose()
