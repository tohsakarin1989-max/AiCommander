"""Opt-in live database gate; only accepts the disposable v4 test container."""
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, local

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.api.cases import import_cases
from app.models.case import Case
from app.models.case_import import CaseImportBatch, CaseImportRow
from app.services.case_import_retry_service import retry_batch_rows
from app.models.case_pipeline import OutboxEvent
from app.models.map_foundation import OperationalArea
from app.services.dashboard_summary_service import DashboardSummaryService
from app.services.case_service import CaseService


def validated_test_url(value):
    url = make_url(value)
    if url.drivername not in {"postgresql", "postgresql+psycopg2"} or url.query:
        raise ValueError("Only the fixed PostgreSQL test target without query overrides is allowed")
    if (url.host, url.port, url.database, url.username) != ("127.0.0.1", 18440, "aic_v4_test", "aic_test"):
        raise ValueError("Refuse non-test database")
    return url


@pytest.mark.parametrize("value", [
    "postgresql://aic_test@127.0.0.1:18440/aic_v4_test?host=192.0.2.1",
    "postgresql://aic_test@127.0.0.1:18440/aic_v4_test?dbname=other_db&user=other_user",
    "postgresql://aic_test@127.0.0.1:18440/aic_v4_test?service=production",
    "postgresql+asyncpg://aic_test@127.0.0.1:18440/aic_v4_test",
    "postgresql://aic_test@127.0.0.1:5432/production",
])
def test_postgis_gate_rejects_overrides_without_connecting(value):
    with pytest.raises(ValueError):
        validated_test_url(value)


