"""Deep vector asset validation in the isolated map worker environment.

Requires the pinned map-build dependencies, not the core API environment.
This validates encoded content, not geographic completeness or road topology.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
from typing import Any
import zlib


MAX_FILE_BYTES = 8 * 1024 ** 3
MAX_TILE_BYTES = 2 * 1024 ** 2
MAX_RAW_BYTES = 8 * 1024 ** 2
MAX_TILES = 2_000_000


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_vector_metadata')
        result[key] = value
    return result


def _decode(payload: bytes, declared: set[str], label_fields=None):
    from google.protobuf.message import DecodeError
    from mapbox_vector_tile.decoder import TileData

    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = inflater.decompress(payload, MAX_RAW_BYTES + 1)
    if (len(raw) > MAX_RAW_BYTES or not inflater.eof or inflater.unused_data
            or inflater.unconsumed_tail):
        raise ValueError('invalid_vector_compression')
    try:
        tile = TileData(raw, default_options={'y_coord_down': True})
    except DecodeError as exc:
        raise ValueError('invalid_vector_protobuf') from exc
    if not tile.tile.IsInitialized():
        raise ValueError('invalid_vector_protobuf')
    names: set[str] = set()
    count = 0
    for layer in tile.tile.layers:
        if (layer.name not in declared or layer.name in names
                or layer.version != 2 or layer.extent != 4096):
            raise ValueError('invalid_vector_layer')
        names.add(layer.name)
        count += len(layer.features)
        if count > 100_000:
            raise ValueError('vector_feature_limit')
        for feature in layer.features:
            if feature.type not in (1, 2, 3) or len(feature.tags) % 2:
                raise ValueError('invalid_vector_feature')
            if any(k >= len(layer.keys) or v >= len(layer.values)
                   for k, v in zip(feature.tags[::2], feature.tags[1::2])):
                raise ValueError('invalid_vector_tags')
            # Validate command lengths before a decoder can iterate them. The
            # decoded geometry remains display geometry, never a routing graph.
            geometry = feature.geometry
            index = 0
            points = 0
            closed = False
            if not geometry or geometry[0] & 7 != 1:
                raise ValueError('invalid_vector_geometry')
            while index < len(geometry):
                command, length = geometry[index] & 7, geometry[index] >> 3
                index += 1
                if command not in (1, 2, 7) or length == 0:
                    raise ValueError('invalid_vector_geometry')
                if command == 7:
                    if feature.type != 3 or length != 1 or points < 3 or closed:
                        raise ValueError('invalid_vector_geometry')
                    closed = True
                else:
                    if feature.type == 1 and command != 1:
                        raise ValueError('invalid_vector_geometry')
                    if command == 1:
                        if (feature.type != 1 and length != 1
                                or feature.type == 2 and points == 1
                                or feature.type == 3 and points and not closed):
                            raise ValueError('invalid_vector_geometry')
                        points, closed = length, False
                    else:
                        if not points or closed:
                            raise ValueError('invalid_vector_geometry')
                        points += length
                    index += length * 2
                    if index > len(geometry):
                        raise ValueError('invalid_vector_geometry')
            if feature.type == 2 and points < 2 or feature.type == 3 and not closed:
                raise ValueError('invalid_vector_geometry')
    decoded = tile.get_message()  # Exercise complete property and geometry decoding.
    label_count, codepoints = 0, set()
    for layer_name, fields in (label_fields or {}).items():
        for feature in decoded.get(layer_name, {}).get('features', []):
            props = feature['properties']
            # Match coalesce(get(field1), ..., ''): empty strings do not fall
            # through, unlike truthiness-based fallback.
            text = next((props[key] for key in fields if props.get(key) is not None), '')
            if not isinstance(text, str) or len(text) > 4096:
                raise ValueError('invalid_label_value')
            if text:
                label_count += 1
                codepoints.update(ord(char) for char in text if not char.isspace())
                if len(codepoints) > 65536:
                    raise ValueError('label_codepoint_limit')
    return count, names, label_count, codepoints


def validate_vector_mbtiles(path: Path, expected_sha256: str, *, bounds: list[float],
                           min_zoom: int, max_zoom: int,
                           timeout_seconds: float = 900,
                           label_fields: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
    """Hash-copy into private storage, then scan every tile of that exact copy.

