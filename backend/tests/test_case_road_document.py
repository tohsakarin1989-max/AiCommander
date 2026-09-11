from copy import deepcopy
import io
from zipfile import ZipFile

import pytest
from PIL import Image

from app.models.road_network import RoadAccessMembership
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.case_road_document import decode_road_geometry, load_document_road
from app.services.case_result_document import load_case_result_document
from app.services import case_result_export as exports, case_result_pdf as pdf, case_map_image
from test_case_results import client_for, db_session, result_data, prepare  # noqa: F401
from app.services.case_result_service import CaseResultService
from test_road_network_service import ready  # noqa: F401
from test_case_road_artifacts import artifact_input  # noqa: F401


def save(db, content):
    item = freeze_road_artifact(db, content)
    db.commit()
    return item


def test_append_preserves_original_document_and_requires_matching_source(artifact_input):
    db, content = artifact_input
    item = save(db, content)
    original = load_case_result_document(db, content['result_id'])
    appended = load_case_result_document(db, content['result_id'], item['id'])
    assert appended.blocks[:len(original.blocks)] == original.blocks
    assert appended.content_sha256 == original.content_sha256
    assert appended.road_artifact_sha256 == item['content_sha256']
    assert '不在导出时重新计算' in str(appended.blocks)
    with pytest.raises(ValueError, match='source_mismatch'):
        load_document_road(db, 'other-result', content['content_sha256'], content['map_snapshot_id'], item['id'])
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        load_case_result_document(db, content['result_id'], item['id'])


@pytest.mark.parametrize('encoded', ['', '?', '??A', '\x00??', '~~~~~~~?'])
def test_invalid_geometry_is_rejected(encoded):
    with pytest.raises(ValueError, match='geometry'):
        decode_road_geometry(encoded)


def test_polyline_axes_and_negative_deltas():
    assert decode_road_geometry('??AC') == [[0, 0], [0.000002, 0.000001]]
    assert decode_road_geometry('??@B') == [[0, 0], [-0.000002, -0.000001]]


def image_stub(monkeypatch):
    output = io.BytesIO()
    Image.new('RGB', (960, 700), '#ddeedd').save(output, format='PNG')
    monkeypatch.setattr(case_map_image, 'render_case_map_image', lambda *args, **kwargs: output.getvalue())


def test_http_real_word_contains_saved_attachment_and_hashes(artifact_input, monkeypatch):
    db, content = artifact_input
    content['targets'] = [{'asset_id': 1, 'name': '合成道路目标', 'evidence_ref': 'synthetic:map:1'}]
    content['matrix']['cells'] = [{'source_index': 0, 'target_index': 0, 'status': 'calculated', 'distance_m': 688}]
    item = save(db, content)
    image_stub(monkeypatch)  # Word renderer is real; map imagery is explicitly synthetic here.
    with client_for(db, 'admin') as client:
        response = client.get(f"/api/case-results/{content['result_id']}/document.docx", params={'road_artifact_id': item['id']})
        assert response.status_code == 200, response.text
        assert response.headers['x-road-artifact-sha256'] == item['content_sha256']
        assert response.headers['x-road-artifact-id'] == item['id']
        assert response.headers['x-result-content-sha256'] == content['content_sha256']
        assert response.headers['cache-control'] == 'no-store'
        with ZipFile(io.BytesIO(response.content)) as archive:
            xml = archive.read('word/document.xml').decode()
            assert '道路参考分析（历史留存）' in xml and '0.69 公里' in xml and 'synthetic:map:1' in xml
        db.query(RoadAccessMembership).delete()
        db.commit()
        denied = client.get(f"/api/case-results/{content['result_id']}/document.docx", params={'road_artifact_id': item['id']})
        assert denied.status_code == 404 and '合成道路目标' not in denied.text


@pytest.mark.parametrize('format', ['docx', 'pdf'])
def test_road_revoked_during_render_not_delivered(artifact_input, monkeypatch, format):
    db, content = artifact_input
    item = save(db, content)
    image_stub(monkeypatch)
    def revoke(*args, **kwargs):
        db.query(RoadAccessMembership).delete()
        db.commit()
        return b'private-rendered-bytes'
    if format == 'pdf':
        monkeypatch.setattr(pdf, '_convert_generated_docx', revoke)
    else:
        monkeypatch.setattr(exports, 'render_docx', revoke)
    with client_for(db, 'admin') as client:
        response = client.get(f"/api/case-results/{content['result_id']}/document.{format}", params={'road_artifact_id': item['id']})
        assert response.status_code == 404
        assert b'private-rendered-bytes' not in response.content


def test_map_renderer_receives_only_saved_geometry_and_rechecks_road(artifact_input, monkeypatch):
    db, comparison = artifact_input
    prepare(db)
    source, _ = CaseResultService.create_current(db, 1)
    content = deepcopy(comparison)
    content.update(result_id=source['id'], content_sha256=source['content_sha256'],
                   map_snapshot_id=source['content']['versions']['map_snapshot_id'])
    content['schema_version'] = 'case-road-route-4.2.0-1'
    content['route'] = {**content.pop('matrix'), 'shape_polyline6': '??AC', 'distance_m': 1}
    content['route']['alternatives'] = [{'shape_polyline6': '??EG', 'distance_m': 120,
        'reference_time_seconds': 30, 'way_ids': [1, 2], 'detour_reference': {
            'status': 'available', 'basis': 'route_geometry_endpoints', 'ratio': 2,
            'straight_distance_m': 60, 'additional_distance_m': 60}}]
    content['target'] = {'asset_id': 1, 'name': '合成目标'}
    item = save(db, content)
    document = load_case_result_document(db, content['result_id'], item['id'])
    assert any(block.text == '留存备选路径1' for block in document.blocks)
    assert any(block.text == '备选路径1绕行参考' for block in document.blocks)
    monkeypatch.setattr(case_map_image, 'load_result_map_context', lambda *args: {
        'result_id': content['result_id'], 'content_sha256': content['content_sha256'],
        'map': {'map_snapshot_id': content['map_snapshot_id']}, 'basemap': {'version': 'synthetic'}})
    seen = []
    def render(db, context, resources):
        seen.append(context)
        db.query(RoadAccessMembership).delete()
        db.commit()
        return b'not-deliverable'
    monkeypatch.setattr(case_map_image, '_render', render)
    with pytest.raises(PermissionError):
        case_map_image.render_case_map_image(db, content['result_id'], road_artifact_id=item['id'])
    assert seen[0]['reference_path'] == [[0, 0], [0.000002, 0.000001]]
    assert seen[0]['reference_alternatives'] == [[[0, 0], [0.000004, 0.000003]]]
