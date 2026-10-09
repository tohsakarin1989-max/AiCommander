"""Durable staged ledger jobs. Formal facilities change only at atomic adoption.

Parsing and planning commit bounded row checkpoints. The final adoption must be
one transaction while the current schema stores the active facility projection;
it never commits a partially visible complete ledger.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from itertools import islice
from types import SimpleNamespace
from uuid import uuid4

from app.database import bind_principal_scope
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapFeatureClaim, MapIngestRun, OperationalArea
from app.models.user import User
from app.services.map_foundation_service import MapFoundationService as S
from app.services.map_ingest_execution import _execute, get_run, source_for_write
from app.services.map_ingest_originals import capture_original, read_original
from app.services.map_ingest_plan import CATEGORIES, make_plan, public_plan
from app.services.map_ingest_tables import iter_table
from app.services.map_ledger_completeness import declare_plan, parse_declaration

ACTIVE = {'queued', 'parsing', 'planning', 'adopting'}
CHUNK_SIZE = 250


def _metadata(run, job):
    run.table_metadata = {**(run.table_metadata or {}), 'job': deepcopy(job)}


def _structure(run):
    return {key: deepcopy(value) for key, value in (run.table_metadata or {}).items()
            if key not in {'job', 'ledger_declaration', 'ledger_comparison'}}


def _basis(db, source, template):
    area = db.query(OperationalArea).populate_existing().filter_by(id=source.operational_area_id).one()
    return S._hash_json({'template': S.template_to_dict(template),
        'source': [source.id, source.source_key, source.source_type, source.trust_rank,
                   source.status, source.configuration], 'boundary': area.boundary})


def enqueue(db, *, source_id, template_id, filename, content, source_revision, actor_id,
            ledger_declaration=None, input_kind='file'):
    if input_kind not in {'file', 'clipboard'}:
        raise ValueError('invalid_input_kind')
    if input_kind == 'clipboard' and not filename.lower().endswith('.tsv'):
        raise ValueError('clipboard_requires_tsv|人工粘贴须保留制表符原文')
    source = source_for_write(db, source_id, actor_id)
    template = S._get_template(db, source_id, template_id)
    S._validate_transformation(template.coordinate_system, template.transformation)
    declaration = parse_declaration(ledger_declaration)
    digest = sha256(content).hexdigest()
    revision = (source_revision or 'unspecified').strip()[:200] or 'unspecified'
    key = S._hash_json({'staged_job': '9.1-1', 'source': source_id, 'template': S.template_to_dict(template),
                       'file': digest, 'revision': revision, 'declaration': declaration, 'input_kind': input_kind})
    existing = db.query(MapIngestRun).filter_by(idempotency_key=key).first()
    if existing:
        return existing, True
    # Validate only header/sample before accepting; remaining rows are worker work.
    reader = iter_table(filename, content, template=template, metadata={})
    try:
        next(reader, None)
    finally:
        reader.close()
    run = MapIngestRun(id=str(uuid4()), source_id=source_id, template_id=template_id,
        filename=filename[:255], source_revision=revision, file_hash=digest, idempotency_key=key,
        status='queued', created_by=actor_id, total_rows=0, valid_rows=0, quarantined_rows=0,
        created_assets=0, updated_assets=0, template_snapshot=S.template_to_dict(template),
        table_metadata={'job': {'schema_version': 'map-staged-job-9.1-1', 'parsed_rows': 0,
            'planned_rows': 0, 'phase': 'parsing', 'basis': _basis(db, source, template),
            'declaration': declaration, 'visibility': 'not_adopted', 'can_leave_page': True,
            'input_kind': input_kind, 'origin_boundary': '人工粘贴内容，不代表完整原始工作簿' if input_kind == 'clipboard' else '用户上传原件'}})
    db.add(run)
    db.flush()
    capture_original(db, run, content=content, filename=filename)
    db.commit()
    return run, False


def _assemble(db, run, source, template):
    claims = db.query(MapFeatureClaim).filter_by(run_id=run.id).order_by(MapFeatureClaim.row_number).all()
    entries = [deepcopy(claim.plan) for claim in claims]
    if any(not entry for entry in entries):
        raise ValueError('job_not_ready|源行计划尚未完成')
    identity_counts = Counter(claim.source_record_id for claim in claims if claim.source_record_id)
    asset_counts = Counter(row.get('asset_id') for row in entries if row.get('asset_id') is not None)
    for claim, row in zip(claims, entries):
        if (claim.source_record_id and identity_counts[claim.source_record_id] > 1) or (
                row.get('asset_id') is not None and asset_counts[row['asset_id']] > 1):
            row['classification'] = 'failed'
            row['errors'] = [{'field': 'external_id', 'code': 'duplicate_source_identity',
                              'message': '完整批次多行指向同一设施，需逐行核对，不按最后一行覆盖'}]
    counts = {key: sum(row['classification'] == key for row in entries) for key in CATEGORIES}
    structure = _structure(run)
    from app.services.map_import_contract import detect_drift, structure_changes
    drift = detect_drift(template, structure)
    plan = {'source_id': source.id, 'template_id': template.id, 'structure': structure,
        'drift': drift, 'structure_changes': structure_changes(template, structure),
        'counts': counts, 'rows': entries, 'total_rows': len(entries),
        'valid_rows': len(entries) - counts['failed'] - counts['conflict'],
        'quarantined_rows': counts['failed'] + counts['conflict'],
        'publishable': bool(entries) and not drift and counts['failed'] < len(entries),
        'errors': [{'row': row['row_number'], **error} for row in entries for error in row['errors']],
        'sample': [row.get('normalized_payload') for row in entries if row.get('normalized_payload')][:10]}
    plan['plan_token'] = S._hash_json({'job': run.id, 'basis': _basis(db, source, template),
        'structure': structure, 'rows': entries, 'file_hash': run.file_hash})
    declaration = (run.table_metadata or {}).get('job', {}).get('declaration')
    return declare_plan(db, source, template, plan, declaration)


def preview_job(db, run_id):
    run = get_run(db, run_id)
    if run.status != 'ready_to_adopt':
        raise ValueError('job_not_ready|后台尚未完成预览或当前状态不能采用')
    source = S._get_source(db, run.source_id)
    template = S._get_template(db, source.id, run.template_id)
    _check_basis(db, run, source, template)
    return public_plan(_assemble(db, run, source, template))


def control(db, run_id, *, action, actor_id, plan_token=None):
    run = get_run(db, run_id)
    source = source_for_write(db, run.source_id, actor_id)
    query = db.query(MapIngestRun).filter_by(id=run_id)
    if db.bind.dialect.name == 'postgresql':
        query = query.with_for_update()
    run = query.populate_existing().one()
    job = deepcopy((run.table_metadata or {}).get('job') or {})
    if not job:
        raise ValueError('not_staged_job|这是历史同步批次，不能以后台任务控制')
    if action == 'pause' and run.status in {'queued', 'parsing', 'planning'}:
        job['resume_status'] = run.status
        run.status = 'paused'
    elif action == 'resume' and run.status == 'paused':
        run.status = job.get('resume_status', 'queued')
    elif action == 'resume' and run.status == 'failed':
        template = S._get_template(db, source.id, run.template_id)
        _check_basis(db, run, source, template)
        job.pop('approved_plan_token', None)
        job['planned_rows'] = 0
        run.status = 'planning' if job.get('parsing_complete') else 'parsing'
        run.errors = []
    elif action == 'cancel' and run.status in {'queued', 'parsing', 'planning', 'paused', 'ready_to_adopt', 'failed'}:
        run.status = 'cancelled'
        job['visibility'] = 'not_adopted'
    elif action == 'adopt' and run.status == 'ready_to_adopt':
        template = S._get_template(db, source.id, run.template_id)
        _check_basis(db, run, source, template)
        plan = _assemble(db, run, source, template)
        if not plan_token or plan_token != plan['plan_token']:
            raise ValueError('plan_stale|请先查看本批次预览，变化后重新预览')
        if not plan['publishable']:
            raise ValueError('job_not_publishable|暂无可采用行，请修正来源后重新上传')
        if (job.get('declaration') or {}).get('mode') == 'full' and any(
                plan['counts'][key] for key in ('failed', 'conflict', 'identity_pending')):
            raise ValueError('full_ledger_incomplete|完整台账存在异常或身份待核；整批暂不采用，日常仍使用上一有效资料')
        job.update(approved_plan_token=plan_token, adoption_actor_id=actor_id)
        run.status = 'adopting'
    elif (action, run.status) not in {('pause', 'paused'), ('cancel', 'cancelled')}:
        raise ValueError('job_state_conflict|任务状态已变化，请刷新确认')
    _metadata(run, job)
    db.commit()
    return run


def _check_basis(db, run, source, template):
    job = (run.table_metadata or {}).get('job') or {}
    if job.get('basis') != _basis(db, source, template):
        raise ValueError('plan_stale|来源、边界或模板已变化，请按新版本重新准备')


def _check_targets(db, entries):
    for item in entries:
        if item['classification'] == 'failed':
            continue
        # Caller separately resolves exact source identity; this check protects
        # current values while all adoption writes hold the area lock.
        if item.get('asset_id') is not None:
            current = db.query(JurisdictionAsset).populate_existing().filter_by(id=item['asset_id']).first()
            if current is None or S._hash_json(S.asset_to_dict(current)) != item.get('base_hash'):
                raise ValueError('plan_stale|设施资料在准备后变化，请重新准备')


def process_next(db, *, chunk_size=CHUNK_SIZE):
    """Claim one transaction-sized checkpoint; killed workers roll it back."""
    query = db.query(MapIngestRun).filter(MapIngestRun.status.in_(ACTIVE)).order_by(MapIngestRun.started_at, MapIngestRun.id)
    run = query.first()
    if run is None:
        return {'state': 'idle'}
    identifier = run.id
    old_info = dict(db.info)
    try:
        actor_id = (run.table_metadata or {}).get('job', {}).get('adoption_actor_id', run.created_by)
        actor = db.query(User).filter_by(id=actor_id).first()
        if actor is None or not actor.is_active:
            raise PermissionError('map_actor_inactive|发起人已失效')
        bind_principal_scope(db, SimpleNamespace(user_id=actor.id, role=actor.role), method='POST')
        source = source_for_write(db, run.source_id, actor_id)
        # Every writer takes area then run locks, including controls. Reversing
        # this order would deadlock cancellation against final adoption.
        query = db.query(MapIngestRun).filter(MapIngestRun.id == identifier, MapIngestRun.status.in_(ACTIVE))
        if db.bind.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        run = query.populate_existing().first()
        if run is None:
            db.rollback()
            return {'state': 'already_claimed'}
        template = S._get_template(db, source.id, run.template_id)
        _check_basis(db, run, source, template)
        job = deepcopy(run.table_metadata['job'])
        if run.status in {'queued', 'parsing'}:
            content, filename = read_original(db, run.id)
            structure = {}
            reader = iter_table(filename, content, template=template, metadata=structure)
            try:
                rows = list(islice(reader, job['parsed_rows'], job['parsed_rows'] + chunk_size + 1))
            finally:
                reader.close()
            for number, raw in rows[:chunk_size]:
                db.add(MapFeatureClaim(run_id=run.id, source_id=source.id, row_number=number,
                    source_record_id=S._clean_string(S._mapped_value(raw, template.field_mapping, 'external_id')),
                    source_revision=run.source_revision, raw_payload=raw, raw_hash=S._hash_json(raw), status='staged'))
            job['parsed_rows'] += min(chunk_size, len(rows))
            run.total_rows = job['parsed_rows']
            run.table_metadata = {**structure, 'job': job}
            run.status = 'parsing' if len(rows) > chunk_size else 'planning'
            job['parsing_complete'] = run.status == 'planning'
            job['phase'] = run.status
        elif run.status == 'planning':
            claims = db.query(MapFeatureClaim).filter_by(run_id=run.id).order_by(MapFeatureClaim.row_number).offset(
                job['planned_rows']).limit(chunk_size).all()
            plan = make_plan(db, source, template, [(claim.row_number, claim.raw_payload) for claim in claims],
                             _structure(run), file_hash=run.file_hash)
            for claim, entry in zip(claims, plan['rows']):
                claim.plan = entry
            job['planned_rows'] += len(claims)
            if job['planned_rows'] >= run.total_rows:
                run.status = 'ready_to_adopt'
                job['phase'] = 'ready_to_adopt'
                db.flush()
                assembled = _assemble(db, run, source, template)
                run.classification_counts = assembled['counts']
                run.errors = assembled['errors'][:200]
                if assembled['publishable'] and not any(assembled['counts'][key] for key in (
                        'failed', 'conflict', 'identity_pending')):
                    # Uploading with the confirmed source template authorizes
                    # its normal policy; don't invent per-row approval work.
                    job.update(approved_plan_token=assembled['plan_token'],
                               adoption_actor_id=actor_id, phase='adopting', adoption_basis='confirmed_source_policy')
                    run.status = 'adopting'
        else:
            plan = _assemble(db, run, source, template)
            if plan['plan_token'] != job.get('approved_plan_token'):
                raise ValueError('plan_stale|后台采用前的来源或比较基准已变化')
            _check_targets(db, plan['rows'])
            from app.services.map_ingest_plan import resolve_asset
            for item in plan['rows']:
                if item['classification'] == 'failed':
                    continue
                target, _, decision = resolve_asset(db, source, item['normalized_payload'])
                if (target.id if target else None) != item.get('asset_id') or (
                        decision.id if decision else None) != item.get('identity_decision_id'):
                    raise ValueError('plan_stale|来源身份已变化，不能按旧计划采用')
            rows = [(claim.row_number, claim.raw_payload) for claim in db.query(MapFeatureClaim).filter_by(
                run_id=run.id).order_by(MapFeatureClaim.row_number)]
            job.update(visibility='adopted', phase='completed')
            plan['structure'] = {**plan['structure'], 'job': job}
            _execute(db, source=source, template=template, rows=rows, plan=plan, file_hash=run.file_hash,
                     filename=run.filename, revision=run.source_revision, key=run.idempotency_key,
                     created_by=actor_id, existing_run=run)
            return {'state': run.status, 'run_id': run.id}
        _metadata(run, job)
        db.commit()
        return {'state': run.status, 'run_id': run.id, 'parsed_rows': job['parsed_rows'], 'planned_rows': job['planned_rows']}
    except (ValueError, LookupError, PermissionError) as exc:
        db.rollback()
        db.info.clear()
        db.info.update(old_info)
        failed = db.query(MapIngestRun).filter_by(id=identifier).one()
        failed.status = 'failed'
        # Stable code only: don't persist exception text that might contain data.
        failed.errors = [{'code': str(exc).split('|', 1)[0], 'message': '后台准备或采用未完成；正式设施未部分更新，请核对来源、权限或模板'}]
        db.commit()
        return {'state': 'failed', 'run_id': identifier}
    finally:
        db.info.clear()
        db.info.update(old_info)
