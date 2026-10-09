"""Retain received bytes as internal source evidence, never infer an original workbook."""
import hashlib
from app.models.case_import import CaseImportRow
from app.models.case_source import EvidenceObject, SourceReference
from app.services.case_source_service import CaseSourceService


def preserve_received_input(db, batch, content, input_method='file', *, source_context=None):
    evidence = EvidenceObject(storage_key=f'case-import/{batch.id}',
        sha256=hashlib.sha256(content).hexdigest(), media_type='text/plain' if input_method == 'clipboard' else 'application/octet-stream',
        sensitivity='internal', availability='available', content=content)
    db.add(evidence)
    db.flush()
    attach_received_rows(db, batch, evidence=evidence, input_method=input_method, source_context=source_context)
    return evidence.id


def attach_received_rows(db, batch, *, evidence=None, input_method=None, source_context=None):
    """Also attach rows that succeed on retry, using the unchanged received bytes."""
    if evidence is None:
        evidence = db.query(EvidenceObject).filter_by(storage_key=f'case-import/{batch.id}').one_or_none()
    if evidence is None:
        return
    input_method = input_method or (batch.result or {}).get('input_method', 'file')
    existing = {(reference.case_id, reference.locator.get('row')) for reference in
                db.query(SourceReference).filter_by(evidence_object_id=evidence.id).all()}
    for row in db.query(CaseImportRow).filter_by(batch_id=batch.id).all():
        if row.case_id and row.status in {'created', 'updated', 'unchanged'} and (row.case_id, row.row_number) not in existing:
            latest = CaseSourceService.latest_revision(db, row.case_id)
            locator = {'batch_id': batch.id, 'row': row.row_number, 'input_method': input_method,
                       'source_status': row.status,
                       'provenance': '用户声明人工粘贴，非原始工作簿' if input_method == 'clipboard' else '收到的上传字节'}
            if row.source_values.get('_import_provenance'):
                locator['import_source'] = row.source_values['_import_provenance']
            if source_context is not None:
                locator.update(source_key=source_context['source_key'],
                    source_version=source_context['source_version'],
                    external_record_key=str(row.source_values.get('external_record_key') or '').strip())
            db.add(SourceReference(case_id=row.case_id, source_revision_id=latest.id if latest else None,
                evidence_object_id=evidence.id, kind='manual_paste' if input_method == 'clipboard' else 'source_import',
                locator=locator))
