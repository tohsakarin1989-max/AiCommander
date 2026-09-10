import hashlib
import json
import os

import pytest

from app.services.map_package_materialize import materialize_package
from tests.test_map_package_set import package


def test_reassemble_verified_bytes_and_completion_marker(tmp_path):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    output = tmp_path / 'output'
    output.mkdir()
    result = materialize_package(incoming, manifest, output)
    assert result.parent == output
    receipt = json.loads((result / 'assembled.json').read_text())
    assert receipt['publish_ready'] is False
    assert receipt['status'] == 'assembled_integrity_verified'
    for asset, record in zip(manifest['assets'], receipt['assets']):
        data = (result / record['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == asset['sha256']
        assert not ((result / record['file']).stat().st_mode & 0o222)
    assert len(list(incoming.iterdir())) == 14


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'whole_hash', 'symlink'])
def test_failed_assembly_removes_only_own_partial_output(tmp_path, damage):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    output = tmp_path / 'output'
    output.mkdir()
    sentinel = output / 'previous-map'
    sentinel.write_text('retain')
    asset = manifest['assets'][-1]
    path = incoming / asset['chunks'][0]['file']
    if damage == 'missing':
        path.unlink()
    elif damage == 'corrupt':
        path.write_bytes(b'xxxxx')
    elif damage == 'whole_hash':
        asset['sha256'] = '0' * 64
    else:
        path.unlink()
        path.symlink_to(sentinel)
    with pytest.raises((ValueError, OSError)):
        materialize_package(incoming, manifest, output)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_text() == 'retain'


def test_repeated_assembly_never_overwrites_existing_output(tmp_path):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    first = materialize_package(incoming, manifest, tmp_path)
    original = (first / 'assembled.json').read_bytes()
    second = materialize_package(incoming, manifest, tmp_path)
    assert first != second
    assert (first / 'assembled.json').read_bytes() == original


@pytest.mark.parametrize('failure', ['disk_full', 'interrupted'])
def test_write_failure_and_interruption_leave_no_completion(tmp_path, monkeypatch, failure):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    output = tmp_path / 'output'
    output.mkdir()

    def fail_sync(_fd):
        if failure == 'disk_full':
            raise OSError('simulated disk full')
        raise KeyboardInterrupt()

    monkeypatch.setattr(os, 'fsync', fail_sync)
    with pytest.raises(OSError if failure == 'disk_full' else KeyboardInterrupt):
        materialize_package(incoming, manifest, output)
    assert list(output.iterdir()) == []
    assert len(list(incoming.iterdir())) == 14


def test_old_integrity_report_does_not_skip_rechecking(tmp_path):
    from app.services.map_package_set import verify_directory

    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    assert verify_directory(incoming, manifest)['status'] == 'integrity_verified'
    (incoming / manifest['assets'][0]['chunks'][0]['file']).write_bytes(b'xxxxx')
    output = tmp_path / 'output'
    output.mkdir()
    with pytest.raises(ValueError):
        materialize_package(incoming, manifest, output)
    assert list(output.iterdir()) == []
