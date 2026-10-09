"""Opt-in real PostgreSQL evidence; only the dedicated v9 synthetic map DB."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import uuid4
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.mark.skipif(not os.getenv('AIC_V9_MAP_PG_URL'), reason='requires explicitly isolated v9 map PostgreSQL')
def test_durable_map_jobs_concurrent_claim_rollback_visibility_and_revoke(monkeypatch):
    value = make_url(os.environ['AIC_V9_MAP_PG_URL'])
    assert value.host == '127.0.0.1' and value.database == 'aic_v9_map'
    engine = create_engine(value)
    from app.models.user import User
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.map_foundation import MapFeatureClaim, MapIngestRun, UserAreaScope
    from app.services.map_foundation_service import MapFoundationService as S
    from app.services.map_ingest_jobs import enqueue, process_next
    from tests.test_map_ledger_v72 import BASE, csv_bytes
    token = uuid4().hex[:12]
    started = monotonic()
    with Session(engine) as db:
        assert db.scalar(text('SELECT current_database()')) == 'aic_v9_map'
        actor = User(username='map-v9-' + token, display_name='合成地图管理员', password_hash='not-a-login', role='admin', is_active=True)
        db.add(actor); db.commit()
        actor_id = actor.id
        source = S.create_source(db, {'source_key': 'synthetic-v9-' + token, 'name': 'v9 合成台账', 'source_type': 'ledger'})
        source_id, area_id = source.id, source.operational_area_id
        template = S.create_template(db, {'source_id': source_id, 'name': '合成模板', 'coordinate_system': 'wgs84',
            'field_mapping': {'external_id': '井号', 'name': '井名', 'asset_type': '类型', 'longitude': '经度', 'latitude': '纬度'}})
        template_id = template.id
        run, _ = enqueue(db, source_id=source_id, template_id=template_id, filename='synthetic.csv',
            content=csv_bytes([{**BASE, '井号': token + '-' + str(n)} for n in range(20)]),
            source_revision='synthetic-atomic', actor_id=actor_id)
        run_id = run.id

    def work():
        with Session(engine) as db:
            return process_next(db, chunk_size=3)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: work(), range(4)))
    for _ in range(30):
        with Session(engine) as db:
            state = db.get(MapIngestRun, run_id).status
        if state == 'adopting':
            break
        assert state in {'queued', 'parsing', 'planning'}, state
        work()
    assert state == 'adopting'
    with Session(engine) as db:
        assert db.query(MapFeatureClaim).filter_by(run_id=run_id).count() == 20
        assert db.query(JurisdictionAsset).filter(JurisdictionAsset.external_id.like(token + '%')).count() == 0

    original_merge = S._merge_asset
    failed = False
    def crash_after_one(*args, **kwargs):
        nonlocal failed
        result = original_merge(*args, **kwargs)
        if not failed:
            failed = True
            raise RuntimeError('synthetic checkpoint interruption')
        return result
    monkeypatch.setattr(S, '_merge_asset', staticmethod(crash_after_one))
    with pytest.raises(RuntimeError, match='synthetic checkpoint'):
        work()
    with Session(engine) as db:
        assert db.query(JurisdictionAsset).filter(JurisdictionAsset.external_id.like(token + '%')).count() == 0
        assert db.get(MapIngestRun, run_id).status == 'adopting'

    changed, release = Event(), Event()
    def hold_first_write(*args, **kwargs):
        result = original_merge(*args, **kwargs)
        if not changed.is_set():
            changed.set()
            assert release.wait(20)
        return result
    monkeypatch.setattr(S, '_merge_asset', staticmethod(hold_first_write))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work)
        try:
            assert changed.wait(20)
            with Session(engine) as db:
                # Another ordinary reader cannot see a half-written batch.
                assert db.query(JurisdictionAsset).filter(JurisdictionAsset.external_id.like(token + '%')).count() == 0
                # The area serialization lock must not block an unrelated case
                # save that needs only a foreign-key KEY SHARE lock.
                from app.services.case_service import CaseService
                db.execute(text("SET LOCAL lock_timeout = '2s'"))
                CaseService.create_case(db, case_number=None, operational_area_id=area_id,
                    description='地图采用期间的独立合成记录', commit=False)
                db.commit()
        finally:
            release.set()
        assert future.result(timeout=30)['state'] == 'completed'
    monkeypatch.setattr(S, '_merge_asset', staticmethod(original_merge))
    with Session(engine) as db:
        assert db.query(JurisdictionAsset).filter(JurisdictionAsset.external_id.like(token + '%')).count() == 20
        assert db.query(MapFeatureClaim).filter_by(run_id=run_id).count() == 20
        actor = db.get(User, actor_id); actor.role = 'analyst'
        grant = UserAreaScope(user_id=actor_id, operational_area_id=area_id, access_level='manage')
        db.add(grant); db.commit()
        revoke, _ = enqueue(db, source_id=source_id, template_id=template_id, filename='revoke.csv',
            content=csv_bytes([{**BASE, '井号': token + '-revoked'}]), source_revision='revoke', actor_id=actor_id)
        revoked_id = revoke.id
        grant.access_level = 'read'; db.commit()
    result = work()
    assert result == {'state': 'failed', 'run_id': revoked_id}
    with Session(engine) as db:
        assert not db.query(JurisdictionAsset).filter_by(external_id=token + '-revoked').first()
    engine.dispose()
    print(f'v9 synthetic map PG: rows=20 chunk=3, concurrent workers=4, rollback+atomic visibility+revoke passed; elapsed={monotonic()-started:.3f}s; prefix={token}')
