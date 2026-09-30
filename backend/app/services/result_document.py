"""Render the same typed frozen reader document; never reanalyse or refresh."""
from app.services.case_result_export import render_docx, export_case_result_docx
from app.services.case_result_pdf import export_case_result_pdf, _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_tasks import _identity
from app.services.result_catalog import _read


@document_budget
def export_result(db, kind, identifier, format):
    if format not in {'docx', 'pdf'}:
        raise ValueError('invalid_document_format')
    _identity(db)
    before, document = _read(db, kind, identifier, topic_document_preview=False)
    if kind == 'case':
        exporter = export_case_result_pdf if format == 'pdf' else export_case_result_docx
        document, data = exporter(db, identifier)
    else:
        image = None
        if any(block.kind == 'map' for block in document.blocks):
            from app.services.result_map_service import render_material_map
            from app.services.case_map_image import CaseMapImageError
            from app.services.case_result_export import CaseResultExportError
            try:
                image = render_material_map(db, kind, identifier)
            except CaseMapImageError:
                raise CaseResultExportError('map_rendering_not_ready') from None
        data = render_docx(document, map_image=image)
        if format == 'pdf':
            data = _convert_generated_docx(data)
    db.expire_all()
    _identity(db)
    after, _ = _read(db, kind, identifier)
    if before['content_sha256'] != after['content_sha256']:
        raise PermissionError('document_source_changed')
    return document, data
