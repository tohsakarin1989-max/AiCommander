from copy import deepcopy
from datetime import datetime
import pytest

from app.models.case import Case
from app.models.case_import import CaseImportSourceRecord
from app.models.case_source import EvidenceObject, SourceReference
from app.services.case_import_table import parse_case_table
from app.services.case_source_import import import_source_table
from app.services.case_service import CaseService
from test_case_search_page import search_db


def run(db, text, version='1', dry=False, source='台账A'):
    content = text.encode()
    table = parse_case_table('test.csv', content)
    return import_source_table(db, table=table, content=content, area_id=1,
        source_key=source, source_revision=version, time_zone='Asia/Shanghai', dry_run=dry)


HEADER = '源记录键,发现时间,地点,简要案情,油品类型\n'
ROW = 'K01,2026-10-08,路口,现场发现,原油\n'


def test_source_reorder_repeat_and_safe_update(search_db):
    first = run(search_db, HEADER + ROW)
    assert first['created'] == 1
    assert search_db.query(Case).count() == 1
    assert search_db.query(EvidenceObject).one().content == (HEADER + ROW).encode()
    replay = run(search_db, HEADER + ROW)
    assert replay['replayed'] and replay['created'] == 0
    reordered = '简要案情,地点,发现时间,源记录键,油品类型,备注\n现场发现,路口,2026-10-08,K01,原油,新增备注\n'
    assert run(search_db, reordered, '2')['unchanged'] == 1
    changed = (HEADER + ROW).replace('原油', '柴油')
    preview = run(search_db, changed, '3', True)
    assert preview['preview'][0]['action'] == 'updated'
    assert search_db.query(Case).one().oil_type == '原油'
    result = run(search_db, changed, '3')
    assert result['updated'] == 1
    assert search_db.query(Case).one().oil_type == '柴油'
    assert search_db.query(Case).count() == 1
    assert search_db.query(SourceReference).count() == 3


def test_unchanged_new_source_version_keeps_complete_audit_without_case_work(search_db):
    from app.models.case_import import CaseImportBatch, CaseImportRow
    from app.models.case_pipeline import OutboxEvent
    from app.models.case_source import CaseRevision, DomainChange
    from app.services.case_source_service import CaseSourceService
    original = HEADER + ROW + ROW.replace('K01', 'K02')
    first = run(search_db, original, '来源第一版')
    records = {record.external_key: record for record in search_db.query(CaseImportSourceRecord)}
    prior = {key: {'revision': record.revision, 'source_hash': record.source_hash,
                   'adopted': deepcopy(record.adopted_values)} for key, record in records.items()}
    facts = {case.id: deepcopy(CaseSourceService.source_payload(search_db, case))
             for case in search_db.query(Case)}
    counts = {model: search_db.query(model).count() for model in (CaseRevision, DomainChange)}
    case_jobs = search_db.query(OutboxEvent).filter_by(event_type='case.analysis.requested').count()
    reordered = HEADER + ROW.replace('K01', 'K02') + ROW
    second = run(search_db, reordered, '来源第二版')
    assert second['unchanged'] == 2 and second['created'] == second['updated'] == 0
    assert second['batch_id'] != first['batch_id']
    for key, row_number in (('K02', 2), ('K01', 3)):
        record = records[key]
        search_db.refresh(record)
        assert record.source_version == '来源第二版'
        assert record.last_batch_id == second['batch_id']
        assert record.last_row_number == row_number
        assert record.revision == prior[key]['revision'] + 1
        assert record.source_hash == prior[key]['source_hash'] and record.adopted_values == prior[key]['adopted']
        reference = search_db.query(SourceReference).filter_by(case_id=record.case_id,
            evidence_object_id=second['original_evidence_id']).one()
        assert reference.source_revision_id == CaseSourceService.latest_revision(search_db, record.case_id).id
        assert reference.locator['batch_id'] == second['batch_id'] and reference.locator['row'] == row_number
        assert reference.locator['source_status'] == 'unchanged'
        assert reference.locator['source_key'] == '台账A'
        assert reference.locator['source_version'] == '来源第二版'
        assert reference.locator['external_record_key'] == key
    assert search_db.get(EvidenceObject, second['original_evidence_id']).content == reordered.encode()
    assert {case.id: CaseSourceService.source_payload(search_db, case) for case in search_db.query(Case)} == facts
    assert {model.__tablename__: search_db.query(model).count() for model in counts} == {
        model.__tablename__: count for model, count in counts.items()}
    assert search_db.query(OutboxEvent).filter_by(event_type='case.analysis.requested').count() == case_jobs
    before_replay = {model: search_db.query(model).count() for model in (
        CaseImportBatch, CaseImportRow, SourceReference, EvidenceObject)}
    replay = run(search_db, reordered, '来源第二版')
    assert replay['replayed'] and replay['batch_id'] == second['batch_id']
    assert all(search_db.query(model).count() == count for model, count in before_replay.items())
    assert all(record.revision == prior[key]['revision'] + 1 for key, record in records.items())


