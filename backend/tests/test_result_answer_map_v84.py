"""Frozen-answer map/export plumbing; PNG fixture is not browser acceptance."""
from copy import deepcopy
from datetime import datetime
import io
import json
from zipfile import ZipFile

from PIL import Image
import pytest

from app.models.case_source import CaseLocation
from app.models.map_foundation import MapSnapshot, UserAreaScope
from app.services.result_catalog import read_result
from app.services.result_document import export_result
from app.services.result_map_service import frozen_map, map_context
from tests.test_business_answer_v84 import AS_OF, add_map, create, execute
from tests.test_intelligent_query_tasks import query_db, search_db, add_case  # noqa: F401


@pytest.fixture
async def answer_material(query_db):
    snapshot = add_map(query_db)
    case = add_case(query_db, 'FROZEN-POINTS', discovered_at=datetime(2026, 10, 1), latitude=1, longitude=2)
    query_db.add_all([
        CaseLocation(case_id=case.id, role='discovery', precision='exact',
            geometry={'type': 'Point', 'coordinates': [125, 46]}),
        CaseLocation(case_id=case.id, role='incident', precision='exact',
            geometry={'type': 'Point', 'coordinates': [125.01, 46.01]}),
    ])
    query_db.commit()
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    return query_db, run, snapshot


def map_blocks(material):
    return [json.loads(block['text']) for block in material['document']['blocks'] if block['kind'] == 'map']


def test_query_reader_uses_answer_and_card_frozen_snapshot_once(answer_material):
    db, run, snapshot = answer_material
    material = read_result(db, 'query', run['id'])
    spec = frozen_map(material)
    assert spec['state'] == 'available' and spec['map_snapshot_id'] == snapshot.id
    assert spec['point_count'] == 2
    assert map_blocks(material) == [spec]
    assert material['map']['image_url'] == f"/api/results/query/{run['id']}/map.png"
    assert {point['role'] for point in spec['points']} == {'discovery', 'incident'}
    assert spec['points'][0]['latitude'] == 46  # Never legacy case.latitude=1.
    assert '发现／查获地点' in spec['points'][0]['label']
    assert all(point['evidence_refs'] for point in spec['points'])


def test_multi_snapshot_and_inconsistent_copies_never_merge_or_use_current(answer_material):
    db, run, _ = answer_material
    material = read_result(db, 'query', run['id'])
    original = deepcopy(material)
    context = material['body']['result']['answer']['map_context']
    context['snapshots'].append({'id': 'other-map', 'version': 'other', 'area_id': 2})
    material['body']['result']['cards'][0]['data']['map_context'] = deepcopy(context)
    spec = frozen_map(material)
    assert spec['state'] == 'unavailable' and '不同历史快照' in spec['reason']
    assert 'points' not in spec and 'map_snapshot_id' not in spec
    original['body']['result']['cards'][0]['data']['map_context']['points'][0]['longitude'] = 126
    assert frozen_map(original)['state'] == 'unavailable'


@pytest.mark.parametrize('change', ['alias', 'foreign_point', 'invalid_coordinate', 'untyped_role', 'over_budget'])
def test_invalid_context_is_not_rendered_but_text_remains_readable(answer_material, change):
    db, run, _ = answer_material
    material = read_result(db, 'query', run['id'])
    context = material['body']['result']['answer']['map_context']
    if change == 'alias':
        context['snapshots'][0]['id'] = 'current'
        for point in context['points']:
            point['map_snapshot_id'] = 'current'
    elif change == 'foreign_point':
        context['points'][0]['map_snapshot_id'] = 'unbound-map'
    elif change == 'invalid_coordinate':
        context['points'][0]['latitude'] = float('nan')
    elif change == 'untyped_role':
        context['points'][0]['role'] = 'mentioned'
    else:
        context['points'] = context['points'] * 51
        context['coverage']['shown'] = len(context['points'])
    material['body']['result']['cards'][0]['data']['map_context'] = deepcopy(context)
    assert frozen_map(material)['state'] == 'unavailable'
    assert material['body']['result']['answer']['direct_answer']


