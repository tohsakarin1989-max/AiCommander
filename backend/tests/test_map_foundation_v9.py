"""Synthetic source fixtures: staged jobs, exact mappings, no inferred facts."""
import io
from copy import deepcopy

import openpyxl
import pytest

from tests.test_map_foundation import db_session, _client, _create_source, _create_template
from tests.test_map_ledger_v72 import BASE, csv_bytes, setup, ingest
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapIngestRun
from app.services.map_foundation_service import MapFoundationService as S
from app.services.map_ingest_jobs import enqueue, process_next, control
from app.services.map_ingest_tables import inspect_table


def job(db, source, template, rows, declaration=None):
    return enqueue(db, source_id=source['id'], template_id=template.id,
        filename='synthetic.csv', content=csv_bytes(rows), source_revision='v9-synthetic',
        actor_id=1, ledger_declaration=declaration)[0]


def test_reorder_and_unused_note_reuses_template_but_missing_mapped_column_blocks(db_session):
    source, template = setup(db_session, expected_structure={'headers': list(BASE), 'header_row': 1, 'sheet_name': None})
    content = csv_bytes([{**BASE, '备注': '合成'}], headers=['备注', *reversed(BASE)])
    view = inspect_table(db_session, source['id'], 'synthetic.csv', content)
    assert view['recommended_template_id'] == template.id
    plan = S.preview(db_session, source_id=source['id'], template_id=template.id, filename='synthetic.csv', content=content)
    assert not plan['drift'] and plan['structure_changes']
    bad = csv_bytes([{key: val for key, val in BASE.items() if key != '经度'}])
    assert inspect_table(db_session, source['id'], 'bad.csv', bad)['recommended_template_id'] is None


def test_file_inspection_selects_real_sheet_and_header(db_session):
    source = _create_source(_client(db_session))
    book = openpyxl.Workbook()
    book.active.title = '说明'
    book.active.append(['不是台账'])
    sheet = book.create_sheet('生产表')
    sheet.append(['合成来源'])
    sheet.append(list(BASE))
    sheet.append(list(BASE.values()))
    output = io.BytesIO()
    book.save(output)
    view = inspect_table(db_session, source['id'], 'test.xlsx', output.getvalue(), sheet_name='生产表', header_row=2)
    assert view['structure']['available_sheets'] == ['说明', '生产表']
    assert view['structure']['header_row'] == 2
    assert view['suggested_mapping']['external_id'] == '井号'


def test_pasted_tsv_retains_exact_original_and_manual_origin(db_session):
    source, template = setup(db_session)
    text = '\t'.join(BASE) + '\r\n' + '\t'.join(str(value) for value in BASE.values()) + '\r\n'
    run, _ = enqueue(db_session, source_id=source['id'], template_id=template.id,
        filename='人工粘贴.tsv', content=text.encode(), source_revision='手工选区', actor_id=1, input_kind='clipboard')
    from app.services.map_ingest_originals import read_original
    assert read_original(db_session, run.id)[0] == text.encode()
    assert run.table_metadata['job']['input_kind'] == 'clipboard'
    assert '不代表完整原始工作簿' in run.table_metadata['job']['origin_boundary']
    while process_next(db_session)['state'] != 'completed':
        pass
    assert db_session.query(JurisdictionAsset).count() == 1


def test_staged_job_is_durable_invisible_until_atomic_adoption_and_idempotent(db_session):
    source, template = setup(db_session)
    rows = [{**BASE, '井号': f'S-{n}'} for n in range(3)]
    run = job(db_session, source, template, rows)
    assert job(db_session, source, template, rows).id == run.id
    assert db_session.query(JurisdictionAsset).count() == 0
    for expected in ['parsing', 'planning', 'planning', 'adopting']:
        assert process_next(db_session, chunk_size=2)['state'] == expected
        assert db_session.query(JurisdictionAsset).count() == 0
    assert db_session.query(MapFeatureClaim).count() == 3
    assert process_next(db_session, chunk_size=2)['state'] == 'completed'
    assert db_session.query(JurisdictionAsset).count() == 3
    assert db_session.query(MapFeatureClaim).count() == 3
    assert all(asset.risk_level is None and asset.confidence_score is None for asset in db_session.query(JurisdictionAsset))
    assert process_next(db_session)['state'] == 'idle'


def test_pause_resume_cancel_preserves_source_and_never_adopts(db_session):
    source, template = setup(db_session)
    run = job(db_session, source, template, [BASE])
    process_next(db_session, chunk_size=1)
    control(db_session, run.id, action='pause', actor_id=1)
    assert process_next(db_session)['state'] == 'idle'
    control(db_session, run.id, action='resume', actor_id=1)
    assert run.status == 'planning'
    control(db_session, run.id, action='cancel', actor_id=1)
    assert db_session.query(JurisdictionAsset).count() == 0
    assert db_session.query(MapFeatureClaim).count() == 1
    assert run.original_evidence_object_id


