"""Exact-input reuse is not source identity; isolated retries stay observable."""
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError

from app.models.case_history_index import CaseHistoryFragment, CaseHistoryIndex, CaseHistoryVectorReuse
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import CaseRevision
from app.services.case_history_index_debt import EVENT_TYPE, current_input_stamp
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_source_service import CaseSourceService
from app.services.local_embedding_service import LocalEmbeddingError
from tests.test_case_history_index import db, make_case  # noqa: F401


class Embedder:
    state, model_version, dimension, encoder_fingerprint = 'ready', 'synthetic-v75', 2, 'config-A'

    def __init__(self):
        self.calls, self.fail_text, self.on_encode = [], None, None

    def encode(self, text):
        self.calls.append(text)
        if self.fail_text and self.fail_text in text:
            raise LocalEmbeddingError('sensitive original text must not be stored')
        if self.on_encode:
            self.on_encode(text)
        return [1.] + [0.] * (self.dimension - 1)


@pytest.fixture
def encoder(monkeypatch):
    encoder = Embedder()
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', lambda: encoder)
    return encoder


def run(db, limit=100):
    result = CaseHistoryIndexService.reconcile_batch(db, limit=limit)
    db.commit()
    return result


def debt_for(db, case):
    return db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE,
        OutboxEvent.aggregate_id == str(case.id)))


def make_due(db, debt):
    debt.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


def test_exact_input_reuse_keeps_each_revision_and_reference(db, encoder):
    first, second = make_case(db), make_case(db, 'SECOND')
    first.description = second.description = '重复原文。重复原文。'
    rev_a, _ = CaseSourceService.capture_change(db, first)
    CaseSourceService.capture_change(db, second)
    db.commit()
    result = run(db)
    assert encoder.calls.count('重复原文。') == 1
    assert result['reused_vectors'] >= 3
    initial = db.scalar(select(CaseHistoryFragment).where(CaseHistoryFragment.case_id == first.id,
        CaseHistoryFragment.field == 'description', CaseHistoryFragment.start == 0))
    first_id = initial.id
    assert initial.source_revision_id == rev_a.id
    first.description = '另一个版本。'
    rev_b, _ = CaseSourceService.capture_change(db, first)
    db.commit()
    run(db)
    assert encoder.calls.count('另一个版本。') == 1
    count = len(encoder.calls)
    first.description = '重复原文。重复原文。'
    rev_a2, _ = CaseSourceService.capture_change(db, first)
    db.commit()
    run(db)
    assert len(encoder.calls) == count
    current = list(db.scalars(select(CaseHistoryFragment).where(CaseHistoryFragment.case_id == first.id,
        CaseHistoryFragment.field == 'description').order_by(CaseHistoryFragment.start)))
    assert {row.source_revision_id for row in current} == {rev_a2.id}
    assert current[0].id != first_id and current[0].quote == current[1].quote
    assert current[0].start != current[1].start and current[0].id != current[1].id
    assert len(set([rev_a.id, rev_b.id, rev_a2.id])) == 3
    assert db.query(CaseRevision).filter_by(case_id=first.id).count() == 3
    assert set(CaseHistoryVectorReuse.__table__.columns.keys()) == {
        'text_sha256', 'encoder_fingerprint', 'dimension', 'model_version', 'embedding', 'created_at'}


@pytest.mark.parametrize('attribute,new_value', [
    ('model_version', 'synthetic-v76'), ('dimension', 3), ('encoder_fingerprint', 'config-B')])
def test_model_dimension_and_actual_encoder_config_never_reuse(db, encoder, attribute, new_value):
    make_case(db)
    run(db)
    first = len(encoder.calls)
    setattr(encoder, attribute, new_value)
    run(db)
    assert len(encoder.calls) == first * 2
    assert db.query(CaseHistoryVectorReuse).count() == first * 2


def test_literal_whitespace_change_is_new_encoder_input(db, encoder):
    case = make_case(db)
    run(db)
    first = len(encoder.calls)
    case.description += ' '
    # Trailing whitespace outside a sentence is not encoded. A leading space is.
    case.description = ' ' + case.description
    db.commit()
    run(db)
    assert len(encoder.calls) == first + 1
    assert encoder.calls[-1].startswith(' ')


def test_reuse_cannot_bypass_revocation_or_publish_after_encoder_changes(db, encoder):
    case = make_case(db)
    run(db)
    db.info['authorized_area_ids'] = ()
    before = len(encoder.calls)
    with pytest.raises(PermissionError, match='history_source_unavailable'):
        CaseHistoryIndexService.rebuild_case(db, case)
    assert len(encoder.calls) == before
    db.info.pop('authorized_area_ids')
    publications = []
    CaseHistoryIndexService.rebuild_case(db, case, publications=publications)
    encoder.encoder_fingerprint = 'config-B'
    with pytest.raises(ValueError, match='history_encoder_changed'):
        publications[0]()
    db.rollback()


