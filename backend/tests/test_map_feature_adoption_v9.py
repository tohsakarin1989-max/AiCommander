"""Legacy write surfaces must use the same governed foundation receipts."""
from tests.test_jurisdiction_context import api_db_session, _build_client  # noqa: F401
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapFieldDecision, MapSource, JurisdictionAssetVersion, OperationalArea, UserAreaScope
from app.models.user import User
from app.services.jurisdiction_service import JurisdictionService as S


def payload(**changes):
    return {'name': '合成井', 'asset_type': 'well', 'external_id': 'W1',
            'latitude': 46.6, 'longitude': 125.1, **changes}


def test_manual_records_source_identity_adoption_and_no_invented_scores(api_db_session):
    client = _build_client(api_db_session)
    value = client.post('/api/jurisdiction/assets', json=payload()).json()
    assert value['risk_level'] is None and value['confidence_score'] is None
    assert value['attributes']['source_identity_id']
    assert api_db_session.query(MapFeatureClaim).one().asset_id == value['id']
    assert api_db_session.query(MapFieldDecision).filter_by(asset_id=value['id']).count() >= 4
    assert api_db_session.query(JurisdictionAssetVersion).one().source_claim_id
    update = client.put(f"/api/jurisdiction/assets/{value['id']}", json={'name': '人工核对名称'})
    assert update.status_code == 200, update.text
    decision = api_db_session.query(MapFieldDecision).filter_by(group_key='details').order_by(MapFieldDecision.id.desc()).first()
    assert decision.payload['manual_override']
    assert api_db_session.query(JurisdictionAssetVersion).count() == 2


def test_geojson_retains_multiline_and_polygon_and_raw_source(api_db_session):
    geometries = [
        {'type': 'MultiLineString', 'coordinates': [[[125.1, 46.6], [125.11, 46.61]], [[125.2, 46.6], [125.2, 46.7]]]},
        {'type': 'Polygon', 'coordinates': [[[125, 46], [125.1, 46], [125.1, 46.1], [125, 46]]] },
    ]
    source = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'id': str(i),
        'properties': {'name': '同名区域', 'asset_type': 'road'}, 'geometry': geometry} for i, geometry in enumerate(geometries)]}
    result = S.import_geojson(api_db_session, source)
    assert result['created'] == 2 and not result['errors']
    assert [asset.geometry for asset in api_db_session.query(JurisdictionAsset).order_by(JurisdictionAsset.id)] == geometries
    assert api_db_session.query(MapFeatureClaim).first().raw_payload['original_record'] == source['features'][0]
    assert S.import_geojson(api_db_session, source)['created'] == 0
    assert api_db_session.query(JurisdictionAsset).count() == 2


def test_bad_geometry_remains_a_failed_source_and_never_becomes_point(api_db_session):
    raw = {'名称': '缺线形道路', '类型': 'road', '几何类型': 'line', '经度': 125.1, '纬度': 46.6}
    result = S.import_tabular_assets(api_db_session, [raw])
    assert result['created'] == 0 and result['errors']
    assert api_db_session.query(JurisdictionAsset).count() == 0
    claim = api_db_session.query(MapFeatureClaim).one()
    assert claim.status == 'quarantined' and claim.raw_payload == raw and claim.row_number == 2


def test_table_preview_read_only_and_chinese_production_fields_governed(api_db_session):
    rows = [{'井号': 'W1', '井名': '生产台账', '类型': 'well', '经度': 125.1, '纬度': 46.6,
             '油品': '原油', '含水率下限': 30, '含水率上限': 40, '含水率单位': '%', '含水率测量口径': '质量'}]
    before = api_db_session.query(MapSource).count()
    assert S.import_tabular_assets(api_db_session, rows, dry_run=True)['valid'] == 1
    assert api_db_session.query(MapSource).count() == before
    assert S.import_tabular_assets(api_db_session, rows, filename='synthetic-source.csv')['created'] == 1
    asset = api_db_session.query(JurisdictionAsset).one()
    assert asset.attributes['water_cut_min'] == 30
    decision = api_db_session.query(MapFieldDecision).filter_by(group_key='water_cut').one()
    assert decision.payload['new']['water_cut_unit'] == '%'
    assert api_db_session.query(MapFeatureClaim).one().raw_payload['original_record'] == rows[0]
    from app.models.map_foundation import MapIngestRun
    assert api_db_session.query(MapIngestRun).one().filename == 'synthetic-source.csv'