def test_complete_ledger_with_bad_rows_does_not_publish_partial_facilities(db_session):
    source, template = setup(db_session)
    run = job(db_session, source, template, [BASE, {**BASE, '井号': 'B', '经度': '未知'}], declaration={
        'mode': 'full', 'scope_key': 'synthetic-all', 'scope_description': '合成测试全集',
        'valid_from': '2026-10-01T00:00:00Z', 'valid_to': '2026-11-01T00:00:00Z'})
    process_next(db_session)
    process_next(db_session)
    assert run.status == 'ready_to_adopt'
    from app.services.map_ingest_jobs import preview_job
    preview = preview_job(db_session, run.id)
    with pytest.raises(ValueError, match='full_ledger_incomplete'):
        control(db_session, run.id, action='adopt', actor_id=1, plan_token=preview['plan_token'])
    assert db_session.query(JurisdictionAsset).count() == 0


def test_changed_asset_after_plan_fails_without_overwriting(db_session):
    source, template = setup(db_session)
    ingest(db_session, source, template, [BASE])
    run = job(db_session, source, template, [{**BASE, '井名': '来源更新'}])
    process_next(db_session)
    process_next(db_session)
    asset = db_session.query(JurisdictionAsset).one()
    asset.name = '人工已更正'
    db_session.commit()
    assert process_next(db_session)['state'] == 'failed'
    db_session.refresh(asset)
    assert asset.name == '人工已更正'


@pytest.mark.parametrize('crs', ['cgcs2000_gauss_kruger', 'local_control_points'])
def test_unverified_projection_never_uses_affine_as_fact(crs):
    with pytest.raises(ValueError, match='coordinate_conversion_unverified'):
        S._to_wgs84(1, 2, coordinate_system=crs, transformation=dict(a=1, b=0, c=0, d=0, e=1, f=0))


def test_job_api_accepts_and_records_in_background(db_session):
    client = _client(db_session)
    source = _create_source(client)
    template = _create_template(client, source['id'])
    result = client.post(f"/api/map-sources/{source['id']}/jobs?template_id={template['id']}",
                         files={'file': ('synthetic.csv', csv_bytes([BASE]), 'text/csv')})
    assert result.status_code == 202, result.text
    assert result.json()['status'] == 'queued'
    assert db_session.query(JurisdictionAsset).count() == 0


def test_withdrawn_manage_permission_stops_queued_job(db_session):
    from app.models.user import User
    from app.models.map_foundation import UserAreaScope
    source, template = setup(db_session)
    actor = db_session.get(User, 1)
    actor.role = 'analyst'
    access = UserAreaScope(user_id=1, operational_area_id=source['operational_area']['id'], access_level='manage')
    db_session.add(access)
    db_session.commit()
    run = job(db_session, source, template, [BASE])
    access.access_level = 'write'
    db_session.commit()
    assert process_next(db_session)['state'] == 'failed'
    assert db_session.query(JurisdictionAsset).count() == 0
    assert db_session.query(MapFeatureClaim).count() == 0


def test_manager_routes_only_expose_manage_areas_and_do_not_grant_originals(db_session):
    from app.models.map_foundation import OperationalArea
    source, template = setup(db_session)
    second = OperationalArea(code='not-managed', name='合成只读区')
    db_session.add(second)
    db_session.commit()
    hidden = S.create_source(db_session, {'source_key': 'hidden-source', 'name': '未授权维护来源', 'source_type': 'ledger', 'operational_area_id': second.id})
    managed = source['operational_area']['id']
    db_session.info.update(authorized_area_ids=(managed, second.id), area_access_levels={managed: 'manage', second.id: 'write'}, principal_user_id=1)
    client = _client(db_session, role='analyst')
    response = client.get('/api/map-sources')
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == [source['id']]
    forbidden = client.post('/api/map-sources', json={'source_key': 'attempt', 'name': '越界', 'source_type': 'ledger', 'operational_area_id': second.id})
    assert forbidden.status_code == 403
    scopes = client.get('/api/map-maintenance-scope').json()
    assert not scopes['can_download_original'] and not scopes['can_publish_map']
    assert [area['id'] for area in scopes['areas']] == [managed]


