"""User output configuration projects authorized facts; it never rewrites them."""
from copy import deepcopy
from dataclasses import asdict

import pytest
from fastapi.encoders import jsonable_encoder

from app.services.case_table_export import ledger_snapshot
from app.services.result_presentation import present_result
from app.services.result_document import export_result
from tests.test_result_materials_v65 import material_db, query_db, saved_case  # noqa: F401
from test_case_search_page import search_db, add_case  # noqa: F401


def test_ledger_column_mapping_preserves_identity_units_and_formula_safety(search_db):
    add_case(search_db, '00012', oil_volume=0, oil_volume_unit='ton')
    search_db.commit()
    config = {'columns': [{'key': 'case_number', 'label': '本单位记录号'},
                          {'key': 'oil_volume', 'label': '登记数量'},
                          {'key': 'oil_volume_unit', 'label': '登记单位'}]}
    saved = ledger_snapshot(search_db, output_configuration=config)
    assert saved['columns'] == ['本单位记录号', '登记数量', '登记单位']
    assert saved['rows'] == [['00012', 0, 'ton']]
    assert '不是单位正式样表' in saved['boundary']
    for invalid in [
        {'columns': [{'key': 'description', 'label': '经过'}]},
        {'columns': [{'key': 'case_number', 'label': '编号'}, {'key': 'oil_volume', 'label': '数量'}]},
        {'columns': [{'key': 'case_number', 'label': '=编号'}]},
        {'columns': [{'key': 'case_number', 'label': '编号'}, {'key': 'phone', 'label': '电话'}]},
    ]:
        with pytest.raises(ValueError):
            ledger_snapshot(search_db, output_configuration=invalid)


def test_controlled_sections_keep_mandatory_evidence_and_same_word_body(material_db):
    _, saved = saved_case(material_db)
    from app.services.result_catalog import read_result
    original = read_result(material_db, 'case', saved['id'])
    unchanged = deepcopy(original)
    sections = ['evidence', 'differences', 'gaps', 'boundary']
    shown = present_result(original, sections=sections)
    text = str(shown['document'])
    assert '事实摘要与关联条件' not in text
    assert '版本与适用边界' in text and saved['content_sha256'] in text
    assert shown['sources'] == original['sources']
    assert shown['body'] == original['body'] and original == unchanged
    assert shown['presentation']['sections'] == sections
    document, data, metadata = export_result(material_db, 'case', saved['id'], 'docx',
                                            sections=sections, with_metadata=True)
    assert jsonable_encoder([asdict(block) for block in document.blocks]) == shown['document']['blocks']
    assert data.startswith(b'PK')
    assert metadata['sections'] == sections
    with pytest.raises(ValueError):
        present_result(original, sections=['arbitrary'])


def test_excluding_evidence_or_gaps_cannot_remove_candidate_qualifications(material_db):
    _, saved = saved_case(material_db)
    from app.services.result_catalog import read_result
    original = read_result(material_db, 'case', saved['id'])
    shown = present_result(original, sections=['facts'])
    text = str(shown['document'])
    assert '分析信息缺口' in text and '版本与适用边界' in text
    assert shown['sources'] == original['sources']
    assert '必要' in shown['presentation']['sections_boundary']


def test_scope_templates_are_immutable_and_revocation_is_checked(material_db):
    from app.services import output_template_service as service
    from app.models.map_foundation import UserAreaScope
    from app.models.user import User
    from app.database import AreaWriteAccessError
    config = {'sections': ['facts', 'boundary']}
    row = service.save_template(material_db, kind='material_sections', name='简要资料',
                                configuration=config, operational_area_id=1)
    material_db.commit()
    assert service.read_template(material_db, row['id'], 'material_sections')['configuration'] == config
    assert len(service.list_templates(material_db, 'material_sections')) == 1
    with pytest.raises(AreaWriteAccessError):
        service.save_template(material_db, kind='material_sections', name='跨域',
                              configuration=config, operational_area_id=2)
    material_db.get(User, 1).role = 'viewer'
    material_db.commit()
    with pytest.raises(PermissionError):
        service.save_template(material_db, kind='material_sections', name='只读写入',
                              configuration=config, operational_area_id=1)
    material_db.query(UserAreaScope).filter_by(user_id=1).delete()
    material_db.commit()
    assert service.list_templates(material_db, 'material_sections') == []
    with pytest.raises(PermissionError):
        service.read_template(material_db, row['id'], 'material_sections')


def test_output_template_api_and_direct_column_configuration(material_db):
    import json
    from tests.test_case_table_export import client_for
    saved_case(material_db)
    http = client_for(material_db)
    config = {'columns': [{'key': 'case_number', 'label': '编号'}]}
    response = http.post('/api/case-exports/templates', json={
        'name': '通用明细', 'kind': 'case_ledger', 'operational_area_id': 1, 'configuration': config})
    assert response.status_code == 201
    saved = response.json()
    assert saved['configuration'] == config and '未经过单位' in saved['boundary']
    assert http.get('/api/case-exports/templates').json()[0]['id'] == saved['id']
    exported = http.get('/api/case-exports/ledger.csv', params={'output_template_id': saved['id']})
    assert exported.status_code == 200 and '\r\n编号\r\n' in exported.text
    assert http.get('/api/case-exports/ledger.csv', params={'output_configuration': json.dumps(config)}).status_code == 200
    assert http.get('/api/case-exports/ledger.csv', params={'output_configuration': '{malformed'}).status_code == 422
    assert http.post('/api/case-exports/templates', json={**saved, 'configuration': {'sql': 'select *'}}).status_code == 422
    assert client_for(material_db, False).get('/api/case-exports/templates').status_code == 401


def test_sections_api_page_word_and_real_pdf_share_projection(material_db):
    from tests.test_result_materials_v65 import client
    _, saved = saved_case(material_db)
    http = client(material_db)
    params = [('sections', 'facts'), ('sections', 'boundary')]
    path = f'/api/results/case/{saved["id"]}'
    page = http.get(path, params=params)
    assert page.status_code == 200
    assert page.json()['presentation']['sections_customized']
    assert http.get(path, params={'sections': 'bad'}).status_code == 409
    word = http.get(path + '/document.docx', params=params)
    assert word.status_code == 200 and word.headers['x-result-sections'] == 'facts,boundary'
    import shutil
    if shutil.which('soffice'):
        pdf = http.get(path + '/document.pdf', params=params)
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
        assert pdf.headers['x-result-sections'] == 'facts,boundary'


def test_period_change_chapter_uses_only_saved_categories_and_preserves_time():
    from app.services.result_presentation import format_document
    from app.services.case_result_document import CaseResultDocument, DocumentBlock
    document = CaseResultDocument('business-result-document-6.5-1', 'p', 'a' * 64,
        (DocumentBlock('heading', '周期摘要'), DocumentBlock('paragraph', '摘要'),
         DocumentBlock('table', '统计口径', (('周期', '冻结周期'),))))
    result = {'kind': 'situation', 'id': 'p', 'content_sha256': 'a' * 64, 'created_at': '2026-10-09',
              'body': {'comparison_snapshot': {'change_origins': {'late_entry': {'count': 2, 'case_ids': [1, 2], 'label': '本期补录的历史情况'}}}}, 'boundary': []}
    shown = format_document(result, document, sections=['differences', 'boundary'])
    value = str(shown)
    assert '冻结周期' in value and '本期补录的历史情况' in value
    assert '未冻结分类依据' in value and '不能补算' in value
    assert '2' in value
