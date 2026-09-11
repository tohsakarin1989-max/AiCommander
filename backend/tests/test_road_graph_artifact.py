from dataclasses import replace
import hashlib

import pytest

from app.services.road_graph_artifact import graph_inventory_sha256, verify_graph_artifact
from app.services.road_graph_artifact import install_graph_artifact
from app.services.road_network_service import RoadNetworkBinding, RoadNetworkUnavailable


def test_inventory_compatible_and_content_change_rejected(tmp_path):
    key = 'a' * 64
    tiles = tmp_path / key / 'tiles'
    tiles.mkdir(parents=True)
    tile = tiles / '001.gph'
    tile.write_bytes(b'synthetic tile')
    expected = hashlib.sha256(
        f'tiles/001.gph\t14\t{hashlib.sha256(b"synthetic tile").hexdigest()}\n'.encode()
    ).hexdigest()
    assert graph_inventory_sha256(tiles) == expected
    binding = RoadNetworkBinding('graph', 1, 1, expected, key, '3.8.3', 'cache')
    assert verify_graph_artifact(tmp_path, binding) == tiles
    tile.write_bytes(b'damaged')
    with pytest.raises(RoadNetworkUnavailable, match='checksum_mismatch'):
        verify_graph_artifact(tmp_path, binding)
    with pytest.raises(RoadNetworkUnavailable, match='key_invalid'):
        verify_graph_artifact(tmp_path, replace(binding, artifact_key='../private'))


@pytest.mark.parametrize('kind', ['empty', 'file_link', 'directory_link', 'alternate_input'])
def test_no_empty_graph_links_or_untracked_inputs(tmp_path, kind):
    tiles = tmp_path / 'tiles'
    tiles.mkdir()
    if kind == 'file_link':
        (tiles / '001.gph').symlink_to(tmp_path / 'outside')
    elif kind == 'directory_link':
        (tiles / 'linked').symlink_to(tmp_path, target_is_directory=True)
    elif kind == 'alternate_input':
        (tiles / 'traffic.tar').write_bytes(b'untracked')
    with pytest.raises(RoadNetworkUnavailable):
        graph_inventory_sha256(tiles)


def test_install_is_content_addressed_idempotent_and_does_not_move_source(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / '001.gph').write_bytes(b'graph fixture')
    digest = graph_inventory_sha256(source)
    root = tmp_path / 'published'
    assert install_graph_artifact(source, root, expected_sha256=digest) == digest
    assert install_graph_artifact(source, root, expected_sha256=digest) == digest
    assert graph_inventory_sha256(root / digest / 'tiles') == digest
    assert (source / '001.gph').read_bytes() == b'graph fixture'
    assert not list(root.glob('.install-*'))


def test_interrupted_install_never_exposes_partial_package(tmp_path, monkeypatch):
    from app.services import road_graph_artifact as module
    source = tmp_path / 'source'
    source.mkdir()
    (source / '001.gph').write_bytes(b'graph fixture')
    digest = graph_inventory_sha256(source)
    root = tmp_path / 'published'
    def interrupted_copy(src, dst, **kwargs):
        dst.mkdir(parents=True)
        (dst / '001.gph').write_bytes(b'partial')
        raise OSError('simulated full disk')
    monkeypatch.setattr(module.shutil, 'copytree', interrupted_copy)
    with pytest.raises(OSError):
        install_graph_artifact(source, root, expected_sha256=digest)
    assert not (root / digest).exists()
    assert not list(root.glob('.install-*'))


def test_install_rejects_damaged_existing_package_without_overwriting(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / '001.gph').write_bytes(b'graph fixture')
    digest = graph_inventory_sha256(source)
    root = tmp_path / 'published'
    damaged = root / digest / 'tiles'
    damaged.mkdir(parents=True)
    (damaged / '001.gph').write_bytes(b'damaged')
    with pytest.raises(RoadNetworkUnavailable, match='checksum_mismatch'):
        install_graph_artifact(source, root, expected_sha256=digest)
    assert (damaged / '001.gph').read_bytes() == b'damaged'
