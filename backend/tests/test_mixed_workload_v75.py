"""One fixed functional concurrency run; not a latency/capacity acceptance gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import platform
import sqlite3
from threading import Barrier, local
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.cases import CaseCreate, create_case
from app.database import Base, bind_principal_scope
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import CaseRevision
from app.models.case_submission import CaseSubmissionReceipt
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.services.case_road_jobs import enqueue_comparison, process_comparison
from app.services.case_road_status import automatic_comparison_status
from app.services.case_search_service import CaseSearchService
from app.services.case_submission_service import submission_status
from app.services.facility_job_checkpoint import progress
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_case_results import result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mixed-workload-v75.sqlite'}",
                           connect_args={'timeout': 20, 'check_same_thread': False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        yield db
    engine.dispose()


def test_fixed_core_saves_queries_and_persistent_scan_coexist(prepared, monkeypatch, tmp_path):
    db, source, previous_matrix_calls = prepared
    engine = db.get_bind()
    # Disjoint authorized areas keep the road input frozen while exercising the
    # same database writer/readers. Same-area intake should invalidate that input.
    db.get(User, 1).role = 'analyst'
    db.add_all([User(id=71, username='mixed-writer', display_name='合成录入',
                    password_hash='not-a-login', role='analyst'),
                User(id=72, username='mixed-reader', display_name='合成查询',
                    password_hash='not-a-login', role='analyst')])
    db.flush()
    db.add_all([UserAreaScope(user_id=1, operational_area_id=1, access_level='write'),
                UserAreaScope(user_id=71, operational_area_id=2, access_level='write'),
                UserAreaScope(user_id=72, operational_area_id=2, access_level='read')])
    db.commit()
    monkeypatch.setattr('app.services.facility_job_checkpoint.SCAN_LIMIT', 3)
    def forbidden(*_args, **_kwargs):
        pytest.fail('this fixed scan workload must not enter model or matrix execution')
    monkeypatch.setattr('app.services.facility_road_batches.calculate_distance_matrix', forbidden)
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda:
        SimpleNamespace(state='not_enabled', model_version=None, dimension=None,
                        encoder_fingerprint=None, encode=forbidden))
    bind_principal_scope(db, SimpleNamespace(user_id=1, role='analyst'), method='POST')
    job = enqueue_comparison(db, result_id=source['id'], analysis_at=AT, vehicle=VEHICLE,
                             engine_version='valhalla-test', include_facility_pool=True)
    db.commit()
    event_id = job['event_id']
    with Session(engine) as baseline:
        originals = {case.id: case.description for case in baseline.scalars(select(Case))}
    db.close()  # No fixture transaction remains open during the three streams.

    barrier, thread_state = Barrier(3), local()
    query_writes, timings, scan_states = [], {}, []
    def observe(_connection, _cursor, statement, *_args):
        if getattr(thread_state, 'query', False) and statement.lstrip().split()[0].upper() in {
                'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
            query_writes.append(statement.split()[0])
    event.listen(engine, 'before_cursor_execute', observe)

    def scoped(user_id, method):
        session = Session(engine, autoflush=False)
        bind_principal_scope(session, SimpleNamespace(user_id=user_id, role='analyst'), method=method)
        return session

    def saves():
        barrier.wait(timeout=10)
        started, ids = time.perf_counter(), []
        for number in range(20):
            with scoped(71, 'POST') as session:
                result = create_case(CaseCreate(case_number=f'MIXED-V75-{number:02}',
                    description=f'并发合成原事实-{number:02}，不得丢失或被派生覆盖。',
                    operational_area_id=2), db=session, idempotency_key=f'mixed-v75-{number:02}')
                ids.append(result.id)
        timings['20_saves_seconds'] = time.perf_counter() - started
        return ids

    def queries():
        barrier.wait(timeout=10)
        started, totals = time.perf_counter(), []
        thread_state.query = True
        try:
            for _ in range(20):
                with scoped(72, 'GET') as session:
                    page = CaseSearchService.page(session, page=1, page_size=100)
                    assert page['total'] >= 1
                    assert all(case.operational_area_id == 2 and case.id != 1 for case in page['items'])
                    totals.append(page['total'])
        finally:
            thread_state.query = False
        timings['20_queries_seconds'] = time.perf_counter() - started
        return totals

    def resume_scans():
        barrier.wait(timeout=10)
        started = time.perf_counter()
        for slice_number in range(2):
            # A fresh Session for each slice proves continuation is durable,
            # not a Python object retained by the first worker call.
            with Session(engine, autoflush=False) as session:
                if slice_number:
                    row = session.get(OutboxEvent, event_id)
                    assert progress(row.payload['facility_checkpoint'])['scanned'] == 3
                    row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    session.commit()
                result = process_comparison(session, event_id, artifact_root=tmp_path)
                assert result['status'] == 'pending', result
                row = session.get(OutboxEvent, event_id, populate_existing=True)
                current = progress(row.payload['facility_checkpoint'])
                assert current['phase'] == 'scan' and not current['scan_complete']
                assert current['scanned'] == (slice_number + 1) * 3
                assert current['road_targets_completed'] == 0
                scan_states.append(current)
        timings['2_scan_slices_seconds'] = time.perf_counter() - started

    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            write_future, query_future, worker_future = pool.submit(saves), pool.submit(queries), pool.submit(resume_scans)
            ids, totals = write_future.result(timeout=40), query_future.result(timeout=40)
            worker_future.result(timeout=40)
        timings['mixed_wall_seconds'] = time.perf_counter() - started
        assert len(set(ids)) == 20 and len(totals) == 20 and not query_writes
        assert len(scan_states) == 2 and not previous_matrix_calls
        with Session(engine) as session:
            for case_id, original in originals.items():
                assert session.get(Case, case_id).description == original
            assert session.query(Case).count() == len(originals) + 20
            assert session.query(CaseRevision).filter(CaseRevision.case_id.in_(ids)).count() == 20
            assert session.query(CaseSubmissionReceipt).filter_by(user_id=71).count() == 20
            assert session.query(OutboxEvent).filter(OutboxEvent.event_type == 'case.analysis.requested',
                OutboxEvent.aggregate_id.in_([str(identifier) for identifier in ids])).count() == 20
            for number, case_id in enumerate(ids):
                case = session.get(Case, case_id)
                assert case.description == f'并发合成原事实-{number:02}，不得丢失或被派生覆盖。'
            row = session.get(OutboxEvent, event_id)
            assert row.status == 'pending' and row.attempts == 2
            assert progress(row.payload['facility_checkpoint'])['scanned'] == 6
            session.query(UserAreaScope).filter_by(user_id=72).delete()
            session.commit()
        thread_state.query = True
        try:
            with scoped(72, 'GET') as session:
                denied = CaseSearchService.page(session, page=1, page_size=100)
                assert denied['total'] == 0 and not denied['items']
            with scoped(71, 'GET') as session:
                for number, case_id in enumerate(ids):
                    assert submission_status(session, f'mixed-v75-{number:02}') == {
                        'status': 'completed', 'case_id': case_id}
            with scoped(1, 'GET') as session:
                assert automatic_comparison_status(session, source['id'])['progress']['scanned'] == 6
        finally:
            thread_state.query = False
        assert not query_writes
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    print('MIXED_WORKLOAD_V75=' + json.dumps({'python': platform.python_version(),
        'sqlite': sqlite3.sqlite_version, 'database': 'isolated_file_sqlite', 'concurrent_streams': 3,
        'saves': 20, 'queries': 20, 'persistent_scan_slices': 2, 'scanned_facilities': 6,
        'query_writes': len(query_writes), 'timings': {key: round(value, 6) for key, value in timings.items()},
        'boundary': '同库不同授权厂区的固定功能性并发；未走模型/矩阵、不设P95门槛，不替代v71性能失败或目标容量验收。'},
        ensure_ascii=False))
