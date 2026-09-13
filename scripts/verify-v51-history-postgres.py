"""只创建一次性本地数据库，核验历史索引迁移、并发续建及备份恢复。"""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
import time
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    image = "aicommander-postgis-vector:16-0.8.6"
    password = secrets.token_hex(24)
    identity = "aic-history-check-" + uuid.uuid4().hex[:12]
    container = None
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}

    def docker(*args, **kwargs):
        return subprocess.run(["docker", *args], check=True, **kwargs)

    try:
        container = docker("run", "-d", "--pull=never",
                           "--name", identity, "--label", "aicommander.disposable=history-verification",
                           "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432",
                           "-e", "POSTGRES_USER=aic_history_test", "-e", "POSTGRES_DB=aic_history_test",
                           "-e", "POSTGRES_PASSWORD", image, capture_output=True, text=True,
                           env={**env, "POSTGRES_PASSWORD": password}).stdout.strip()
        for _ in range(45):
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-h", "127.0.0.1",
                                    "-U", "aic_history_test"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("disposable_database_not_ready")
        port = int(docker("port", container, "5432", capture_output=True, text=True).stdout.strip().rsplit(":", 1)[1])
        url = f"postgresql://aic_history_test:{password}@127.0.0.1:{port}/aic_history_test"
        test_env = {**env, "DATABASE_URL": url, "SECRET_KEY": secrets.token_hex(32), "ENVIRONMENT": "development"}
        # Import app only after excluding the developer's live database/model settings.
        os.environ.clear()
        os.environ.update(test_env)
        sys.path.insert(0, str(root / "backend"))
        from sqlalchemy import create_engine, select, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import sessionmaker
        from app.models.case import Case
        from app.models.case_history_index import CaseHistoryIndex, CaseHistoryEmbedding
        from app.models.map_foundation import OperationalArea
        from app.services.case_history_index_service import CaseHistoryIndexService
        from app.services.case_history_retrieval import CaseHistoryRetrieval
        from app.services.case_history_vector_service import exact_distances, store_embedding
        from app.services.case_pipeline_service import CasePipelineService
        from app.services.vector_db_service import VectorDBService

        def migrate(target):
            # Do not print connection URLs or inherited environment.
            result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", target],
                                    cwd=root / "backend", env=test_env, capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError("isolated_migration_failed: " + result.stderr.replace(password, "[redacted]")[-3000:])

        migrate("b508c42fd75b")
        engine = create_engine(url)
        sessions = sessionmaker(bind=engine, autoflush=False)
        with sessions() as db:
            assert db.query(Case).count() == 0, "refuse_populated_test_database"
            area = db.scalar(select(OperationalArea).order_by(OperationalArea.id))
            assert area is not None
            area_id = area.id
            db.add_all([Case(case_number=f"SYNTHETIC-HISTORY-{i}", operational_area_id=area_id,
                             occurred_time=datetime(2000, 1, 1), location="合成井场",
                             description="夜间打眼盗油使用胶管。") for i in range(4)])
            db.commit()
        previous_dump = docker("exec", container, "pg_dump", "-U", "aic_history_test", "-Fc", "aic_history_test",
                               capture_output=True).stdout
        migrate("head")
        barrier = Barrier(2)

        def build_batch():
            with sessions() as db:
                barrier.wait(timeout=10)
                result = CaseHistoryIndexService.reconcile_batch(db, limit=2)
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            batches = list(pool.map(lambda _: build_batch(), range(2)))
        assert sorted(item["after_case_id"] for item in batches) == [2, 4]
        with sessions() as db:
            assert db.query(CaseHistoryIndex).count() == 4
            assert db.query(Case).count() == 4
            indexes = list(db.scalars(select(CaseHistoryIndex).order_by(CaseHistoryIndex.case_id)))
            for position, index in enumerate(indexes):
                store_embedding(db, index, [1., float(position)], 'synthetic-vector-fixture')
            db.commit()
            db.info["authorized_area_ids"] = (area_id,)
            source_hashes = {(index.case_id, index.source_type, index.source_id): index.source_hash for index in indexes}
            distances = exact_distances(db, sources=source_hashes, vector=[1., 0.], model_version='synthetic-vector-fixture')
            assert len(distances) == 4
            assert abs(distances[(1, 'case', '1')]) < 1e-6
            assert distances[(4, 'case', '4')] > distances[(2, 'case', '2')] > 0
            vector_type = db.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid='case_history_embeddings'::regclass AND attname='embedding'")).scalar_one()
            assert vector_type == 'vector'
            assert db.execute(text("SELECT postgis_version()")).scalar_one()
            with patch('app.services.vector_db_service.get_local_embedder', return_value=SimpleNamespace(
                    state='ready', model_version='synthetic-vector-fixture', encode=lambda _: [1., 0.])):
                adapter = VectorDBService()
                matches = adapter.search_similar_cases('软管', min_similarity=0, db=db)
                assert [item['case_id'] for item in matches] == [1, 2, 3, 4]
                assert adapter.status['complete'] is True
                assert all('document' not in item for item in matches)
            result = CaseHistoryRetrieval.search(db, query="打孔盗油软管")
            assert result["coverage"]["indexed_sources"] == 4
            assert result["coverage"]["fallback_sources"] == 0
            db.info["authorized_area_ids"] = ()
            assert not list(db.scalars(select(CaseHistoryIndex)))
            assert not exact_distances(db, sources=source_hashes, vector=[1., 0.], model_version='synthetic-vector-fixture')
            assert CaseHistoryRetrieval.search(db, query="软管")["items"] == []
            db.info["authorized_area_ids"] = (area_id,)
            case = db.scalar(select(Case).where(Case.id == 1))
            case.description, case.location = "修改后没有对应词项", "未知"
            source_event = CasePipelineService.enqueue_case_change(db, case, changed_fields={'description', 'location'})
            db.commit()
            result = CaseHistoryRetrieval.search(db, query="软管", limit=20)
            assert 1 not in {item["case_id"] for item in result["items"]}
            assert result["coverage"]["fallback_sources"] == 1
            db.info.pop('authorized_area_ids')
            priority = CaseHistoryIndexService.reconcile_batch(db, limit=1)
            db.commit()
            assert priority['priority_cases'] == 1 and priority['acknowledged_events'] == 1
            assert source_event.payload['history_index_pending'] is False
            assert source_event.status == 'pending'
            db.info['authorized_area_ids'] = (area_id,)
            updated_index = db.scalar(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == 1))
            assert not exact_distances(db, sources={(1, 'case', '1'): updated_index.source_hash},
                                      vector=[1., 0.], model_version='synthetic-vector-fixture')
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        # A second real PostgreSQL connection can edit while the synthetic
        # model response is pending. A mocked model is not model acceptance.
        from app.config import settings
        from app.models.ai_model import AIModel
        from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
        with sessions() as worker:
            model = AIModel(name="isolated-extractor", provider="openai-compatible",
                            model_name="synthetic", role="analyst", api_key="",
                            config={"api_base": "http://127.0.0.1:9999/v1", "revision": "test"})
            worker.add(model)
            worker.commit()
            with patch.object(settings, 'CASE_SEMANTIC_MODEL_ID', model.id):
                case = worker.get(Case, 3)
                event = CasePipelineService.enqueue_case_change(worker, case)
                event_id = event.id
                worker.commit()

                def concurrent_edit(*_):
                    assert not worker.in_transaction()
                    with sessions() as editor:
                        editor.execute(text("SET LOCAL lock_timeout = '1s'"))
                        editor.execute(text("UPDATE cases SET description='合成并发编辑' WHERE id=3"))
                        editor.commit()
                    return '{"fragments":[]}'

                with patch('app.services.case_local_semantic_model._request', side_effect=concurrent_edit):
                    processed = CasePipelineService.process_event(worker, event_id)
                assert processed['status'] == 'superseded'
                assert worker.query(CaseAnalysisProfile).filter_by(case_id=3).count() == 0
                fresh = worker.query(OutboxEvent).filter_by(aggregate_id='3', status='pending',
                    event_type='case.analysis.requested').one()
                with patch('app.services.case_local_semantic_model._request', return_value='{"fragments":[]}'):
                    assert CasePipelineService.process_event(worker, fresh.id)['status'] == 'completed'
                profile = worker.query(CaseAnalysisProfile).filter_by(case_id=3).one()
                assert profile.payload['semantics']['model_extraction']['status'] == 'ready'
        # v5.0 result reuse is serialized by an actual PostgreSQL row lock.
        # Reuse the normal rule pipeline; no fabricated current snapshot.
        from app.services.conclusion_factory_service import ConclusionFactoryService
        from app.models.conclusion import Conclusion
        with sessions() as db:
            db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: 'write'})
            case = db.get(Case, 4)
            case.description = '升级后新增的合成原始资料，须在新版备份中保留。'
            event = CasePipelineService.enqueue_case_change(db, case)
            db.commit()
            assert CasePipelineService.process_event(db, event.id)['status'] == 'completed'
        conclusion_barrier = Barrier(2)

        def create_draft():
            with sessions() as db:
                db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: 'write'})
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                conclusion_barrier.wait(timeout=10)
                result = asyncio.run(ConclusionFactoryService.generate_conclusion(db, 4))
                identifier = result.id
                db.commit()
                return identifier

        with ThreadPoolExecutor(max_workers=2) as pool:
            conclusion_ids = list(pool.map(lambda _: create_draft(), range(2)))
        assert conclusion_ids[0] == conclusion_ids[1]
        with sessions() as db:
            assert db.query(Conclusion).filter_by(case_id=4).count() == 1
            expected_cases = list(db.execute(text('SELECT row_to_json(cases)::text FROM cases ORDER BY id')).scalars())
        dump = docker("exec", container, "pg_dump", "-U", "aic_history_test", "-Fc", "aic_history_test",
                      capture_output=True).stdout
        docker("exec", container, "createdb", "-U", "aic_history_test", "aic_history_restored", capture_output=True)
        docker("exec", "-i", container, "pg_restore", "-U", "aic_history_test", "--exit-on-error",
               "--no-owner", "-d", "aic_history_restored", input=dump, capture_output=True)
        restored = create_engine(make_url(url).set(database="aic_history_restored"))
        try:
            with restored.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM cases")).scalar_one() == 4
                assert conn.execute(text("SELECT count(*) FROM case_history_indexes")).scalar_one() == 4
                assert conn.execute(text("SELECT count(*) FROM case_history_embeddings")).scalar_one() == 4
                assert conn.execute(text("SELECT description FROM cases WHERE id=1")).scalar_one() == "修改后没有对应词项"
                assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
                assert list(conn.execute(text('SELECT row_to_json(cases)::text FROM cases ORDER BY id')).scalars()) == expected_cases
                assert conn.execute(text('SELECT count(*) FROM conclusions WHERE case_id=4')).scalar_one() == 1
        finally:
            restored.dispose()
            engine.dispose()
        # Restore the matching old schema into a different DB, never downgrade
        # the new DB or discard new raw records while changing application code.
        docker("exec", container, "createdb", "-U", "aic_history_test", "aic_history_previous", capture_output=True)
        docker("exec", "-i", container, "pg_restore", "-U", "aic_history_test", "--exit-on-error",
               "--no-owner", "-d", "aic_history_previous", input=previous_dump, capture_output=True)
        previous_engine = create_engine(make_url(url).set(database="aic_history_previous"))
        try:
            with previous_engine.connect() as conn:
                assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == 'b508c42fd75b'
                assert conn.execute(text('SELECT count(*) FROM cases')).scalar_one() == 4
                assert conn.execute(text("SELECT to_regclass('case_history_indexes')")).scalar_one() is None
        finally:
            previous_engine.dispose()
        print(json.dumps({"status": "passed", "synthetic_only": True, "revision": revision,
                          "postgres_image": image, "concurrent_batches": 2, "cases": 4,
                          "scope_revocation": "passed", "stale_index_excluded": "passed",
                          "native_vector_type": vector_type, "exact_cosine_ordering": "passed",
                          "saved_event_priority": "passed", "stale_vector_excluded": "passed",
                          "legacy_native_vector_adapter": "passed",
                          "model_wait_releases_case_lock": "passed", "model_stale_input_discarded": "passed",
                          "concurrent_conclusion_reuse": "passed", "new_raw_rows_restored_exactly": True,
                          "previous_schema_restored_separately": True,
                          "backup_restored": True, "backup_sha256": hashlib.sha256(dump).hexdigest(),
                          "target_server_verified": False, "semantic_model_verified": False}, ensure_ascii=False))
    finally:
        if container:
            # Target is only the exact container ID created above; no shared volumes.
            docker("rm", "-f", "-v", container, capture_output=True, env=env)


if __name__ == "__main__":
    main()