def test_map_context_reads_exact_historical_basemap_and_current_permissions(answer_material, monkeypatch):
    from app.services.offline_map_service import OfflineMapService
    db, run, snapshot = answer_material
    snapshot.status = 'superseded'
    db.add(MapSnapshot(id='later-current-map', version='later', operational_area_id=1,
        public_bundle_id=snapshot.public_bundle_id, status='current', manifest={}, feature_watermark='later'))
    db.commit()
    called = []
    def manifest(_db, selected):
        called.append(selected.id)
        return {'snapshot_id': selected.id, 'version': selected.version, 'renderer': 'leaflet',
            'tile_url': f'/api/maps/tiles/{selected.id}/{{z}}/{{x}}/{{y}}', 'network_required': False}
    # Actual tile/browser renderer was not changed by this adapter.
    monkeypatch.setattr(OfflineMapService, 'resolved_manifest', manifest)
    context = map_context(db, 'query', run['id'])
    assert called == [snapshot.id]
    assert context['basemap']['snapshot_id'] == context['map']['map_snapshot_id'] == snapshot.id
    features = context['production']['features']
    assert features[0]['geometry']['coordinates'] == [125, 46]
    assert features[0]['properties']['role'] == 'discovery'
    db.query(UserAreaScope).filter_by(user_id=1).delete()
    db.commit()
    with pytest.raises(PermissionError):
        map_context(db, 'query', run['id'])
    assert called == [snapshot.id]


def test_word_and_pdf_reuse_same_map_snapshot_and_png_without_reanalysis(answer_material, monkeypatch):
    from app.services import result_document
    from app.services.intelligent_query_document import export_query_document
    db, run, snapshot = answer_material
    encoded = io.BytesIO()
    Image.new('RGB', (960, 500), '#dce5dc').save(encoded, format='PNG')
    png = encoded.getvalue()
    rendered = []
    def render(_db, kind, identifier):
        selected = read_result(_db, kind, identifier)
        assert map_blocks(selected)[0]['map_snapshot_id'] == snapshot.id
        rendered.append((kind, identifier, selected['content_sha256']))
        return png
    def forbidden(*args, **kwargs):
        pytest.fail('material export must not rerun business analysis')
    monkeypatch.setattr('app.services.business_answer.run_business_answer', forbidden)
    monkeypatch.setattr('app.services.result_map_service.render_material_map', render)
    converted = []
    monkeypatch.setattr(result_document, '_convert_generated_docx', lambda data: converted.append(data) or b'%PDF-synthetic-converter')
    document, word = export_result(db, 'query', run['id'], 'docx')
    pdf_document, pdf = export_result(db, 'query', run['id'], 'pdf')
    direct_document, direct_word = export_query_document(db, run['id'], 'docx')
    assert pdf_document.content_sha256 == document.content_sha256
    assert direct_document == document
    assert pdf.startswith(b'%PDF') and len(converted) == 1
    for data in (word, converted[0], direct_word):
        with ZipFile(io.BytesIO(data)) as archive:
            images = [name for name in archive.namelist() if name.startswith('word/media/') and not name.endswith('/')]
            assert len(images) == 1 and archive.read(images[0]) == png
            assert snapshot.id in archive.read('word/document.xml').decode()
    assert rendered == [('query', run['id'], document.content_sha256)] * 3


@pytest.mark.asyncio
async def test_unknown_map_still_exports_text_without_current_map(query_db, monkeypatch):
    assert frozen_map({'kind': 'query', 'body': {'result': {}}})['state'] == 'not_applicable'
    add_case(query_db, 'NO-KNOWN-LOCATION', discovered_at=datetime(2026, 10, 1))
    query_db.commit()
    run = await execute(query_db, create(query_db, 'recent_changes', {'as_of': AS_OF}))
    def forbidden(*args, **kwargs):
        pytest.fail('missing frozen map must not render the current map')
    monkeypatch.setattr('app.services.result_map_service.render_material_map', forbidden)
    document, data = export_result(query_db, 'query', run['id'], 'docx')
    assert data.startswith(b'PK') and not any(block.kind == 'map' for block in document.blocks)
    assert any(block.text.startswith('地图说明：') for block in document.blocks)


def test_scope_revocation_while_rendering_prevents_document_delivery(answer_material, monkeypatch):
    db, run, _ = answer_material
    encoded = io.BytesIO()
    Image.new('RGB', (960, 500), '#dce5dc').save(encoded, format='PNG')
    def revoke(*args):
        db.query(UserAreaScope).filter_by(user_id=1).delete()
        db.commit()
        return encoded.getvalue()
    monkeypatch.setattr('app.services.result_map_service.render_material_map', revoke)
    with pytest.raises(PermissionError):
        export_result(db, 'query', run['id'], 'docx')
