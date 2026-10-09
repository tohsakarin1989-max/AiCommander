"""Versioned source rows adopt through the case service, never overwrite manual facts."""
import hashlib

from sqlalchemy.exc import IntegrityError

from app.database import require_area_write_access
from app.models.case import Case
from app.models.case_import import CaseImportRow, CaseImportSourceRecord
from app.services.case_import_batch_service import acquire_import_batch
from app.services.case_import_values import normalize_case_row, case_row_preview, allocation_order
from app.services.case_source_service import CaseSourceService, case_payload, encode, json_value
from app.services.case_service import CaseService


def _values(row, zone):
    normalized = normalize_case_row(row, time_zone=zone)
    # Parsing defaults must not turn absent columns into instructions to clear facts.
    fields = set(row) - {'external_record_key', 'security_team'}
    if 'security_team' in row:
        fields.add('report_unit')
    fields.add('time_timezone')
    if {'occurred_time', 'occurred_from', 'occurred_to'} & fields:
        fields.add('time_precision')
    return normalized, {key: normalized[key] for key in fields if key in normalized}


def _plan(db, area, source, key, raw, zone, source_version, *, lock=False):
    normalized, values = _values(raw, zone)
    payload = json_value(values)
    signature = hashlib.sha256(encode(payload).encode()).hexdigest()
    query = db.query(CaseImportSourceRecord).filter_by(operational_area_id=area,
                                                      source_key=source, external_key=key)
    record = query.with_for_update().populate_existing().one_or_none() if lock else query.one_or_none()
    case = None
    changes = {}
    conflicts = []
    if record is None:
        action = 'created'
    else:
        case_query = db.query(Case).filter(Case.id == record.case_id)
        case = case_query.with_for_update().populate_existing().one_or_none() if lock else case_query.one_or_none()
        if case is None:
            return 'conflict', record, None, normalized, values, signature, {}, ['来源目标已撤回或不可访问，不能重新建案']
        if signature == record.source_hash:
            action = 'unchanged'
        else:
            action = 'updated'
            changes = {key: value for key, value in values.items()
                       if json_value(value) != record.source_values.get(key)}
            if source_version and source_version == record.source_version:
                conflicts.append('同一来源版本出现不同内容，请核实版本或记录键')
            current = case_payload(case)
            for field, value in changes.items():
                if value in (None, '') and record.source_values.get(field) not in (None, ''):
                    conflicts.append(f'{field}：空白不能自动清除已有事实')
                if current.get(field) != record.adopted_values.get(field):
                    conflicts.append(f'{field}：正式记录已人工或另源修改')
            # A location/quantity edit must not erase separately maintained typed facts.
            latest = CaseSourceService.latest_revision(db, case.id)
            for fields, group in (({'location', 'latitude', 'longitude'}, 'locations'),
                                  ({'oil_volume', 'oil_volume_unit', 'water_cut'}, 'measurements')):
                if fields & set(changes) and latest and latest.payload.get(group) != record.adopted_values.get('_' + group):
                    conflicts.append(f'{group}：结构化事实已变化，请在记录详情核对')
            anchors = {'discovered_at', 'occurred_time', 'location'}
            known = {name for name in anchors if record.source_values.get(name) not in (None, '')}
            if known and known <= set(changes):
                conflicts.append('时间和地点标识同时变化，须核实源记录键是否被复用')
            if conflicts:
                action = 'conflict'
    return action, record, case, normalized, values, signature, changes, conflicts