def test_reserved_source_metadata_cannot_claim_a_registered_source(api_db_session):
    client = _build_client(api_db_session)
    result = client.post('/api/jurisdiction/assets', json=payload(attributes={'source_id': 999, 'field_groups': {}}))
    assert result.status_code == 400
    assert api_db_session.query(JurisdictionAsset).count() == 0


def test_manage_permission_is_area_scoped_and_rechecked_for_user(api_db_session):
    db = api_db_session
    area = db.info['default_operational_area_id']
    other = OperationalArea(code='other', name='其他厂区', status='active')
    user = User(id=7, username='maintainer-v9', display_name='合成维护员', password_hash='test-only', role='analyst', is_active=True)
    db.add_all([other, user])
    db.flush()
    scope = UserAreaScope(user_id=user.id, operational_area_id=area, access_level='manage')
    db.add(scope)
    db.commit()
    db.info.update(principal_user_id=user.id, principal_role='analyst', authorized_area_ids=(area, other.id),
                   area_access_levels={area: 'manage', other.id: 'write'})
    client = _build_client(db)
    assert client.post('/api/jurisdiction/assets', json=payload()).status_code == 200
    assert client.post('/api/jurisdiction/assets', json=payload(operational_area_id=other.id)).status_code == 403
    # Even a stale request session cannot retain revoked maintenance access.
    scope.access_level = 'write'
    db.commit()
    assert client.post('/api/jurisdiction/assets', json=payload(external_id='W2')).status_code == 403


def test_normal_writer_cannot_use_any_legacy_import_write_path(api_db_session):
    db = api_db_session
    area = db.info['default_operational_area_id']
    db.info.update(authorized_area_ids=(area,), area_access_levels={area: 'write'})
    client = _build_client(db)
    for path, body in [('/assets', payload()), ('/assets/bulk', {'items': [payload()]}),
        ('/assets/import-geojson', {'geojson': {'type': 'FeatureCollection', 'features': []}})]:
        assert client.post('/api/jurisdiction' + path, json=body).status_code == 403
    assert client.post('/api/jurisdiction/assets/import-table', files={'file': ('test.csv', '名称,类型\n测试,well'.encode(), 'text/csv')}).status_code == 403


def test_real_auth_middleware_to_legacy_write_service(api_db_session):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.api import auth, jurisdiction
    from app.database import get_db, bind_principal_scope
    from app.security import AuthMiddleware
    from app.services.auth_service import AuthService

    db = api_db_session
    area = db.info['default_operational_area_id']
    other = OperationalArea(code='middleware-other', name='其他厂区', status='active')
    user = User(id=8, username='scoped-map-v9', display_name='合成维护员',
                password_hash=AuthService.hash_password('SyntheticPassword!2026'), role='analyst', is_active=True)
    db.add_all([other, user])
    db.flush()
    db.add_all([UserAreaScope(user_id=user.id, operational_area_id=area, access_level='manage'),
                UserAreaScope(user_id=user.id, operational_area_id=other.id, access_level='write')])
    db.commit()
    factory = sessionmaker(bind=db.bind, autoflush=False)
    app = FastAPI()
    app.include_router(auth.router, prefix='/api/auth')
    app.include_router(jurisdiction.router, prefix='/api/jurisdiction')
    def scoped_db(request: Request):
        with factory() as session:
            bind_principal_scope(session, getattr(request.state, 'principal', None), method=request.method)
            yield session
    app.dependency_overrides[get_db] = scoped_db
    app.add_middleware(AuthMiddleware, session_factory=factory, auth_required=True,
        bootstrap_token='not-used', secure_cookie=False, allowed_origins=('http://testserver',))
    client = TestClient(app)
    assert client.post('/api/auth/login', json={'username': user.username, 'password': 'SyntheticPassword!2026'}).status_code == 200
    result = client.post('/api/jurisdiction/assets', json=payload())
    assert result.status_code == 200, result.text
    identifier = result.json()['id']
    assert client.put(f'/api/jurisdiction/assets/{identifier}', json={'description': '人工补充'}).status_code == 200
    assert client.post('/api/jurisdiction/assets', json=payload(operational_area_id=other.id)).status_code == 403
    assert client.post('/api/jurisdiction/assets/sync-public-map', json={}).status_code == 403
    db.query(UserAreaScope).filter_by(user_id=user.id, operational_area_id=area).update({'access_level': 'write'})
    db.commit()
    assert client.delete(f'/api/jurisdiction/assets/{identifier}').status_code == 403
    assert client.post('/api/jurisdiction/assets/bulk', json={'items': [payload(external_id='DENIED')]}).status_code == 403