@pytest.mark.skipif(not os.environ.get("AIC_POSTGIS_TEST_URL"), reason="requires disposable PostGIS test container")
def test_real_postgis_import_concurrency_and_business_day_scope(monkeypatch):
    url = validated_test_url(os.environ["AIC_POSTGIS_TEST_URL"])
    engine = create_engine(url)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            assert db.query(Case).count() == 0, "Refuse to run against a populated database"
            assert db.query(CaseImportBatch).count() == 0
            assert db.execute(text("SELECT postgis_version()")).scalar()
            area = OperationalArea(code="v4-pg-one", name="PostGIS合成一区")
            hidden = OperationalArea(code="v4-pg-two", name="PostGIS合成二区")
            db.add_all([area, hidden])
            db.commit()
            area_id, hidden_id = area.id, hidden.id
        barrier = Barrier(4)

        def run():
            with sessions() as db:
                db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: "write"},
                               default_operational_area_id=area_id)
                barrier.wait(timeout=10)
                return import_cases(file=UploadFile(filename="pg.csv", file=io.BytesIO(
                    b"occurred_time,description\n2026-09-09T17:00:00Z,PostGIS fixture\n"
                )), db=db)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: run(), range(4)))
        assert sum(row["created"] for row in results) == 1
        assert sum(row["replayed"] for row in results) == 3
        with sessions() as db:
            assert db.query(Case).count() == db.query(CaseImportBatch).count() == db.query(OutboxEvent).count() == 1
            db.add(Case(case_number="PG-HIDDEN", operational_area_id=hidden_id,
                        occurred_time=datetime(2026, 9, 10, tzinfo=timezone.utc), description="hidden fixture"))
            db.commit()
            db.info["authorized_area_ids"] = (area_id,)
            summary = DashboardSummaryService.build(db, operational_area_id=area_id, days=7,
                                                    as_of=datetime(2026, 9, 10, 12, tzinfo=timezone.utc))
            assert summary["metrics"]["cases"] == 1
            assert next(row["count"] for row in summary["trend"] if row["date"] == "2026-09-10") == 1
            db.info["authorized_area_ids"] = (hidden_id,)
            assert db.query(CaseImportBatch).count() == 0

        # Different failed rows share one receipt; row-level CAS is insufficient.
        with sessions() as db:
            db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: "write"},
                           default_operational_area_id=area_id)
            failed = import_cases(file=UploadFile(filename="corrections.csv", file=io.BytesIO(
                b"occurred_time,description,longitude\n2026-08-01,first,bad\n2026-08-02,second,bad\n"
            )), db=db)
            batch_id = failed["batch_id"]
            assert failed["created"] == 0
        correction_barrier = Barrier(2)

        def correct(number):
            with sessions() as db:
                db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: "write"},
                               default_operational_area_id=area_id)
                # Preload stale objects intentionally, as a request may do.
                db.query(CaseImportBatch).filter_by(id=batch_id).one()
                db.query(CaseImportRow).filter_by(batch_id=batch_id).all()
                correction_barrier.wait(timeout=10)
                return retry_batch_rows(db, batch_id, [
                    {"row": number, "revision": 0, "changes": {"longitude": "124"}},
                ])

        with ThreadPoolExecutor(max_workers=2) as executor:
            corrections = list(executor.map(correct, [2, 3]))
        assert sum(item["created"] for item in corrections) == 2
        with sessions() as db:
            receipt = db.query(CaseImportBatch).filter_by(id=batch_id).one().result
            rows = db.query(CaseImportRow).filter_by(batch_id=batch_id).all()
            assert receipt["created"] == 2
            assert receipt["errors"] == []
            assert all(row.status == "created" and row.revision == 1 for row in rows)
            assert len({row.case_id for row in rows}) == 2

        # Force opposing-date batches to allocate at the same time. Both areas
        # share the namespace but must retain separate business visibility.
        allocation_barrier = Barrier(2)
        worker_state = local()
        original_allocate = CaseService._generate_case_number
        def synchronized_first(db, occurred):
            number = original_allocate(db, occurred)
            if not getattr(worker_state, 'allocated', False):
                worker_state.allocated = True
                allocation_barrier.wait(timeout=10)
            return number
        monkeypatch.setattr(CaseService, '_generate_case_number', synchronized_first)
        def import_different_batch(index):
            with sessions() as db:
                target = [area_id, hidden_id][index]
                db.info.update(authorized_area_ids=(target,), area_access_levels={target: 'write'},
                               default_operational_area_id=target)
                dates = ['2026-12-01', '2026-12-02'][::1 if index == 0 else -1]
                content = 'occurred_time,description\n' + ''.join(f'{day},batch-{index}-{day}\n' for day in dates)
                return import_cases(file=UploadFile(filename=f'parallel-{index}.csv', file=io.BytesIO(content.encode())), db=db)
        with ThreadPoolExecutor(max_workers=2) as executor:
            batches = list(executor.map(import_different_batch, [0, 1]))
        assert all(item['created'] == 2 and item['errors'] == [] for item in batches), batches
        assert all([row['row'] for row in item['preview']] == [2, 3] for item in batches)
        with sessions() as db:
            cases = db.query(Case).filter(Case.case_number.like('202612%')).all()
            assert len(cases) == len({case.case_number for case in cases}) == 4

        failed_batches = []
        for index in range(2):
            with sessions() as db:
                target = [area_id, hidden_id][index]
                db.info.update(authorized_area_ids=(target,), area_access_levels={target: 'write'}, default_operational_area_id=target)
                dates = ['2026-12-10', '2026-12-11'][::1 if index == 0 else -1]
                content = 'occurred_time,description,longitude\n' + ''.join(f'{day},retry-{index},invalid\n' for day in dates)
                item = import_cases(file=UploadFile(filename=f'retry-{index}.csv', file=io.BytesIO(content.encode())), db=db)
                assert item['created'] == 0
                failed_batches.append(item['batch_id'])
        allocation_barrier = Barrier(2)
        def correct_different_batch(index):
            with sessions() as db:
                target = [area_id, hidden_id][index]
                db.info.update(authorized_area_ids=(target,), area_access_levels={target: 'write'}, default_operational_area_id=target)
                return retry_batch_rows(db, failed_batches[index], [
                    {'row': number, 'revision': 0, 'changes': {'longitude': '124'}} for number in [2, 3]
                ])
        with ThreadPoolExecutor(max_workers=2) as executor:
            corrected = list(executor.map(correct_different_batch, [0, 1]))
        assert all(item['created'] == 2 and item['errors'] == [] for item in corrected), corrected
        assert all([row['row'] for row in item['rows']] == [2, 3] for item in corrected)
    finally:
        engine.dispose()