def import_source_table(db, *, table, content, area_id, source_key, source_revision=None,
                        time_zone='UTC', dry_run=False, input_method='file'):
    area_id = require_area_write_access(db, area_id)
    source_key = source_key.strip()
    source_revision = source_revision.strip() if source_revision else None
    if not area_id or not 1 <= len(source_key) <= 80 or (source_revision and len(source_revision) > 100):
        raise ValueError('请选择明确厂区，来源标识限80字、版本限100字')
    if 'external_record_key' not in table.field_mapping.values():
        raise ValueError('持续更新必须映射稳定的源记录键列；无键资料请使用普通首次导入')
    keys = [str(row.values.get('external_record_key') or '').strip() for row in table.rows]
    if any(not key or len(key) > 160 for key in keys) or len(keys) != len(set(keys)):
        raise ValueError('源记录键不能为空、超过160字或在同表重复')
    if not dry_run and db.bind.dialect.name == 'postgresql':
        # Source identities absent at first import cannot be row-locked yet.
        # Serialize the scoped import family before acquiring per-source/case
        # locks; changed row order must not create lock-order cycles.
        from sqlalchemy import text
        lock_key = int.from_bytes(hashlib.sha256(f'case-source-import:{area_id}'.encode()).digest()[:8], 'big', signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    batch = None
    if not dry_run:
        batch, created = acquire_import_batch(db, content=content, area_id=area_id, table=table,
            source_identity={'source_key': source_key, 'source_revision': source_revision, 'time_zone': time_zone})
        if not created:
            if batch.result is None:
                raise ValueError('该来源批次正在处理，请稍后查看回执')
            return {**batch.result, 'created': 0, 'updated': 0, 'replayed': True,
                    'original_created': batch.result.get('created', 0)}
    counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'conflict': 0, 'failed': 0}
    previews, errors = [], []
    rows = sorted(zip(table.rows, keys), key=lambda pair: (
        allocation_order(pair[0].values, time_zone, pair[0].number)[0], pair[1]))
    for item, key in rows:
        case, error = None, None
        try:
            action, record, case, normalized, values, signature, changes, conflicts = _plan(
                db, area_id, source_key, key, item.values, time_zone, source_revision, lock=not dry_run)
            preview = {**case_row_preview(item.number, normalized), 'action': action,
                       'external_record_key': key, 'case_id': case.id if case else None,
                       'changed_fields': sorted(changes), 'conflicts': conflicts,
                       'differences': [{'field': name, 'previous_source': record.source_values.get(name) if record else None,
                                        'current': json_value(getattr(case, name, None)) if case else None,
                                        'incoming': json_value(value)} for name, value in changes.items()]}
            if action == 'conflict':
                error = '；'.join(conflicts)
            if not dry_run and action in {'created', 'updated'}:
                with db.begin_nested():
                    if action == 'created':
                        case = CaseService.create_case(db, case_number=None, operational_area_id=area_id,
                                                       commit=False, **normalized)
                        record = CaseImportSourceRecord(operational_area_id=area_id, source_key=source_key,
                            external_key=key, case_id=case.id, revision=0)
                    else:
                        case = CaseService.update_case(db, case.id, commit=False, **changes)
                    record.source_values, record.source_hash = json_value(values), signature
                    record.source_version = source_revision
                    current = case_payload(case)
                    # Never bless other manually maintained fields merely
                    # because an unrelated source field changed this time.
                    adopted = dict(record.adopted_values or {}) if action == 'updated' else {}
                    adopted.update({field: current.get(field) for field in (changes if action == 'updated' else values)})
                    latest = CaseSourceService.latest_revision(db, case.id)
                    for fields, group in (({'location', 'latitude', 'longitude'}, 'locations'),
                                          ({'oil_volume', 'oil_volume_unit', 'water_cut'}, 'measurements')):
                        if action == 'created' or fields & set(changes):
                            adopted['_' + group] = latest.payload.get(group, []) if latest else []
                    record.adopted_values = adopted
                    record.last_batch_id, record.last_row_number = batch.id, item.number
                    record.revision += 1
                    db.add(record)
                    db.flush()
                preview['case_id'] = case.id
            elif not dry_run and action == 'unchanged' and source_revision:
                record.source_version = source_revision
            previews.append(preview)
        except (ValueError, IntegrityError) as exc:
            action = 'failed'
            case = None
            error = str(exc) if isinstance(exc, ValueError) else '来源正在被其他导入处理，请刷新后重试原批次'
            previews.append({'row': item.number, 'action': action, 'conflicts': [error]})
        counts[action] += 1
        if error:
            errors.append({'row': item.number, 'error': error})
        if batch is not None:
            snapshot = json_value(item.values)
            db.add(CaseImportRow(batch_id=batch.id, operational_area_id=area_id, row_number=item.number,
                source_values=snapshot, current_values=snapshot, time_zone=time_zone, status=action,
                case_id=case.id if case else None, error=error, revision=0, corrections=[]))
    previews.sort(key=lambda item: item['row'])
    errors.sort(key=lambda item: item['row'])
    result = {**counts, 'valid': len(table.rows) - counts['failed'] - counts['conflict'], 'total': len(table.rows),
              'created': 0 if dry_run else counts['created'], 'updated': 0 if dry_run else counts['updated'],
              'planned': counts, 'dry_run': dry_run, 'preview': previews, 'errors': errors,
              'batch_id': batch.id if batch else None, 'replayed': False,
              'source_key': source_key, 'source_revision': source_revision,
              'input_method': input_method,
              'table': {'worksheet': table.worksheet, 'worksheets': table.worksheets,
                        'header_row': table.header_row, 'field_mapping': table.field_mapping,
                        'ignored_headers': table.ignored_headers, 'time_zone': time_zone},
              'boundary': '来源记录身份不等于事件身份；缺席不删除，冲突不覆盖，请回原记录核对后重新预览'}
    if batch:
        from app.services.case_import_original import preserve_received_input
        result['original_evidence_id'] = preserve_received_input(db, batch, content, input_method)
        batch.result = result
        db.commit()
    return result
