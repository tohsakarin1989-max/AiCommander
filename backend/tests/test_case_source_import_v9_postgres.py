"""Opt-in, synthetic-only check in the dedicated v9 map validation database."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.case import Case
from app.models.case_import import CaseImportSourceRecord
from app.models.map_foundation import OperationalArea
from app.services import case_source_import as service
from app.services.case_import_table import parse_case_table
from app.services.case_service import CaseService


@pytest.mark.skipif(not os.getenv('AIC_V9_MAP_PG_URL'), reason='Requires dedicated synthetic PostgreSQL validation DB')
def test_source_concurrency_and_interleaved_manual_fact_are_preserved(monkeypatch):
    url = make_url(os.environ['AIC_V9_MAP_PG_URL'])
    assert url.host == '127.0.0.1' and url.database == 'aic_v9_map'
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, autoflush=False)
    prefix = uuid4().hex[:12]
    with factory() as db:
        area = OperationalArea(code=f'v9-case-{prefix}', name='合成来源并发测试区')
        db.add(area)
        db.commit()
        area_id = area.id

    def scoped(db):
        db.info.update(authorized_area_ids=(area_id,), area_access_levels={area_id: 'manage'})

    header = '源记录键,发现时间,地点,简要案情,油品类型\n'
    row = 'A,2026-10-09,合成测试点,无真实业务信息,原油\n'
    content = (header + row).encode()

    def import_data(db, data=content, version='1'):
        return service.import_source_table(db, table=parse_case_table('synthetic.csv', data), content=data,
            area_id=area_id, source_key=f'synthetic-{prefix}', source_revision=version, time_zone='Asia/Shanghai')

    barrier = Barrier(4)

    def writer():
        with factory() as db:
            scoped(db)
            barrier.wait(10)
            return import_data(db)

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: writer(), range(4)))
        assert sum(result['created'] for result in results) == 1
        assert sum(bool(result['replayed']) for result in results) == 3
        with factory() as db:
            scoped(db)
            case_id = db.query(Case).one().id
            assert db.query(CaseImportSourceRecord).count() == 1

        ready, proceed = Event(), Event()
        original_plan = service._plan

        def held_plan(*args, **kwargs):
            ready.set()
            assert proceed.wait(10)
            return original_plan(*args, **kwargs)

        monkeypatch.setattr(service, '_plan', held_plan)

        def update_source():
            with factory() as db:
                scoped(db)
                return import_data(db, content.replace('原油'.encode(), '柴油'.encode()), '2')

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(update_source)
            try:
                assert ready.wait(10)
                with factory() as db:
                    scoped(db)
                    CaseService.update_case(db, case_id, oil_type='合成人工确认')
            finally:
                proceed.set()
            assert future.result(timeout=10)['conflict'] == 1
        with factory() as db:
            scoped(db)
            assert db.query(Case).one().oil_type == '合成人工确认'
        print(f'v9 source PG: 4 concurrent requests, 1 case; interleaved manual edit protected; prefix={prefix}')
    finally:
        engine.dispose()
