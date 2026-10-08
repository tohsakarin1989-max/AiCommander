"""Material formatting reuses a frozen body, not a second analysis pipeline."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import io
import json
from urllib.parse import unquote
import zipfile

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

from app.models.deployment_advisor import SituationBrief
from app.services.facility_material_service import freeze_facility
from app.services.result_catalog import read_result
from app.services.result_document import export_result
from app.services.result_presentation import download_filename, present_result
from tests.test_result_materials_v65 import (  # noqa: F401
    material_db, query_db, search_db, saved_case, facility, client,
)


def test_format_does_not_change_frozen_body_or_sources(material_db):
    _, saved = saved_case(material_db)
    material = read_result(material_db, 'case', saved['id'])
    original = deepcopy(material)
    short = present_result(material, 'case_summary')
    assert short['body'] == material['body']
    assert short['sources'] == material['sources']
    assert short['content_sha256'] == material['content_sha256']
    assert material == original
    texts = [block['text'] for block in short['document']['blocks']]
    assert '事实摘要与关联条件' in texts and '待核验候选' in texts and '分析信息缺口' in texts
    assert '案情语义画像与原文引用' not in texts
    assert any('完整资料' in text for text in texts)
    assert present_result(material)['document'] == material['document']
    with pytest.raises(ValueError, match='not_applicable'):
        present_result(material, 'facility_sheet')
    with pytest.raises(ValueError, match='content_changed'):
        present_result(material, 'case_summary', expected_content_sha256='0' * 64)


def test_facility_sheet_distinguishes_restricted_and_partial_examples(material_db):
    asset = facility(material_db)
    row, _ = freeze_facility(material_db, asset.id, idempotency_key='presentation-facility')
    material_db.commit()
    material = read_result(material_db, 'facility', row.id)
    # The formatter receives an already-authorized body, and must still never
    # print data embedded inside a restricted section.
    material['body']['sections']['events'] = {'state': 'restricted', 'total': 99,
        'items': [{'label': 'forbidden-section-text'}]}
    short = present_result(material, 'facility_sheet')
    body = json.dumps(short['document'], ensure_ascii=False)
    assert 'forbidden-section-text' not in body and '匹配总数：99' not in body
    assert '空间邻近（不等于涉案）' in body and '待核验候选关联' in body
    assert '不是单位正式样表' in body and '概要格式' in body
    assert short['content_sha256'] == material['content_sha256']


def test_reader_format_no_writes_and_invalid_or_changed_requests_fail(material_db):
    _, saved = saved_case(material_db)
    writes = []
    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith(('insert', 'update', 'delete')):
            writes.append(statement)
    event.listen(material_db.bind, 'before_cursor_execute', observe)
    try:
        http = client(material_db)
        path = f'/api/results/case/{saved["id"]}'
        answer = http.get(path, params={'template': 'case_summary', 'expected_content_sha256': saved['content_sha256']})
        assert answer.status_code == 200
        assert answer.json()['presentation']['template'] == 'case_summary'
        assert http.get(path, params={'template': 'facility_sheet'}).status_code == 409
        assert http.get(path, params={'template': 'case_summary', 'expected_content_sha256': '0' * 64}).status_code == 409
        assert http.get(path, params={'template': 'invented'}).status_code == 422
        assert client(material_db, authenticated=False).get(path).status_code == 401
    finally:
        event.remove(material_db.bind, 'before_cursor_execute', observe)
    assert writes == []


def test_same_template_page_and_real_word_export_and_business_filename(material_db):
    asset = facility(material_db)
    row, _ = freeze_facility(material_db, asset.id, idempotency_key='presentation-word')
    material_db.commit()
    saved = read_result(material_db, 'facility', row.id)
    displayed = present_result(saved, 'facility_sheet')
    document, data, metadata = export_result(material_db, 'facility', row.id, 'docx',
        template='facility_sheet', expected_content_sha256=row.content_sha256, with_metadata=True)
    assert jsonable_encoder([asdict(block) for block in document.blocks]) == displayed['document']['blocks']
    with zipfile.ZipFile(io.BytesIO(data)) as file:
        xml = file.read('word/document.xml').decode()
    assert '设施资料单' in xml and row.content_sha256 in xml and '空间邻近' in xml
    assert metadata['filename'].startswith('设施材料-') and metadata['filename'].endswith('-设施资料单.docx')
    response = client(material_db).get(f'/api/results/facility/{row.id}/document.docx',
        params={'template': 'facility_sheet', 'expected_content_sha256': row.content_sha256})
    assert response.status_code == 200
    assert response.headers['x-result-template'] == 'facility_sheet'
    assert response.headers['x-result-content-sha256'] == row.content_sha256
    assert unquote(response.headers['content-disposition'].split("filename*=UTF-8''")[1]) == metadata['filename']
    assert client(material_db).get(f'/api/results/facility/{row.id}/document.docx',
        params={'expected_content_sha256': '0' * 64}).status_code == 409


def test_case_summary_export_preserves_fixed_map_contract_without_inventing_map(material_db):
    _, saved = saved_case(material_db)
    document, data = export_result(material_db, 'case', saved['id'], 'docx', template='case_summary')
    assert document.content_sha256 == saved['content_sha256'] and data.startswith(b'PK')
    assert len([block for block in document.blocks if block.kind == 'map']) == 1


def test_filename_escapes_paths_and_control_characters_without_changing_digest():
    name = download_filename({'kind': 'case', 'title': '../测试\r\n:/..',
        'created_at': datetime(2026, 10, 5, tzinfo=timezone.utc), 'content_sha256': 'b' * 64}, 'pdf', 'case_summary')
    assert '\r' not in name and '\n' not in name and '/' not in name and ':' not in name
    assert '-2026-10-05-bbbbbbbb-案件资料摘要.pdf' in name
    with pytest.raises(ValueError):
        download_filename({'kind': 'case'}, 'exe')


def test_period_template_reuses_zero_and_missing_information(material_db):
    case, _ = saved_case(material_db)
    brief = SituationBrief(id='presentation-period', operational_area_id=1, period_type='daily',
        period_start=datetime(2026, 9, 1), period_end=datetime(2026, 9, 2), input_fingerprint='a' * 64,
        status='completed', summary='本期记录为零，资料未齐不等于没有问题',
        comparison_snapshot={'current': {'case_ids': [case.id], 'case_count': 0}, 'previous': {'case_ids': []}},
        evidence_refs=[f'case:{case.id}'], information_gaps=['技防资料未提供'])
    material_db.add(brief)
    material_db.commit()
    saved = read_result(material_db, 'situation', brief.id)
    short = present_result(saved, 'period_brief')
    assert short['body'] == saved['body']
    assert '案件数：0' in str(short['document']) and '技防资料未提供' in str(short['document'])
    assert short['content_sha256'] == saved['content_sha256']
