import json

import pytest

from app.services.map_package_import_service import create_import, put_chunk, get_import, submit_import
from tests.test_map_package_set import package
from app.config import settings
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with sessionmaker(bind=engine)() as db:
            yield db
    finally:
        engine.dispose()


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MAP_PACKAGE_ROOT', str(tmp_path / 'storage'))
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    return incoming, manifest


def test_resume_and_submit_persist_without_queue_connection(db_session, source):
    directory, manifest = source
    raw = json.dumps(manifest).encode()
    run = create_import(db_session, raw, user_id=None)
    assert create_import(db_session, raw, user_id=None).id == run.id
    assert get_import(db_session, run.id)['received_chunks'] == 0
    for asset in manifest['assets']:
        for chunk in asset['chunks']:
            content = (directory / chunk['file']).read_bytes()
            put_chunk(db_session, run.id, chunk['file'], content)
            put_chunk(db_session, run.id, chunk['file'], content)
    progress = get_import(db_session, run.id)
    assert progress['received_chunks'] == progress['total_chunks'] == 14
    assert progress['missing_chunks'] == []
    assert submit_import(db_session, run.id)['status'] == 'queued'
    assert submit_import(db_session, run.id)['status'] == 'queued'
    assert get_import(db_session, run.id)['publish_ready'] is False


def test_missing_chunks_cannot_submit(db_session, source):
    _, manifest = source
    run = create_import(db_session, json.dumps(manifest).encode(), user_id=None)
    with pytest.raises(ValueError, match='map_import_incomplete'):
        submit_import(db_session, run.id)


@pytest.mark.parametrize('name,content', [('../bad.part', b'wrong'),
    ('unknown.part', b'wrong'), ('vector-0.part', b'wrong')])
def test_bad_upload_does_not_advance_progress(db_session, source, name, content):
    _, manifest = source
    run = create_import(db_session, json.dumps(manifest).encode(), user_id=None)
    with pytest.raises(ValueError):
        put_chunk(db_session, run.id, name, content)
    db_session.rollback()
    assert get_import(db_session, run.id)['received_chunks'] == 0


def test_parallel_uploads_keep_one_receipt(tmp_path, source):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.models.map_package_import import MapPackageImportChunk
    directory, manifest = source
    engine = create_engine(f'sqlite:///{tmp_path / "concurrent.sqlite"}')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            run_id = create_import(db, json.dumps(manifest).encode(), user_id=None).id
        barrier = Barrier(4)
        def upload(_):
            with sessions() as db:
                barrier.wait(timeout=5)
                return put_chunk(db, run_id, 'vector-0.part', (directory / 'vector-0.part').read_bytes())
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(upload, range(4)))
        assert len({r['sha256'] for r in replies}) == 1
        with sessions() as db:
            assert db.query(MapPackageImportChunk).count() == 1
    finally:
        engine.dispose()
