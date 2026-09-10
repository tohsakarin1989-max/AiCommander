from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import case_imports, cases
from app.database import get_db
from test_case_search_page import search_db  # noqa: F401


def client_for(db):
    app = FastAPI()
    app.include_router(case_imports.router, prefix="/api/case-imports")
    app.include_router(cases.router, prefix="/api/cases")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_inspection_exposes_headers_not_case_text_and_saved_template_is_scoped(search_db):
    search_db.info.update(authorized_area_ids=(1,), area_access_levels={1: "write"}, default_operational_area_id=1)
    with client_for(search_db) as client:
        inspected = client.post('/api/case-imports/inspect', files={'file': ('sample.csv',
            '日期,内容,备注\n2026-09-10,不要出现在列名预览中的原文,内部说明\n'.encode())})
        assert inspected.status_code == 200
        assert inspected.json()['headers'] == ['日期', '内容', '备注']
        assert '内部说明' not in inspected.text
        assert '原文' not in inspected.text
        payload = {'name': '生产台账', 'operational_area_id': 1, 'settings': {
            'header_row': 1, 'time_zone': 'Asia/Shanghai',
            'field_mapping': {'日期': 'occurred_time', '内容': 'description', '备注': None}}}
        saved = client.post('/api/case-imports/templates', json=payload)
        assert saved.status_code == 201
        assert saved.json()['settings']['field_mapping']['备注'] is None
        assert len(client.get('/api/case-imports/templates').json()) == 1
        search_db.info['authorized_area_ids'] = (2,)
        assert client.get('/api/case-imports/templates').json() == []


def test_templates_reject_arbitrary_settings_and_read_only_write(search_db):
    with client_for(search_db) as client:
        for settings in ({'time_zone': 'Mars'}, {'header_row': 0}, {'field_mapping': {'x': 'commit'}},
                         {'field_mapping': {'x': 'description', 'y': 'description'}}, {'shell': 'no'}):
            result = client.post('/api/case-imports/templates', json={'name': 'invalid', 'settings': settings})
            assert result.status_code == 422
        search_db.info.update(authorized_area_ids=(1,), area_access_levels={1: 'read'}, default_operational_area_id=1)
        from app.database import AreaWriteAccessError
        import pytest
        with pytest.raises(AreaWriteAccessError):
            client.post('/api/case-imports/templates', json={'name': 'readonly', 'operational_area_id': 1, 'settings': {}})


def test_explicit_ignored_alias_does_not_conflict_with_custom_mapping(search_db):
    import json
    with client_for(search_db) as client:
        response = client.post('/api/cases/import', params={'dry_run': True, 'field_mapping': json.dumps({
            '日期': 'occurred_time', '内容': 'description', '案情描述': None})}, files={'file': ('a.csv',
                '日期,内容,案情描述\n2026-09-10,应导入,不应导入\n'.encode())})
        assert response.status_code == 200
        assert response.json()['valid'] == 1
        assert response.json()['preview'][0]['description'] == '应导入'


def test_workbook_cover_sheet_still_exposes_worksheet_directory(search_db):
    import io
    import openpyxl
    book = openpyxl.Workbook()
    book.active.title = '说明'
    book.active.append(['请使用案件表'])
    sheet = book.create_sheet('案件')
    sheet.append(['案发时间', '案情描述'])
    sheet.append(['2026-09-10', '合成案件'])
    data = io.BytesIO()
    book.save(data)
    book.close()
    with client_for(search_db) as client:
        result = client.post('/api/case-imports/inspect', files={'file': ('a.xlsx', data.getvalue())})
        assert result.status_code == 200
        assert result.json()['worksheets'] == ['说明', '案件']
        assert result.json()['total'] == 0
        assert client.post('/api/cases/import', files={'file': ('a.xlsx', data.getvalue())}).status_code == 400
