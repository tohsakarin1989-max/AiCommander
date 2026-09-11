"""Opt-in migration check against a newly owned, disposable local PostgreSQL."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_postgres_scope_migration_and_transactional_triggers(monkeypatch):
    value = os.environ.get('AIC_QUERY_SCOPE_PG_URL')
    if not value:
        pytest.skip('disposable PostgreSQL not requested')
    url = make_url(value)
    assert url.host == '127.0.0.1' and url.database == 'aic_query_scope'
    assert os.environ.get('AIC_DISPOSABLE_QUERY_SCOPE') == '1'
    from app.config import settings
    monkeypatch.setattr(settings, 'DATABASE_URL', value)
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'alembic'))
    engine = create_engine(value)
    try:
        with engine.connect() as db:
            existing = db.scalar(text("SELECT to_regclass('public.cases')"))
            if existing is not None:
                # Resume only this owned pre-upgrade fixture after setup failure.
                assert db.scalar(text('SELECT version_num FROM alembic_version')) == '82d5f19ec429'
                assert db.scalar(text('SELECT count(*) FROM cases')) == 0
        command.upgrade(config, '82d5f19ec429')
        with engine.begin() as db:
            db.execute(text("INSERT INTO operational_areas(id,code,name,is_default,status) VALUES (991,'query-pg-test','合成区域',false,'active')"))
            identifier = db.scalar(text("INSERT INTO cases(case_number,occurred_time,description,operational_area_id) "
                "VALUES ('SYNTHETIC-SCOPE-PG',now(),'不可自动改写',1) RETURNING id"))
        command.upgrade(config, '93e6a20fd53b')
        with engine.begin() as db:
            assert db.scalar(text("SELECT revision FROM query_scope_revision WHERE id=1")) == 0
            assert db.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'aic_query_scope_%_v1' AND NOT tgisinternal")) == 6
            assert db.scalar(text('SELECT description FROM cases WHERE id=:id'), {'id': identifier}) == '不可自动改写'
            db.execute(text("INSERT INTO cases(case_number,occurred_time,operational_area_id) VALUES ('SYNTHETIC-SCOPE-PG-NEW',now(),1)"))
            assert db.scalar(text("SELECT revision FROM query_scope_revision WHERE id=1")) == 0
        with engine.connect() as db:
            tx = db.begin()
            db.execute(text('UPDATE cases SET operational_area_id=991 WHERE id=:id'), {'id': identifier})
            assert db.scalar(text('SELECT revision FROM query_scope_revision WHERE id=1')) == 1
            tx.rollback()
            assert db.scalar(text('SELECT revision FROM query_scope_revision WHERE id=1')) == 0
        with engine.begin() as db:
            db.execute(text('DELETE FROM cases WHERE id=:id'), {'id': identifier})
            assert db.scalar(text('SELECT revision FROM query_scope_revision WHERE id=1')) == 1
    finally:
        engine.dispose()