def test_encoder_config_change_excludes_old_semantic_vectors_before_rebuild(db, encoder):
    from app.services.case_history_fragment_search import search_fragments
    make_case(db)
    run(db)
    db.info['authorized_area_ids'] = (1,)
    assert search_fragments(db, query='不同检索词', semantic_only=True,
        embedding_model=encoder)['coverage']['vector_sources'] == 3
    encoder.encoder_fingerprint = 'config-B'
    result = search_fragments(db, query='不同检索词', semantic_only=True, embedding_model=encoder)
    assert result['coverage']['vector_sources'] == 0 and not result['items']
    assert result['semantic_index_state'] == 'partial'


def test_current_debt_stamp_is_read_only_and_matches_full_source_identity(db, encoder):
    case = make_case(db)
    revision, _ = CaseSourceService.capture_change(db, case)
    db.commit()
    # The helper also preserves a caller with SQLAlchemy's default autoflush.
    case.description = case.description + '未提交更改。'
    db.autoflush = True
    writes = []
    def capture(_conn, _cursor, sql, *_args):
        if sql.split()[0].lower() in {'insert', 'update', 'delete'}:
            writes.append(sql)
    event.listen(db.bind, 'before_cursor_execute', capture)
    try:
        stamp = current_input_stamp(db, case)
    finally:
        event.remove(db.bind, 'before_cursor_execute', capture)
    assert not writes and not encoder.calls
    db.autoflush = False
    assert stamp['source_hash'] == CaseSourceService.source_hash(db, case)
    assert stamp['source_revision_id'] == revision.id


@pytest.mark.parametrize('change', ['source', 'scope', 'schema', 'process'])
def test_prepared_publish_rechecks_source_scope_schema_and_process(db, encoder, monkeypatch, change):
    from app.services import case_history_fragments
    case = make_case(db)
    publications = []
    CaseHistoryIndexService.rebuild_case(db, case, publications=publications)
    if change == 'source':
        case.description = '修订发生在推理之后。'
        db.flush()
        expected = 'history_source_changed'
    elif change == 'scope':
        db.info['authorized_area_ids'] = ()
        expected = 'history_source_changed'
    elif change == 'schema':
        monkeypatch.setattr(case_history_fragments, 'FRAGMENT_INDEX_VERSION', 'future-schema')
        expected = 'history_schema_changed'
    else:
        monkeypatch.setattr(case_history_fragments, '_process_stamp', lambda *_args: 'different-profile')
        expected = 'history_process_changed'
    with pytest.raises(ValueError, match=expected):
        publications[0]()
    db.rollback()
    db.info.pop('authorized_area_ids', None)
    assert db.query(CaseHistoryIndex).count() == 0
    assert db.query(CaseHistoryVectorReuse).count() == 0


@pytest.mark.parametrize('recovery', ['manual', 'new_source'])
def test_prepare_failure_isolated_three_attempts_terminal_and_recoverable(db, encoder, recovery):
    broken = make_case(db, 'BROKEN')
    good = make_case(db, 'GOOD')
    broken.description = '故障原文。'
    CaseSourceService.capture_change(db, broken)
    db.commit()
    encoder.fail_text = '故障'
    result = run(db, 1)
    assert result['failed_cases'] == 1 and result['state'] == 'degraded'
    debt = debt_for(db, broken)
    assert debt.id and debt.status == 'retry' and debt.attempts == 1
    assert debt.payload['source_hash'] == CaseSourceService.source_hash(db, broken)
    assert debt.payload['input_hash'] == current_input_stamp(db, broken)['input_hash']
    assert debt.error == 'history_embedding_failed'
    assert '故障' not in str(debt.payload) and 'sensitive' not in str(debt.payload)
    assert run(db, 1)['changed_sources'] == 1
    assert db.scalar(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == good.id))
    for attempt in [2, 3]:
        make_due(db, debt)
        assert run(db, 1)['failed_cases'] == 1
        assert debt.attempts == attempt
    assert debt.status == 'failed'
    failed_calls = len(encoder.calls)
    for _ in range(4):
        result = run(db, 1)
        assert result['failed_cases'] == 0 and result['terminal_failed_cases'] == 1
    assert len(encoder.calls) == failed_calls
    if recovery == 'manual':
        debt.status = 'retry'
        debt.payload = {**debt.payload, 'ordinary_failures': 0}
        make_due(db, debt)
        assert run(db, 1)['failed_cases'] == 1
        assert debt.status == 'retry' and debt.attempts == 4 and debt.payload['ordinary_failures'] == 1
        make_due(db, debt)
    else:
        broken.description = '修订后的有效原文。'
        CaseSourceService.capture_change(db, broken)
        db.commit()
    encoder.fail_text = None
    for _ in range(3):
        run(db, 1)
    assert debt.status == 'completed' and debt.error is None
    assert db.scalar(select(CaseHistoryIndex).where(CaseHistoryIndex.case_id == broken.id))


