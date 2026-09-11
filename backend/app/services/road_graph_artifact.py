"""Local graph inventory, shared by publication and routing-worker startup.

Only deployment-controlled roots are accepted here, never HTTP input. Published
directories must be immutable and mounted read-only in the routing worker; this
check does not protect against a privileged writer changing files after checking.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import shutil
import tempfile
import fcntl

from app.services.road_network_contracts import RoadNetworkBinding, RoadNetworkUnavailable


def graph_inventory_sha256(tile_dir: Path) -> str:
    """Same inventory format as the existing source-bound Valhalla verifier."""
    tile_dir = Path(tile_dir)
    if tile_dir.is_symlink() or not tile_dir.is_dir():
        raise RoadNetworkUnavailable('road_graph_directory_invalid')
    tiles = []
    def reject_unreadable(error):
        raise error

    for directory, directories, files in os.walk(
            tile_dir, followlinks=False, onerror=reject_unreadable):
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise RoadNetworkUnavailable('road_graph_link_forbidden')
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise RoadNetworkUnavailable('road_graph_nonregular_file')
            # No untracked alternate input in the tile directory.
            if path.suffix != '.gph':
                raise RoadNetworkUnavailable('road_graph_unexpected_file')
            tiles.append(path)
    if not tiles:
        raise RoadNetworkUnavailable('road_graph_empty')
    inventory = hashlib.sha256()
    for path in sorted(tiles, key=lambda item: item.relative_to(tile_dir).as_posix()):
        relative = path.relative_to(tile_dir).as_posix()
        if any(character in relative for character in ('\t', '\n', '\r')):
            raise RoadNetworkUnavailable('road_graph_filename_invalid')
        # O_NOFOLLOW also rejects a leaf replaced by a symbolic link while opening.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RoadNetworkUnavailable('road_graph_nonregular_file')
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise RoadNetworkUnavailable('road_graph_changed_during_check')
        inventory.update(f'tiles/{relative}\t{before.st_size}\t{digest}\n'.encode())
    return inventory.hexdigest()


def verify_graph_artifact(root: Path, binding: RoadNetworkBinding) -> Path:
    """Resolve an opaque server-issued key; no stored path/config is executed."""
    if not re.fullmatch('[a-f0-9]{64}', binding.artifact_key):
        raise RoadNetworkUnavailable('road_graph_key_invalid')
    package = Path(root) / binding.artifact_key
    if package.is_symlink():
        raise RoadNetworkUnavailable('road_graph_link_forbidden')
    tiles = package / 'tiles'
    try:
        actual = graph_inventory_sha256(tiles)
    except OSError as error:
        raise RoadNetworkUnavailable('road_graph_io_failure') from error
    if actual != binding.graph_sha256:
        raise RoadNetworkUnavailable('road_graph_checksum_mismatch')
    return tiles


def install_graph_artifact(source_tiles: Path, root: Path, *, expected_sha256: str) -> str:
    """Atomically install a content-addressed graph, without marking any DB row ready.

    Both directories are operator-controlled, never request paths. Publishers
    share this filesystem lock. Source and destination inventories are checked;
    failed copies cannot replace a previous package. Database authorization and
    publication remain separate requirements.
    """
    if not re.fullmatch('[a-f0-9]{64}', expected_sha256):
        raise RoadNetworkUnavailable('road_graph_key_invalid')
    source_tiles, root = Path(source_tiles), Path(root)
    if root.is_symlink():
        raise RoadNetworkUnavailable('road_graph_link_forbidden')
    root.mkdir(parents=True, exist_ok=True)
    if graph_inventory_sha256(source_tiles) != expected_sha256:
        raise RoadNetworkUnavailable('road_graph_checksum_mismatch')
    lock_fd = os.open(root / '.publish.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        package = root / expected_sha256
        if package.is_symlink():
            raise RoadNetworkUnavailable('road_graph_link_forbidden')
        if package.exists():
            if graph_inventory_sha256(package / 'tiles') != expected_sha256:
                raise RoadNetworkUnavailable('road_graph_checksum_mismatch')
            return expected_sha256
        with tempfile.TemporaryDirectory(prefix='.install-', dir=root) as staging_name:
            staging = Path(staging_name)
            candidate = staging / 'package'
            # Preserve links so a source replaced during copying is rejected by
            # the inventory check rather than followed into another directory.
            shutil.copytree(source_tiles, candidate / 'tiles', symlinks=True)
            if graph_inventory_sha256(candidate / 'tiles') != expected_sha256:
                raise RoadNetworkUnavailable('road_graph_checksum_mismatch')
            for tile in (candidate / 'tiles').rglob('*.gph'):
                tile.chmod(0o444)
                with tile.open('rb') as stream:
                    os.fsync(stream.fileno())
            for directory, _, _ in os.walk(candidate, topdown=False):
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            os.rename(candidate, package)
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    return expected_sha256
