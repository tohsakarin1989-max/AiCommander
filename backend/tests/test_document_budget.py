import pytest
from types import SimpleNamespace

from app.services import document_budget as budget
from app.services.case_result_export import CaseResultExportError


def test_nested_stages_share_deadline_and_reset_after_return(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(budget, 'monotonic', lambda: clock[0])

    @budget.document_budget
    def inner():
        return budget.remaining_seconds(45)

    @budget.document_budget
    def outer():
        clock[0] = 110
        assert inner() == 10

    outer()
    assert budget.remaining_seconds(45) == 45


def test_expired_result_not_delivered_and_context_reset(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(budget, 'monotonic', lambda: clock[0])

    @budget.document_budget
    def late():
        clock[0] = 121
        return b'should not be delivered'

    with pytest.raises(CaseResultExportError, match='renderer_timeout'):
        late()
    assert budget.remaining_seconds(20) == 20


def test_pdf_conversion_gets_only_remaining_budget(monkeypatch):
    from app.services import case_result_pdf as pdf
    clock = [0.0]
    monkeypatch.setattr(budget, 'monotonic', lambda: clock[0])
    document = SimpleNamespace(content_sha256='same-version')

    def docx(*args):
        clock[0] = 110
        return document, b'PK'

    def convert(data):
        assert budget.remaining_seconds(pdf.TIMEOUT_SECONDS) == 10
        return b'%PDF'

    monkeypatch.setattr(pdf, 'export_case_result_docx', docx)
    monkeypatch.setattr(pdf, '_convert_generated_docx', convert)
    monkeypatch.setattr(pdf, 'load_case_result_document', lambda *args: document)
    assert pdf.export_case_result_pdf(None, 'test')[1] == b'%PDF'
