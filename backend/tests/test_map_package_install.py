"""Atomic storage installation is not semantic acceptance or publication."""
import hashlib
import fcntl

import pytest

from app.services.map_package_install import install_assets
from app.services.map_package_materialize import materialize_package
from tests.test_map_package_set import package


def source(tmp_path, composite=False):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    next(a for a in manifest['assets'] if a['role'] == 'glyphs')['name'] = 'glyphs-0-255.pbf'
    if composite:
        manifest['font_profile'] = 'cjk-mongolian-emoji-v1'
    staging = tmp_path / 'staging'
    staging.mkdir()
    return materialize_package(incoming, manifest, staging), manifest


@pytest.mark.parametrize('composite', [False, True])
def test_install_all_assets_and_retry_without_rewriting(tmp_path, composite):
    directory, manifest = source(tmp_path, composite)
    root = tmp_path / 'store'
    root.mkdir()
    report = install_assets(directory, root)
    assert report['status'] == 'installed_integrity_verified'
    assert report['publish_ready'] is False
    assert report['reused'] is False
    assert len(report['assets']) == len(manifest['assets'])
    times = {}
    for record in report['assets']:
        path = root / record['storage_key']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
        times[path] = path.stat().st_mtime_ns
    glyph = next(a for a in report['assets'] if a['role'] == 'glyphs')
    slug = 'cjk-mongolian-emoji-v1' if composite else 'noto-sans-cjk-sc-regular'
    assert f'/glyphs/{slug}/0-255.pbf' in glyph['storage_key']
    assert install_assets(directory, root)['reused'] is True
    assert all(path.stat().st_mtime_ns == stamp for path, stamp in times.items())


def test_bad_source_does_not_leave_visible_package(tmp_path):
    directory, _ = source(tmp_path)
    bad = directory / 'asset-0003.bin'
    bad.chmod(0o600)
    bad.write_bytes(b'changed')
    root = tmp_path / 'store'
    root.mkdir()
    with pytest.raises(ValueError):
        install_assets(directory, root)
    assert not [p for p in (root / 'bundles').iterdir() if p.is_dir()]


def test_corrupt_existing_destination_is_never_overwritten(tmp_path):
    directory, _ = source(tmp_path)
    root = tmp_path / 'store'
    root.mkdir()
    installed = install_assets(directory, root)
    path = root / installed['assets'][0]['storage_key']
    path.chmod(0o600)
    path.write_bytes(b'preserve corruption for investigation')
    with pytest.raises(ValueError):
        install_assets(directory, root)
    assert path.read_bytes() == b'preserve corruption for investigation'


def test_storage_symlink_is_not_followed(tmp_path):
    directory, _ = source(tmp_path)
    root, outside = tmp_path / 'store', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (root / 'bundles').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        install_assets(directory, root)
    assert list(outside.iterdir()) == []


def test_concurrent_install_is_busy_then_reusable(tmp_path):
    directory, _ = source(tmp_path)
    root = tmp_path / 'store'
    root.mkdir()
    report = install_assets(directory, root)
    lock_path = root / 'bundles' / f".install-{report['package_hash']}.lock"
    with lock_path.open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='map_installation_busy'):
            install_assets(directory, root)
    assert install_assets(directory, root)['reused'] is True


def test_corrupt_manifest_does_not_reuse_destination(tmp_path):
    directory, _ = source(tmp_path)
    root = tmp_path / 'store'
    root.mkdir()
    report = install_assets(directory, root)
    manifest = root / 'bundles' / report['package_hash'] / 'manifest.json'
    manifest.chmod(0o600)
    manifest.write_bytes(b'{}')
    with pytest.raises(ValueError, match='installed_manifest_mismatch'):
        install_assets(directory, root)
    assert manifest.read_bytes() == b'{}'
