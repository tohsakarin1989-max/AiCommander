"""Private vector copies must survive package namespace changes, not corruption."""
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import os
from threading import Barrier

import pytest

from app.services import map_vector_tile_service as service


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.setattr(service, '_verified', service.OrderedDict())
    yield
    service._verified.clear()


def copy(source):
    content = source.read_bytes()
    fd = os.open(source, os.O_RDONLY)
    try:
        return service._verified_copy(fd, hashlib.sha256(content).hexdigest(), len(content))
    finally:
        os.close(fd)


def test_missing_private_cache_is_rebuilt(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'checked map')
    first = copy(source)
    first.path.unlink()
    rebuilt = copy(source)
    assert rebuilt.path.read_bytes() == b'checked map'
    assert rebuilt.path != first.path


def test_changed_private_cache_is_rebuilt(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'checked map')
    first = copy(source)
    first.path.chmod(0o600)
    first.path.write_bytes(b'altered map')
    assert copy(source).path.read_bytes() == b'checked map'


def test_eviction_keeps_active_reader_alive(tmp_path):
    copies = []
    for index in range(3):
        source = tmp_path / str(index)
        source.write_bytes(str(index).encode())
        copies.append(copy(source))
    assert len(service._verified) == 2
    evicted_path = copies[0].path
    assert evicted_path.read_bytes() == b'0'
    del copies[0]
    gc.collect()
    assert not evicted_path.exists()


def test_concurrent_first_reads_share_one_verified_copy(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'checked map')
    barrier = Barrier(4)

    def read():
        barrier.wait(timeout=5)
        return copy(source)

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: read(), range(4)))
    assert len({result.path for result in results}) == 1
    assert len(service._verified) == 1
