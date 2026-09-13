from copy import deepcopy
import hashlib
import io
import json
import os
from zipfile import ZipFile

import pytest
from PIL import Image

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, MapSnapshot
from app.models.road_network import RoadAccessMembership
from app.services.case_facility_comparison import compare_case_facilities
from app.services.case_result_document import load_case_result_document
from app.services.case_result_export import render_docx
from app.services.case_result_map import load_result_map_context
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.facility_document_map import facility_map_input, resolve_facility_map_input
from test_case_facility_comparison import prepared, VEHICLE  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_road_access_policy import AT
from test_offline_maps import _mbtiles_bytes


@pytest.fixture
def comparison(prepared, tmp_path):
    db, source, _ = prepared
    content = compare_case_facilities(db, result_id=source['id'], network_id='graph-1',
        analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path)
    artifact = freeze_road_artifact(db, content)
    db.commit()
    return db, source, content, artifact


def test_composite_report_and_renderer_share_frozen_ranked_entrances(comparison):
    db, source, content, artifact = comparison
    original = load_case_result_document(db, source['id'])
    document = load_case_result_document(db, source['id'], artifact['id'])
    maps = [json.loads(block.text) for block in document.blocks if block.kind == 'map']
    assert len(maps) == 1
    spec = resolve_facility_map_input(db, {'content': content, **artifact}, case_id=1)
    assert maps[0] == spec
    assert spec['candidates'] == []
    assert spec['production_asset_ids'] == [row['asset_id'] for row in content['result']['candidates']]
    for candidate, point in zip(content['result']['candidates'], spec['reference_points'], strict=True):
        expected = content['pool']['entrances'][str(candidate['asset_id'])][candidate['selected_entry_index']]
        assert point['latitude'] == expected['latitude'] and point['longitude'] == expected['longitude']
        assert point['rank'] == candidate['rank']
    assert '原空间分析候选（历史参考' in str(document.blocks)
    assert load_case_result_document(db, source['id']) == original
    context = load_result_map_context(db, source['id'], map_spec=spec)
    assert context['map'] == spec
    assert len(context['production']['features']) == 3


@pytest.mark.parametrize('change', ['missing', 'wrong_index', 'wrong_coordinate', 'invalid_origin', 'duplicate'])
def test_invalid_frozen_entrances_do_not_fall_back_to_original_map(comparison, change):
    _, _, original, _ = comparison
    content = deepcopy(original)
    candidate = content['result']['candidates'][0]
    asset = str(candidate['asset_id'])
    if change == 'missing':
        del content['pool']['entrances'][asset]
    elif change == 'wrong_index':
        candidate['selected_entry_index'] = 999
    elif change == 'wrong_coordinate':
        content['pool']['entrances'][asset][0]['latitude'] = 0
    elif change == 'invalid_origin':
        content['pool']['origin']['latitude'] = True
    else:
        content['result']['candidates'][1]['asset_id'] = candidate['asset_id']
    with pytest.raises(ValueError):
        facility_map_input(content, case_id=1)


def test_docx_uses_new_figure_caption_and_rejects_cross_attachment(comparison):
    db, source, _, artifact = comparison
    document = load_case_result_document(db, source['id'], artifact['id'])
    buffer = io.BytesIO()
    Image.new('RGB', (960, 700), '#dce9db').save(buffer, format='PNG')
    # Real Word packaging; this test deliberately does not claim real imagery.
    data = render_docx(document, map_image=buffer.getvalue())
    with ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read('word/document.xml').decode()
    assert '道路候选冻结入口图' in xml and '编号与道路候选一致' in xml
    assert '原空间分析候选（历史参考' in xml
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        load_case_result_document(db, source['id'], artifact['id'])


def test_map_image_is_not_delivered_after_road_permission_revocation(comparison, monkeypatch):
    from app.services import case_map_image
    db, source, _, artifact = comparison
    def render(session, context, resources):
        assert context['map']['schema'] == 'case-facility-map-5.2-1'
        session.query(RoadAccessMembership).delete()
        session.commit()
        return b'private-image-must-not-be-delivered'
    monkeypatch.setattr(case_map_image, '_render', render)
    with pytest.raises(PermissionError):
        case_map_image.render_case_map_image(db, source['id'], road_artifact_id=artifact['id'])


@pytest.mark.skipif(os.environ.get('AIC_TEST_FACILITY_MAP_BROWSER') != '1', reason='explicit real browser rendering')
def test_real_browser_and_word_render_selected_entrance_map(comparison, tmp_path, monkeypatch):
    from playwright.sync_api import BrowserType, Page
    from app.services.case_map_image import render_case_map_image
    from app.services.case_result_export import export_case_result_docx

    db, source, content, artifact = comparison
    # Reuse installed Chrome on this macOS check. Production Chromium is a
    # separate deployment dependency, not claimed verified by this test.
    launch = BrowserType.launch
    monkeypatch.setattr(BrowserType, 'launch', lambda self, **kwargs: launch(self, channel='chrome', **kwargs))
    screenshot = Page.screenshot
    def capture(page, **kwargs):
        assert page.locator('.maplibregl-marker').all_text_contents() == ['1', '2', '3']
        legend = page.locator('#legend').inner_text()
        assert '合成设施13（可信入口）' in legend and '橙色' not in legend
        return screenshot(page, **kwargs)
    monkeypatch.setattr(Page, 'screenshot', capture)
    monkeypatch.setattr(settings, 'MAP_PACKAGE_ROOT', str(tmp_path))
    buffer = io.BytesIO()
    Image.new('RGB', (256, 256), '#dce9db').save(buffer, format='PNG')
    bounds = [-180, -85, 180, 85]
    payload = _mbtiles_bytes(tmp_path, buffer.getvalue(), tile_coordinate=(0, 0, 0), bounds=bounds)
    path = tmp_path / 'synthetic.mbtiles'
    path.write_bytes(payload)
    db.add(MapPackageArtifact(public_bundle_id=1, artifact_kind='mbtiles', storage_key=path.name,
        sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)))
    db.get(MapSnapshot, 'map-1').manifest = {'min_zoom': 0, 'max_zoom': 0, 'bounds': bounds}
    db.commit()
    image = render_case_map_image(db, source['id'], road_artifact_id=artifact['id'])
    (tmp_path / 'facility.png').write_bytes(image)
    assert Image.open(io.BytesIO(image)).width == 960
    document, data = export_case_result_docx(db, source['id'], road_artifact_id=artifact['id'])
    (tmp_path / 'facility.docx').write_bytes(data)
    with ZipFile(io.BytesIO(data)) as archive:
        assert any(name.startswith('word/media/') for name in archive.namelist())
        assert '道路候选冻结入口图' in archive.read('word/document.xml').decode()
    print(f'facility_map_render_artifacts={tmp_path}')
