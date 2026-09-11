import io
import zipfile
import shutil

import pytest

from app.models.agent_run import AgentRun
from app.services import intelligent_query_document as documents
from app.services import intelligent_query_tasks as tasks
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_query_followup import model_for, call, FINISH


@pytest.mark.asyncio
@pytest.mark.skipif(not shutil.which('soffice'), reason='PDF runtime not installed')
async def test_real_pdf_from_frozen_query(query_db):
    task = tasks.create_query(query_db, '统计当前案件')
    await tasks.execute_query(query_db, task['id'], model=model_for(call('count_cases', {}), FINISH))
    document, data = documents.export_query_document(query_db, task['id'], 'pdf')
    assert document.result_id == task['id']
    assert data.startswith(b'%PDF-') and b'%%EOF' in data[-1024:]


@pytest.mark.asyncio
async def test_real_docx_preserves_zero_and_frozen_query(query_db):
    task = tasks.create_query(query_db, '统计没有匹配的案件')
    await tasks.execute_query(query_db, task['id'], model=model_for(call('count_cases', {}), FINISH))
    document, data = documents.export_query_document(query_db, task['id'], 'docx')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        text = archive.read('word/document.xml').decode()
    assert '匹配案件数' in text and '>0<' in text
    assert '统计没有匹配的案件' in text
    assert document.content_sha256 in text
    assert '历史快照' in text


@pytest.mark.asyncio
async def test_export_denies_changed_result_after_render(query_db, monkeypatch):
    task = tasks.create_query(query_db, '统计')
    await tasks.execute_query(query_db, task['id'], model=model_for(call('count_cases', {}), FINISH))
    def changed(document):
        row = query_db.get(AgentRun, task['id'])
        row.result_summary = {'cards': [{'data': {'count': 999}}]}
        query_db.commit()
        return b'PK fake renderer output'
    monkeypatch.setattr(documents, 'render_docx', changed)
    with pytest.raises(PermissionError, match='query_document_changed'):
        documents.export_query_document(query_db, task['id'], 'docx')


def test_export_rejects_unfinished_or_other_owner(query_db):
    task = tasks.create_query(query_db, '统计')
    with pytest.raises(ValueError, match='query_document_not_ready'):
        documents.export_query_document(query_db, task['id'], 'docx')
    query_db.info['principal_user_id'] = 2
    with pytest.raises(ValueError, match='query_not_found'):
        documents.export_query_document(query_db, task['id'], 'docx')


@pytest.mark.asyncio
async def test_export_rechecks_scope_after_render(query_db, monkeypatch):
    from app.models.map_foundation import UserAreaScope
    task = tasks.create_query(query_db, '统计')
    await tasks.execute_query(query_db, task['id'], model=model_for(call('count_cases', {}), FINISH))
    def revoked(document):
        query_db.query(UserAreaScope).filter_by(user_id=1).delete()
        query_db.commit()
        return b'PK'
    monkeypatch.setattr(documents, 'render_docx', revoked)
    with pytest.raises(PermissionError):
        documents.export_query_document(query_db, task['id'], 'docx')