def test_issue_resolution_has_source_receipt_and_never_changes_asset(db_session):
    from app.services.map_data_issues import record_issue, resolve_issue, list_work, list_issues
    from app.models.map_foundation import JurisdictionAssetVersion
    source, template = setup(db_session)
    ingest(db_session, source, template, [BASE])
    asset = db_session.query(JurisdictionAsset).one()
    claim = db_session.query(MapFeatureClaim).one()
    reference = {'field_group': 'production', 'source_claim_id': claim.id}
    issue = record_issue(db_session, {'asset_id': asset.id, 'notes': '合成资料需要核对', 'source_reference': reference})
    before = deepcopy(S.asset_to_dict(asset))
    payload = {'state': 'needs_information', 'expected_state': 'reported', 'note': '尚未收到来源补充', 'request_id': 'synthetic-resolution-1'}
    result = resolve_issue(db_session, issue.id, payload, actor_id=1)
    assert result['state'] == 'needs_information'
    assert resolve_issue(db_session, issue.id, payload, actor_id=1) == result
    with pytest.raises(ValueError, match='new_revision_required'):
        resolve_issue(db_session, issue.id, {**payload, 'state': 'corrected', 'source_reference': reference}, actor_id=1)
    assert S.asset_to_dict(asset) == before
    assert list_issues(db_session, asset.id, page=1, page_size=10)['items'][0]['state'] == 'needs_information'
    assert list_work(db_session, source_id=source['id'])['total'] == 1
    db_session.info['authorized_area_ids'] = ()
    assert list_work(db_session)['total'] == 0


def test_duplicate_identity_across_chunks_never_auto_adopts(db_session):
    source, template = setup(db_session)
    run = job(db_session, source, template, [BASE, {**BASE, '井名': '同键另一行'}])
    for _ in range(4):
        process_next(db_session, chunk_size=1)
    assert run.status == 'ready_to_adopt'
    assert run.classification_counts['failed'] == 2
    assert db_session.query(JurisdictionAsset).count() == 0


def test_real_auth_middleware_scopes_manager_and_blocks_admin_actions(db_session):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.api import auth, map_foundation
    from app.database import get_db, bind_principal_scope
    from app.models.user import User
    from app.models.map_foundation import OperationalArea, UserAreaScope
    from app.security import AuthMiddleware
    from app.services.auth_service import AuthService
    source, template = setup(db_session)
    second = OperationalArea(code='auth-write-only', name='不可维护区')
    db_session.add(second)
    db_session.flush()
    hidden = S.create_source(db_session, {'source_key': 'auth-hidden', 'name': '不可维护来源',
        'source_type': 'ledger', 'operational_area_id': second.id})
    actor = db_session.get(User, 1)
    actor.role = 'analyst'
    actor.password_hash = AuthService.hash_password('SyntheticOnly!2026')
    db_session.add_all([UserAreaScope(user_id=1, operational_area_id=source['operational_area']['id'], access_level='manage'),
                       UserAreaScope(user_id=1, operational_area_id=second.id, access_level='write')])
    db_session.commit()
    factory = sessionmaker(bind=db_session.bind, autoflush=False)
    app = FastAPI()
    app.include_router(auth.router, prefix='/api/auth')
    app.include_router(map_foundation.router, prefix='/api')

    def scoped_db(request: Request):
        with factory() as db:
            bind_principal_scope(db, getattr(request.state, 'principal', None), method=request.method)
            yield db

    app.dependency_overrides[get_db] = scoped_db
    app.add_middleware(AuthMiddleware, session_factory=factory, auth_required=True, secure_cookie=False)
    client = TestClient(app)
    assert client.get('/api/map-sources').status_code == 401
    assert client.post('/api/auth/login', json={'username': actor.username, 'password': 'SyntheticOnly!2026'}).status_code == 200
    response = client.get('/api/map-sources')
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == [source['id']]
    files = {'file': ('synthetic.csv', csv_bytes([BASE]), 'text/csv')}
    assert client.post(f"/api/map-sources/{hidden.id}/inspect", files=files).status_code == 404
    accepted = client.post(f"/api/map-sources/{source['id']}/jobs?template_id={template.id}", files=files)
    assert accepted.status_code == 202, accepted.text
    assert client.get(f"/api/map-ingest-runs/{accepted.json()['id']}/original").status_code == 403
    assert client.post('/api/map-snapshots/build', json={}).status_code == 403
    assert client.get('/api/operational-areas').status_code == 403
    assert client.get('/api/map-maintenance-scope').status_code == 200
    assert client.get('/api/map-data-issues').status_code == 200
    with factory() as db:
        db.query(UserAreaScope).filter_by(user_id=1, operational_area_id=source['operational_area']['id']).one().access_level = 'write'
        db.commit()
    assert client.get('/api/map-sources').status_code == 403
