"""Immutable eligible PBF retention under a deployment-controlled root.

Keys are hashes, never request paths. This source is already permission-filtered;
it must not be reconstructed from an unfiltered public download for scenarios.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

VERSION = "retained-road-source-8.3-1"


def _hash(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("road_retained_source_not_regular")
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("road_retained_source_changed")
    return digest


def _package(root, digest):
    if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("road_retained_source_key_invalid")
    root = Path(root)
    package = root / ".sources" / digest
    if any(path.is_symlink() for path in (root, root / ".sources", package)):
        raise ValueError("road_retained_source_link_forbidden")
    return package


def verify_retained_source(root, descriptor):
    if (not isinstance(descriptor, dict) or descriptor.get("schema_version") != VERSION
            or descriptor.get("key") != descriptor.get("source_sha256")):
        raise ValueError("road_retained_source_binding_invalid")
    package = _package(root, descriptor["key"])
    metadata_path = package / "source-manifest.json"
    if metadata_path.is_symlink():
        raise ValueError("road_retained_source_link_forbidden")
    with metadata_path.open("r") as stream:
        metadata = json.load(stream)
    if metadata != descriptor:
        raise ValueError("road_retained_source_binding_invalid")
    source = package / "eligible.osm.pbf"
    if _hash(source) != descriptor["source_sha256"]:
        raise ValueError("road_retained_source_checksum_mismatch")
    return source


def install_retained_source(source, root, *, expected_source_sha256):
    package = _package(root, expected_source_sha256)
    source = Path(source)
    if source.is_symlink() or source.parent.is_symlink():
        raise ValueError("road_retained_source_link_forbidden")
    if _hash(source) != expected_source_sha256:
        raise ValueError("road_retained_source_checksum_mismatch")
    descriptor = {"schema_version": VERSION, "key": expected_source_sha256,
                  "source_sha256": expected_source_sha256}
    package.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(package.parent / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if package.exists():
            verify_retained_source(root, descriptor)
            return descriptor
        with tempfile.TemporaryDirectory(prefix=".retain-", dir=package.parent) as name:
            staging = Path(name)
            candidate = staging / "package"
            candidate.mkdir()
            destination = candidate / "eligible.osm.pbf"
            with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), "rb") as input_file:
                with destination.open("xb") as output:
                    shutil.copyfileobj(input_file, output)
                    output.flush()
                    os.fsync(output.fileno())
            if _hash(source) != expected_source_sha256 or _hash(destination) != expected_source_sha256:
                raise ValueError("road_retained_source_changed")
            destination.chmod(0o444)
            metadata = candidate / "source-manifest.json"
            with metadata.open("x") as output:
                json.dump(descriptor, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            metadata.chmod(0o444)
            os.rename(candidate, package)
    return descriptor