def test_same_source_version_does_not_advance_identity_and_preview_is_read_only(search_db):
    first = run(search_db, HEADER + ROW, '同一来源版')
    record = search_db.query(CaseImportSourceRecord).one()
    reordered = '简要案情,地点,发现时间,源记录键,油品类型\n现场发现,路口,2026-10-08,K01,原油\n'
    assert run(search_db, reordered, '另一来源版', dry=True)['unchanged'] == 1
    assert (record.source_version, record.revision, record.last_batch_id) == ('同一来源版', 1, first['batch_id'])
    assert search_db.query(EvidenceObject).count() == search_db.query(SourceReference).count() == 1
    received = run(search_db, reordered, '同一来源版')
    search_db.refresh(record)
    assert received['unchanged'] == 1 and not received['replayed']
    assert (record.source_version, record.revision, record.last_batch_id) == ('同一来源版', 1, first['batch_id'])
    # A different received file remains traceable, without inventing another
    # source identity version or another official case revision.
    assert search_db.query(SourceReference).filter_by(evidence_object_id=received['original_evidence_id']).count() == 1
    assert run(search_db, reordered, '同一来源版')['replayed']
    assert search_db.query(EvidenceObject).count() == search_db.query(SourceReference).count() == 2


def test_unchanged_source_audit_and_original_roll_back_together(search_db, monkeypatch):
    first = run(search_db, HEADER + ROW, '第一版')
    original_commit = search_db.commit
    monkeypatch.setattr(search_db, 'commit', lambda: (_ for _ in ()).throw(RuntimeError('合成提交失败')))
    with pytest.raises(RuntimeError, match='合成提交失败'):
        run(search_db, HEADER + ROW, '第二版')
    search_db.rollback()
    monkeypatch.setattr(search_db, 'commit', original_commit)
    record = search_db.query(CaseImportSourceRecord).one()
    assert (record.source_version, record.revision, record.last_batch_id) == ('第一版', 1, first['batch_id'])
    assert search_db.query(EvidenceObject).count() == search_db.query(SourceReference).count() == 1
    assert run(search_db, HEADER + ROW, '第二版')['unchanged'] == 1
    assert search_db.query(CaseImportSourceRecord).one().revision == 2


def test_manual_fact_same_version_blank_and_reused_identity_are_protected(search_db):
    run(search_db, HEADER + ROW)
    case = search_db.query(Case).one()
    CaseService.update_case(search_db, case.id, oil_type='人工确认油品')
    update = run(search_db, (HEADER + ROW).replace('原油', '柴油'), '2')
    assert update['conflict'] == 1 and update['updated'] == 0
    assert search_db.query(Case).one().oil_type == '人工确认油品'
    assert '人工' in update['errors'][0]['error']
    blank = run(search_db, (HEADER + ROW).replace('原油', ''), '3')
    assert blank['conflict'] == 1
    reused = run(search_db, (HEADER + ROW).replace('2026-10-08', '2026-01-01').replace('路口', '另一村'), '4')
    assert reused['conflict'] == 1
    same_version = run(search_db, (HEADER + ROW).replace('现场发现', '补充经过'), '1')
    assert same_version['conflict'] == 1


def test_missing_column_does_not_clear_manual_value(search_db):
    run(search_db, HEADER + ROW)
    case = search_db.query(Case).one()
    CaseService.update_case(search_db, case.id, report_unit='手工填写单位')
    result = run(search_db, (HEADER + ROW).replace('现场发现', '补充现场经过'), '2')
    assert result['updated'] == 1
    assert search_db.query(Case).one().report_unit == '手工填写单位'


