"""Validate exact gazetteer bytes and rebuild expected search grams in memory.

This binds provenance and search correctness, not completeness of real geography.
Never queries the application database or writes the supplied index.
"""
from contextlib import closing
import json
import math
import re
import sqlite3
import time
import unicodedata

from app.services.map_package_set import _object
from app.services.public_place_index import MAX_PLACES, normalize


def validate_place_index(content: bytes, *, source_sha256: str, region_sha256: str | set[str],
                         bounds: list[float], timeout_seconds: float = 60) -> dict:
    regions = {region_sha256} if isinstance(region_sha256, str) else region_sha256
    if (not isinstance(content, bytes) or not 0 < len(content) <= 64 * 1024 * 1024
            or not isinstance(regions, set) or not 1 <= len(regions) <= 1024
            or any(not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h)
                   for h in (source_sha256, *regions))
            or not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) not in (float, int) or (isinstance(v, float) and not math.isfinite(v)) for v in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -90 <= bounds[1] < bounds[3] <= 90
            or type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300):
        raise ValueError('invalid_place_validation_contract')
    deadline = time.monotonic() + timeout_seconds

    def check_time():
        if time.monotonic() >= deadline:
            raise ValueError('place_validation_timeout')

    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(content)
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA temp_store=MEMORY')
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            check_time()
            schema = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
            tables = {name for name, kind in schema if kind == 'table'}
            if tables != {'metadata', 'places', 'names', 'grams'} or any(kind not in ('table', 'index') for _, kind in schema):
                raise ValueError('invalid_place_schema')
            columns = {'metadata': ['key', 'value'],
                       'places': ['id', 'name', 'kind', 'longitude', 'latitude', 'location_role'],
                       'names': ['id', 'place_id', 'norm'], 'grams': ['gram', 'name_id']}
            for table, expected in columns.items():
                if [row[1] for row in db.execute(f'PRAGMA table_info({table})')] != expected:
                    raise ValueError('invalid_place_schema')
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('invalid_place_database')
            metadata = _object(db.execute('SELECT key,value FROM metadata LIMIT 5').fetchall())
            if (set(metadata) != {'schema_version', 'source', 'place_count', 'algorithm'}
                    or metadata['schema_version'] != '1' or metadata['algorithm'] != 'literal-ngram-v1'):
                raise ValueError('invalid_place_metadata')
            source = json.loads(metadata['source'], object_pairs_hook=_object)
            if (not isinstance(source, dict) or source.get('source_sha256') != source_sha256
                    or not isinstance(source.get('region_sha256'), str)
                    or source['region_sha256'] not in regions):
                raise ValueError('place_source_mismatch')
            db.execute('CREATE TEMP TABLE expected_primary (id TEXT PRIMARY KEY, norm TEXT)')
            db.execute('CREATE TEMP TABLE expected_grams (gram TEXT, name_id INTEGER, PRIMARY KEY(gram,name_id)) WITHOUT ROWID')
            points, count = set(), 0
            for identifier, name, kind, lon, lat, role in db.execute('SELECT * FROM places'):
                check_time()
                count += 1
                if count > MAX_PLACES:
                    raise ValueError('place_count_limit_exceeded')
                if (not isinstance(identifier, str) or not re.fullmatch(r'[nwr][1-9][0-9]{0,18}', identifier)
                        or not isinstance(name, str) or not 1 <= len(name) <= 120 or name != name.strip()
                        or any(ord(c) < 32 for c in name)
                        or not isinstance(kind, str) or not 1 <= len(kind) <= 80
                        or role != 'name_reference_point'):
                    raise ValueError('invalid_place_record')
                if (any(type(v) not in (float, int) or not math.isfinite(v) for v in (lon, lat))
                        or not bounds[0] <= lon <= bounds[2] or not bounds[1] <= lat <= bounds[3]):
                    raise ValueError('invalid_place_coordinate')
                db.execute('INSERT INTO expected_primary VALUES (?,?)', (identifier, normalize(name)))
                points.update(ord(c) for c in name if not c.isspace() and unicodedata.category(c) != 'Cf')
            if metadata['place_count'] != str(count) or count == 0:
                raise ValueError('place_count_mismatch')
            if db.execute('SELECT 1 FROM names n LEFT JOIN places p ON n.place_id=p.id WHERE p.id IS NULL LIMIT 1').fetchone():
                raise ValueError('place_name_orphan')
            if db.execute('SELECT id,norm FROM expected_primary EXCEPT SELECT place_id,norm FROM names LIMIT 1').fetchone():
                raise ValueError('place_primary_name_missing')
            if (db.execute('SELECT 1 FROM names GROUP BY place_id,norm HAVING count(*)>1 LIMIT 1').fetchone()
                    or db.execute('SELECT 1 FROM names GROUP BY place_id HAVING count(*)>17 LIMIT 1').fetchone()):
                raise ValueError('duplicate_or_excess_place_names')
            names, grams = 0, 0
            ids = set()
            for identifier, _, norm in db.execute('SELECT * FROM names'):
                check_time()
                names += 1
                if (names > 1_000_000 or type(identifier) is not int or identifier <= 0 or identifier in ids
                        or not isinstance(norm, str) or not 1 <= len(norm) <= 120
                        or normalize(norm) != norm or any(ord(c) < 32 for c in norm)):
                    raise ValueError('invalid_place_search_name')
                ids.add(identifier)
                expected = {norm[i:i + size] for size in (2, 3) for i in range(len(norm) - size + 1)}
                grams += len(expected)
                if grams > 4_000_000:
                    raise ValueError('place_gram_limit')
                db.executemany('INSERT INTO expected_grams VALUES (?,?)', [(g, identifier) for g in expected])
            if (db.execute('SELECT count(*) FROM grams').fetchone()[0] != grams
                    or db.execute('SELECT gram,name_id FROM expected_grams EXCEPT SELECT gram,name_id FROM grams LIMIT 1').fetchone()
                    or db.execute('SELECT gram,name_id FROM grams EXCEPT SELECT gram,name_id FROM expected_grams LIMIT 1').fetchone()):
                raise ValueError('place_grams_mismatch')
            check_time()
            return {'status': 'place_index_validated', 'publish_ready': False,
                    'place_count': count, 'name_count': names, 'gram_count': grams,
                    'primary_codepoints': sorted(points),
                    'source': {'source_sha256': source_sha256, 'region_sha256': source['region_sha256']},
                    'boundary': 'name_reference_point_not_verified_entrance'}
    except (sqlite3.Error, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid_place_index') from exc