Call from a bounded background worker, not a request or case-save transaction.
The caller must still bind other package assets and validate geography before
publishing. No application database, production map or input file is changed.
"""
    if (not isinstance(expected_sha256, str)
            or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)
            or type(min_zoom) is not int or type(max_zoom) is not int
            or not 0 <= min_zoom <= max_zoom <= 19
            or not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) not in (int, float)
                   or (isinstance(v, float) and not math.isfinite(v)) for v in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -85.051129 <= bounds[1] < bounds[3] <= 85.051129
            or not 0 < timeout_seconds <= 3600):
        raise ValueError('invalid_vector_contract')
    deadline = time.monotonic() + timeout_seconds
    if label_fields is not None:
        if not isinstance(label_fields, dict) or not 1 <= len(label_fields) <= 128:
            raise ValueError('invalid_label_contract')
        for layer, fields in label_fields.items():
            if (not isinstance(layer, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', layer)
                    or not isinstance(fields, (tuple, list)) or not 1 <= len(fields) <= 4
                    or any(not isinstance(field, str) or not re.fullmatch(r'[a-z][a-z0-9_:]{0,79}', field)
                           for field in fields)):
                raise ValueError('invalid_label_contract')
            if len(set(fields)) != len(fields):
                raise ValueError('invalid_label_contract')
        label_fields = {layer: tuple(fields) for layer, fields in label_fields.items()}

    def check_time() -> None:
        if time.monotonic() >= deadline:
            raise ValueError('vector_validation_timeout')

    with tempfile.TemporaryDirectory(prefix='vector-validation-') as directory:
        target = Path(directory) / 'verified.mbtiles'
        digest = hashlib.sha256()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source, target.open('xb') as output:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
                raise ValueError('invalid_vector_file')
            copied = 0
            while chunk := source.read(1024 * 1024):
                check_time()
                copied += len(chunk)
                if copied > info.st_size:
                    raise ValueError('vector_file_changed')
                digest.update(chunk)
                output.write(chunk)
            if copied != info.st_size or digest.hexdigest() != expected_sha256:
                raise ValueError('vector_checksum_mismatch')
        connection = sqlite3.connect(f'{target.as_uri()}?mode=ro&immutable=1', uri=True)
        try:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RAW_BYTES + 1024)
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10_000)
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('invalid_vector_database')
            metadata_rows = connection.execute('SELECT name,value FROM metadata LIMIT 129').fetchall()
            if len(metadata_rows) > 128 or any(not isinstance(k, str) or not isinstance(v, str)
                                             or len(v) > 1024 ** 2 for k, v in metadata_rows):
                raise ValueError('invalid_vector_metadata')
            metadata = _json_object(metadata_rows)
            if (metadata.get('format') != 'pbf' or metadata.get('minzoom') != str(min_zoom)
                    or metadata.get('maxzoom') != str(max_zoom)):
                raise ValueError('vector_metadata_mismatch')
            declared_bounds = [float(v) for v in metadata['bounds'].split(',')]
            if len(declared_bounds) != 4 or any(not math.isfinite(v) or abs(v - b) > 0.00001
                                               for v, b in zip(declared_bounds, bounds)):
                raise ValueError('vector_bounds_mismatch')
            layers = json.loads(metadata['json'], object_pairs_hook=_json_object)['vector_layers']
            if not isinstance(layers, list) or not 1 <= len(layers) <= 128:
                raise ValueError('invalid_vector_metadata')
            declared = set()
            for layer in layers:
                name = layer['id']
                if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', name)
                        or name in declared):
                    raise ValueError('invalid_vector_metadata')
                declared.add(name)
            duplicate = connection.execute('SELECT 1 FROM tiles GROUP BY zoom_level,'
                'tile_column,tile_row HAVING count(*)>1 LIMIT 1').fetchone()
            if duplicate:
                raise ValueError('duplicate_vector_coordinate')
            count, features, nonempty = 0, 0, 0
            zoom_counts: dict[int, int] = {}
            observed: set[str] = set()
            label_count, codepoints = 0, set()
            # Repeated empty tiles are common; bound this cache independently of
            # map size. The digest binds the same compressed byte sequence.
            cache = {}
            for zoom, x, y, data in connection.execute(
                    'SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles'):
                check_time()
                count += 1
                if count > MAX_TILES:
                    raise ValueError('vector_tile_limit')
                if (any(type(v) is not int for v in (zoom, x, y)) or not min_zoom <= zoom <= max_zoom
                        or not 0 <= x < 2 ** zoom or not 0 <= y < 2 ** zoom
                        or not isinstance(data, bytes) or not 0 < len(data) <= MAX_TILE_BYTES):
                    raise ValueError('invalid_vector_tile')
                key = hashlib.sha256(data).digest()
                if key in cache:
                    tile_count, tile_layers, tile_labels = cache[key]
                    # Already merged on the first encounter of these bytes.
                    tile_codepoints = ()
                else:
                    tile_count, tile_layers, tile_labels, tile_codepoints = _decode(data, declared, label_fields)
                    check_time()
                    if len(cache) < 256:
                        cache[key] = (tile_count, tile_layers, tile_labels)
                zoom_counts[zoom] = zoom_counts.get(zoom, 0) + 1
                features += tile_count
                nonempty += int(tile_count > 0)
                observed.update(tile_layers)
                label_count += tile_labels
                codepoints.update(tile_codepoints)
                if len(codepoints) > 65536:
                    raise ValueError('label_codepoint_limit')
            if set(zoom_counts) != set(range(min_zoom, max_zoom + 1)) or not features:
                raise ValueError('vector_content_missing')
            check_time()
            report = {'status': 'vector_content_validated', 'publish_ready': False,
                    'sha256': expected_sha256, 'size_bytes': copied, 'tile_count': count,
                    'nonempty_tiles': nonempty, 'feature_count': features,
                    'zoom_counts': zoom_counts, 'layers': sorted(observed),
                    'bounds': bounds, 'geographic_coverage_verified': False,
                    'road_topology_verified': False}
            if label_fields is not None:
                report['label_audit'] = {'fields': label_fields, 'label_count': label_count,
                    'codepoints': sorted(codepoints), 'shaping_verified': False,
                    'note': 'All tile occurrences, not unique places; field selection only, not full style evaluation'}
            return report
        except (sqlite3.Error, KeyError, TypeError, IndexError, AssertionError,
                zlib.error, UnicodeError, RecursionError) as exc:
            raise ValueError('invalid_vector_content') from exc
        finally:
            connection.close()