def test_unrelated_source_update_never_blesses_manually_changed_fields(search_db):
    run(search_db, HEADER + ROW)
    case = search_db.query(Case).one()
    CaseService.update_case(search_db, case.id, oil_type='人工确认油品', report_unit='人工单位')
    changed = (HEADER + ROW).replace('现场发现', '补充现场经过')
    assert run(search_db, changed, '2')['updated'] == 1
    assert run(search_db, changed.replace('原油', '柴油'), '3')['conflict'] == 1
    additional = changed.replace('油品类型\n', '油品类型,报告单位\n').replace('原油\n', '原油,来源单位\n')
    assert run(search_db, additional, '4')['conflict'] == 1
    assert search_db.query(Case).one().oil_type == '人工确认油品'
    assert search_db.query(Case).one().report_unit == '人工单位'


def test_source_receipts_show_updates_conflicts_and_disable_new_case_retry(search_db):
    from fastapi import HTTPException
    from app.services.case_import_retry_service import list_import_batches, get_batch_rows, retry_batch_rows
    run(search_db, HEADER + ROW)
    changed = (HEADER + ROW).replace('原油', '柴油')
    updated = run(search_db, changed, '2')
    unchanged = run(search_db, changed, '3')
    CaseService.update_case(search_db, search_db.query(Case).one().id, oil_type='人工确认')
    conflict = run(search_db, HEADER + ROW, '4')
    rows = {item['batch_id']: item for item in list_import_batches(search_db)['items']}
    assert rows[updated['batch_id']]['updated'] == 1
    assert rows[unchanged['batch_id']]['unchanged'] == 1
    assert rows[conflict['batch_id']]['conflict'] == 1
    assert rows[conflict['batch_id']]['state'] == 'partial'
    view = get_batch_rows(search_db, conflict['batch_id'])
    assert not view['retry_available'] and view['rows'][0]['status'] == 'conflict'
    assert '源键' in view['next_action']
    with pytest.raises(HTTPException) as rejected:
        retry_batch_rows(search_db, conflict['batch_id'], [{'row': 2, 'revision': 0, 'changes': {'description': '更正'}}])
    assert rejected.value.status_code == 409


def test_failed_source_update_rolls_back_only_its_row_savepoint(search_db, monkeypatch):
    from app.services.case_quality_service import CaseQualityService
    from app.models.case_import import CaseImportBatch
    run(search_db, HEADER + ROW.replace('K01', 'Z01'))
    original = CaseQualityService.refresh_case_quality

    def fail_second(db, case, **kwargs):
        if case.description == '合成写入失败':
            raise ValueError('合成更新阶段故障')
        return original(db, case, **kwargs)

    monkeypatch.setattr(CaseQualityService, 'refresh_case_quality', fail_second)
    result = run(search_db, HEADER + ROW.replace('K01', 'A01')
                 + ROW.replace('K01', 'Z01').replace('现场发现', '合成写入失败'), '2')
    assert result['created'] == 1 and result['failed'] == 1
    assert search_db.query(Case).count() == 2
    assert search_db.query(CaseImportBatch).count() == 2
    assert {case.description for case in search_db.query(Case)} == {'现场发现'}


def test_deleted_target_cannot_be_recreated_and_scope_is_current(search_db):
    run(search_db, HEADER + ROW)
    record = search_db.query(CaseImportSourceRecord).one()
    record.case_id = None
    search_db.commit()
    result = run(search_db, (HEADER + ROW).replace('原油', '柴油'), '2')
    assert result['conflict'] == 1
    search_db.info['authorized_area_ids'] = (2,)
    search_db.info['area_access_levels'] = {2: 'write'}
    with pytest.raises(PermissionError):
        run(search_db, HEADER + ROW, '3')


@pytest.mark.parametrize('body', [HEADER + ROW + ROW, HEADER + ROW.replace('K01', ''),
                                   '简要案情\n现场发现\n'])
def test_source_requires_unique_stable_keys_before_writes(search_db, body):
    with pytest.raises(ValueError):
        run(search_db, body)
    assert search_db.query(Case).count() == 0


def test_clipboard_preserves_declared_manual_input_not_fake_workbook(search_db):
    from io import BytesIO
    from starlette.datastructures import UploadFile
    from app.api.cases import import_cases
    original = '发现时间\t简要案情\n2026-10-09\t人工补录经过\n'.encode()
    receipt = import_cases(file=UploadFile(filename='manual.tsv', file=BytesIO(original)),
        operational_area_id=1, db=search_db, input_method='clipboard')
    assert receipt['input_method'] == 'clipboard' and receipt['created'] == 1
    assert search_db.query(EvidenceObject).one().content == original
    reference = search_db.query(SourceReference).one()
    assert reference.kind == 'manual_paste'
    assert '非原始工作簿' in reference.locator['provenance']
