"""Render the same typed frozen reader document; never reanalyse or refresh."""
from app.services.case_result_export import render_docx, export_case_result_docx
from app.services.case_result_pdf import export_case_result_pdf, _convert_generated_docx
from app.services.document_budget import document_budget
from app.services.intelligent_query_tasks import _identity
from app.services.result_catalog import _read
from app.services.result_presentation import download_filename, format_document


@document_budget
def export_result(db, kind, identifier, format, *, template='full', expected_content_sha256=None, with_metadata=False):
    if format not in {'docx', 'pdf'}:
        raise ValueError('invalid_document_format')
    _identity(db)
    before, document = _read(db, kind, identifier, topic_document_preview=False)
    if expected_content_sha256 and before['content_sha256'] != expected_content_sha256:
        raise ValueError('material_content_changed')
    document = format_document(before, document, template)
    if kind == 'case' and template == 'full':
        exporter = export_case_result_pdf if format == 'pdf' else export_case_result_docx
        document, data = exporter(db, identifier)
    else:
        image = None
        if any(block.kind == 'map' for block in document.blocks):
            import json
            from app.services.case_map_image import CaseMapImageError
            from app.services.case_result_export import CaseResultExportError
            try:
                if kind == 'case':
                    from app.services.case_map_image import render_case_map_image
                    if any(json.loads(block.text).get('map_snapshot_id') for block in document.blocks if block.kind == 'map'):
                        image = render_case_map_image(db, identifier)
                else:
                    from app.services.result_map_service import render_material_map
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
    if with_metadata:
        return document, data, {'filename': download_filename(before, format, template), 'template': template}
    return document, data
