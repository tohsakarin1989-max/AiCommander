"""One frozen local diagnostic, not capacity/Valhalla acceptance; run with -s."""
from datetime import timedelta
import json
import platform
import sqlite3
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshotFeature, JurisdictionAssetVersion
from app.services.case_road_jobs import enqueue_comparison, process_comparison
from app.services.case_road_status import automatic_comparison_status
from app.services.facility_dependency_guard import dependency_signature
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_case_results import result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'facility-scale-v75.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        yield db
    engine.dispose()


def test_frozen_1000_facilities_200_cases_cost_diagnostic(prepared, monkeypatch, tmp_path):
    db, source, matrix_calls = prepared
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda:
        SimpleNamespace(state='not_enabled', model_version=None, dimension=None, encoder_fingerprint=None))
    for identifier in range(14, 1001):
        longitude = 125 + (identifier % 100) / 1000
        attributes = {'oil_type': '原油'}
        db.add(JurisdictionAsset(id=identifier, operational_area_id=1,
            name=f'规模合成设施-{identifier}', asset_type='well', verified=True))
        db.add(MapSnapshotFeature(snapshot_id='map-1', asset_id=identifier, operational_area_id=1,
            name=f'规模合成设施-{identifier}', asset_type='well', geometry_type='point', source='manual',
            status='active', verified=True, latitude=46., longitude=longitude, attributes=attributes))
        db.add(JurisdictionAssetVersion(asset_id=identifier, version=1, change_type='synthetic_declared',
            temporal_status='declared', known_at=AT - timedelta(days=1), valid_from=AT - timedelta(days=30),
            valid_to=AT + timedelta(days=60), snapshot={'id': identifier, 'operational_area_id': 1,
                'asset_type': 'well', 'verified': True, 'status': 'active', 'attributes': attributes}))
    for identifier in range(3, 202):
        db.add(Case(id=identifier, operational_area_id=1, case_number=f'SCALE-SYNTHETIC-{identifier}',
            occurred_time=(AT - timedelta(days=identifier)).replace(tzinfo=None),
            description='仅用于离线规模测量的合成记录', oil_type='原油', facility_type='井口'))
    db.commit()

    def measure(fn):
        statements = []
        def observe(_connection, _cursor, statement, *_rest):
            statements.append(statement.split()[0].upper())
        event.listen(db.bind, 'before_cursor_execute', observe)
        started = time.perf_counter()
        try:
            value = fn()
        finally:
            duration = time.perf_counter() - started
            event.remove(db.bind, 'before_cursor_execute', observe)
        return value, {'seconds': round(duration, 6), 'sql_statements': len(statements),
                       'writes': sum(word in {'INSERT', 'UPDATE', 'DELETE'} for word in statements)}

    signature, signature_cost = measure(lambda: dependency_signature(db))
    job = enqueue_comparison(db, result_id=source['id'], analysis_at=AT, vehicle=VEHICLE,
        engine_version='valhalla-test', include_facility_pool=True)
    db.commit()
    outcome, slice_cost = measure(lambda: process_comparison(db, job['event_id'], artifact_root=tmp_path))
    status, status_cost = measure(lambda: automatic_comparison_status(db, source['id']))
    assert outcome['status'] == 'pending' and not matrix_calls
    assert 0 < status['progress']['scanned'] <= 100 and not status['progress']['scan_complete']
    assert status_cost['writes'] == signature_cost['writes'] == 0
    assert signature['components']['jurisdiction_assets']['count'] == 1000
    assert signature['components']['cases']['count'] == 200
    print('FACILITY_SCALE_V75=' + json.dumps({'python': platform.python_version(),
        'sqlite': sqlite3.sqlite_version, 'database': 'isolated_file_sqlite',
        'authorized_facilities': 1000, 'authorized_cases': 200,
        'dependency_metadata_rows': sum(row['count'] for row in signature['components'].values()),
        'one_dependency_pass': signature_cost, 'one_worker_slice': slice_cost,
        'one_status_read': status_cost, 'progress': status['progress'],
        'boundary': '单次合成规模诊断；未建立200案语义索引，不含模型/实际矩阵，不代表目标服务器容量。'},
        ensure_ascii=False))