def test_publish_unknown_error_rolls_back_only_failed_case_and_is_not_healthy(db, encoder, monkeypatch):
    broken, good = make_case(db), make_case(db, 'GOOD')
    from app.services import history_road_refresh
    original = history_road_refresh.record_change
    def fail_one(db, *, case_id, area_ids):
        if case_id == broken.id:
            raise RuntimeError('sensitive input must not leave the process')
        return original(db, case_id=case_id, area_ids=area_ids)
    monkeypatch.setattr(history_road_refresh, 'record_change', fail_one)
    result = run(db)
    assert result['failed_cases'] == 1 and result['changed_sources'] == 1
    assert result['state'] == 'degraded'
    assert {row.case_id for row in db.scalars(select(CaseHistoryIndex))} == {good.id}
    assert {row.case_id for row in db.scalars(select(CaseHistoryFragment))} == {good.id}
    debt = debt_for(db, broken)
    assert debt.payload['failure_stage'] == 'publish'
    assert debt.error == 'history_index_unexpected_error' and 'sensitive' not in str(debt.payload)
    monkeypatch.setattr(history_road_refresh, 'record_change', original)
    make_due(db, debt)
    assert run(db)['failed_cases'] == 0 and debt.status == 'completed'


def test_unexpected_model_exception_is_isolated_and_explicit(db, encoder):
    broken, good = make_case(db, 'BROKEN'), make_case(db, 'GOOD')
    def unexpected(text):
        if text == 'BROKEN':
            raise RuntimeError('private model detail')
    encoder.on_encode = unexpected
    result = run(db)
    assert result['failed_cases'] == 1 and result['state'] == 'degraded'
    assert result['failure_codes'] == ['history_index_unexpected_error']
    assert debt_for(db, broken).payload['failure_stage'] == 'prepare'
    assert {row.case_id for row in db.scalars(select(CaseHistoryIndex))} == {good.id}


def test_cache_write_failure_keeps_core_index_and_sync_rebuild_does_not_commit(db, encoder):
    case = make_case(db)
    def reject_cache(_conn, _cursor, sql, params, _context, _many):
        if sql.lower().startswith('insert into case_history_vector_reuse'):
            raise OperationalError('synthetic cache failure', None, None)
    event.listen(db.bind, 'before_cursor_execute', reject_cache)
    try:
        result = run(db)
    finally:
        event.remove(db.bind, 'before_cursor_execute', reject_cache)
    assert result['changed_sources'] == 1 and result['vector_reuse_write_failures'] == 1
    assert db.query(CaseHistoryFragment).count() == 3 and db.query(CaseHistoryVectorReuse).count() == 0
    case.description = '未提交修订。'
    db.flush()
    CaseHistoryIndexService.rebuild_case(db, case)
    db.rollback()
    assert case.description != '未提交修订。'
    assert not db.scalar(select(CaseHistoryFragment).where(CaseHistoryFragment.quote == '未提交修订。'))
    assert db.query(CaseHistoryVectorReuse).count() == 0


def test_reuse_migration_round_trip_only_touches_disposable_table():
    path = Path(__file__).parents[1] / 'alembic/versions/v75h01_history_vector_reuse.py'
    spec = spec_from_file_location('reuse_migration', path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == 'v75h01' and migration.down_revision == 'v74c01'
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE original_source (id INTEGER PRIMARY KEY, value TEXT)')
        connection.exec_driver_sql("INSERT INTO original_source VALUES (1, 'preserve original')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert 'case_history_vector_reuse' in inspect(connection).get_table_names()
            migration.downgrade()
            assert 'case_history_vector_reuse' not in inspect(connection).get_table_names()
            migration.upgrade()
        assert connection.exec_driver_sql('SELECT value FROM original_source').scalar() == 'preserve original'
    engine.dispose()


def test_real_alembic_chain_keeps_original_and_revision_history(tmp_path):
    from tests.test_result_material_migration_v65 import migrate
    url = f'sqlite:///{tmp_path / "history-reuse.sqlite"}'
    result = migrate(url, 'upgrade', 'v74c01')
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO cases(id,case_number,description,operational_area_id) "
                                "VALUES(7501,'V75-SYNTHETIC','原始修订不进入缓存',1)"))
        connection.execute(text('INSERT INTO case_revisions(case_id,revision,source_hash,payload) '
                                'VALUES(7501,1,:sha,:payload)'),
                           {'sha': 'a' * 64, 'payload': '{"original":"保留历史原文"}'})
    engine.dispose()
    for direction, target in [('upgrade', 'v75h01'), ('downgrade', 'v74c01'), ('upgrade', 'v75h01')]:
        result = migrate(url, direction, target)
        assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == 'v75h01'
        assert connection.scalar(text('SELECT COUNT(*) FROM case_history_vector_reuse')) == 0
        assert connection.scalar(text('SELECT description FROM cases WHERE id=7501')) == '原始修订不进入缓存'
        assert connection.scalar(text('SELECT payload FROM case_revisions WHERE case_id=7501')) == '{"original":"保留历史原文"}'
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()
