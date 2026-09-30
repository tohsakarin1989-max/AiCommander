"""One frozen source for screen PNG and embedded Word map, with local tiles."""
import hashlib
import io
import math
import os
from zipfile import ZipFile

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.models.map_foundation import PublicMapBundle, MapPackageArtifact, MapSnapshot
from app.services.facility_material_service import freeze_facility
from app.services.result_catalog import read_result
from app.services.result_document import export_result
from app.services.result_map_service import frozen_map, map_context
from tests.test_result_materials_v65 import material_db, query_db, search_db, facility, client  # noqa: F401
from tests.test_offline_maps import _mbtiles_bytes


def test_unknown_basemap_is_explicit_not_current_fallback(material_db):
    row, _ = freeze_facility(material_db, facility(material_db).id, idempotency_key='no-map-reference')
    material_db.commit()
    result = read_result(material_db, 'facility', row.id)
    assert result['map']['state'] == 'unavailable'
    assert not any(item['kind'] == 'map' for item in result['document']['blocks'])
    with pytest.raises(ValueError, match='material_map_unavailable'):
        map_context(material_db, 'facility', row.id)


def test_topic_map_keeps_frozen_first_page_and_exact_map_version():
    envelope = {'kind': 'topic', 'body': {'views': {'map': {'points': [
        {'case_id': 10, 'longitude': 125.1, 'latitude': 46.6}],
        'versions': [{'id': 'fixed-map'}], 'unmapped_in_page': 2}}}}
    result = frozen_map(envelope)
    assert result['map_snapshot_id'] == 'fixed-map' and result['point_count'] == 1
    assert result['points'][0]['label'] == '案件 #10'
    assert any('首 100' in text for text in result['warnings'])
    envelope['body']['views']['map']['versions'].append({'id': 'other-map'})
    assert frozen_map(envelope)['state'] == 'unavailable'


@pytest.mark.skipif(os.environ.get('AIC_TEST_MAP_BROWSER') != '1', reason='explicit real browser rendering only')
def test_real_local_map_image_word_and_authenticated_png(material_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MAP_PACKAGE_ROOT', str(tmp_path))
    tile = Image.new('RGB', (256, 256), '#d5e3d0')
    draw = ImageDraw.Draw(tile)
    draw.line([(0, 82), (256, 82)], fill='#ffffff', width=5)
    draw.line([(128, 0), (128, 256)], fill='#7299bb', width=8)
    data = io.BytesIO()
    tile.save(data, format='PNG')
    bounds = [3471 / 4096 * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 1448 / 4096)))),
        3472 / 4096 * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 1447 / 4096))))]
    payload = _mbtiles_bytes(tmp_path, data.getvalue(), tile_coordinate=(12, 3471, 2648), bounds=bounds)
    path = tmp_path / 'synthetic-material.mbtiles'
    path.write_bytes(payload)
    material_db.add(PublicMapBundle(id=1, bundle_id='material-test', provider='synthetic', source_version='1',
        license_record='test', bounds=bounds, manifest={}, package_hash='test'))
    material_db.flush()
    material_db.add(MapPackageArtifact(public_bundle_id=1, artifact_kind='mbtiles', storage_key=path.name,
        sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)))
    material_db.add(MapSnapshot(id='material-map', version='synthetic-fixed', operational_area_id=1,
        public_bundle_id=1, status='current', feature_watermark='1',
        manifest={'min_zoom': 12, 'max_zoom': 12, 'bounds': bounds}))
    asset = facility(material_db)
    asset.longitude = 125.1
    material_db.commit()
    row, _ = freeze_facility(material_db, asset.id, idempotency_key='real-map-material')
    material_db.commit()
    saved = read_result(material_db, 'facility', row.id)
    assert saved['map']['state'] == 'available'
    assert saved['map']['map_snapshot_id'] == 'material-map'
    document, word = export_result(material_db, 'facility', row.id, 'docx')
    with ZipFile(io.BytesIO(word)) as archive:
        names = [name for name in archive.namelist() if name.startswith('word/media/') and not name.endswith('/')]
        assert len(names) == 1
        image = archive.read(names[0])
        assert 'material-map' in archive.read('word/document.xml').decode()
        assert 'TargetMode="External"' not in archive.read('word/_rels/document.xml.rels').decode()
    bitmap = Image.open(io.BytesIO(image)).convert('RGB')
    colors = bitmap.getcolors(bitmap.width * bitmap.height)
    assert bitmap.width == 960 and bitmap.height >= 500
    assert any(count > 10000 and color == (213, 227, 208) for count, color in colors)
    assert any(count > 30 and color == (3, 105, 161) for count, color in colors)
    # Delivery contract uses that same actual rendered output, not an unrelated screenshot.
    monkeypatch.setattr('app.services.result_map_service.render_material_map', lambda *args: image)
    with client(material_db) as http:
        response = http.get(f'/api/results/facility/{row.id}/map.png')
        assert response.status_code == 200 and response.content == image
        assert response.headers['x-result-content-sha256'] == document.content_sha256
    snapshot = material_db.query(MapSnapshot).filter_by(id='material-map').one()
    snapshot.manifest = {**snapshot.manifest, 'min_zoom': 11}
    material_db.commit()
    with pytest.raises(PermissionError, match='facility_material_map_changed'):
        read_result(material_db, 'facility', row.id)
