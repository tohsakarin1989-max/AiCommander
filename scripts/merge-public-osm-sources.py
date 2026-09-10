#!/usr/bin/env python3
"""Merge same-time public OSM extracts without changing object topology.

Isolated build tool. No download, database write, cropping or map publication.
Conflicting duplicates fail; a manifest is written only after successful merge.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import osmium


ORDER = {"n": 0, "w": 1, "r": 2}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def signature(obj):
    """Copy transient buffer values, including ordered references and metadata."""
    if obj.is_node():
        geometry = (obj.location.x, obj.location.y)
    elif obj.is_way():
        geometry = tuple(node.ref for node in obj.nodes)
    else:
        geometry = tuple((member.type, member.ref, member.role) for member in obj.members)
    return (obj.type_str(), obj.id, obj.version, obj.visible, str(obj.timestamp),
            obj.changeset, obj.uid, obj.user, tuple(sorted((tag.k, tag.v) for tag in obj.tags)), geometry)


def signatures(path):
    for obj in osmium.FileProcessor(str(path)):
        yield signature(obj)


def merge(sources: list[Path], output: Path) -> dict:
    if not 2 <= len(sources) <= 8 or len({p.resolve() for p in sources}) != len(sources):
        raise ValueError("Two to eight distinct public source files required")
    records = []
    for path in sources:
        sha = digest(path)
        with osmium.io.Reader(str(path), osmium.osm.NOTHING) as reader:
            header = reader.header()
            stamp = header.get("osmosis_replication_timestamp")
            if header.has_multiple_object_versions:
                raise ValueError("History files are not supported")
        if not stamp:
            raise ValueError("Source replication timestamp required")
        try:
            parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ValueError("Invalid source timestamp") from exc
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != stamp:
            raise ValueError("Noncanonical source timestamp")
        records.append({"filename": path.name, "sha256": sha,
                        "bytes": path.stat().st_size, "timestamp": stamp})
    if len({record["timestamp"] for record in records}) != 1:
        raise ValueError("Source timestamp mismatch")
    output.mkdir(exist_ok=False)
    counts = {"n": 0, "w": 0, "r": 0}
    duplicates = 0
    per_source = [0] * len(sources)
    previous = None
    header = osmium.io.Header()
    header.set("generator", "AiCommander-public-source-merge-v1")
    header.set("osmosis_replication_timestamp", records[0]["timestamp"])
    # Deliberately do not copy a single province's bounding box or replication URL.
    with TemporaryDirectory(prefix=".merge-", dir=output) as temporary:
        candidate = Path(temporary) / "candidate.osm.pbf"
        with osmium.SimpleWriter(str(candidate), header=header) as writer:
            processors = [osmium.FileProcessor(str(path)) for path in sources]
            for group in osmium.zip_processors(*processors):
                present = [obj for obj in group if obj is not None]
                first = present[0]
                kind = first.type_str()
                key = (ORDER.get(kind, -1), first.id)
                if kind not in ORDER or first.id <= 0 or (previous is not None and key <= previous):
                    raise ValueError("Invalid source order or repeated object")
                if not first.visible or (first.is_node() and not first.location.valid()):
                    raise ValueError("Deleted object or invalid node location")
                if len(present) > 1:
                    expected = signature(first)
                    if any(signature(obj) != expected for obj in present[1:]):
                        raise ValueError(f"Conflicting public object: {kind}{first.id}")
                writer.add(first)  # Must consume the buffer before advancing processors.
                counts[kind] += 1
                duplicates += len(present) - 1
                for index, obj in enumerate(group):
                    per_source[index] += obj is not None
                previous = key
        if not all(per_source):
            raise ValueError("Empty public source")
        for path, record in zip(sources, records):
            if digest(path) != record["sha256"]:
                raise ValueError("Source changed during merge")
        result = {
            "schema_version": 1, "algorithm": "strict-same-time-merge-v1",
            "status": "merged_not_reference_validated", "parser": version("osmium"),
            "sources": records, "objects": counts, "source_object_counts": per_source,
            "duplicate_copies_removed": duplicates,
            "artifact": {"filename": "merged.osm.pbf", "sha256": digest(candidate),
                         "bytes": candidate.stat().st_size},
            "reference_completeness_verified": False, "routing_validated": False,
            "publish_ready": False,
        }
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        candidate.chmod(0o400)
        os.link(candidate, output / "merged.osm.pbf")  # No replacement of an existing target.
        with (output / "merge-manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(merge(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
