from contextlib import closing
import json
import sqlite3

import pytest

from app.services.public_place_index import build_index
from app.services.place_index_validation import validate_place_index
from tests.test_public_place_index import place


def content(tmp_path, sql=None):
    path = tmp_path / 'places.sqlite'
    build_index(path, [place(aliases=['Daqing'])],
                {'source_sha256': 'a' * 64, 'region_sha256': 'b' * 64})
    if sql:
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(sql)
    return path.read_bytes()


def validate(data, **kwargs):
    return validate_place_index(data, source_sha256='a' * 64, region_sha256='b' * 64,
                                bounds=[122, 45, 127, 50], **kwargs)


def test_complete_index_and_primary_glyph_requirements(tmp_path):
    report = validate(content(tmp_path))
    assert report['place_count'] == 1
    assert report['name_count'] == 2
    assert report['primary_codepoints'] == sorted(map(ord, '大庆市'))
    assert report['source']['source_sha256'] == 'a' * 64
    assert report['publish_ready'] is False


@pytest.mark.parametrize('sql,reason', [
    ("DELETE FROM grams WHERE gram='大庆'", 'place_grams_mismatch'),
    ("INSERT INTO grams VALUES ('错误',1)", 'place_grams_mismatch'),
    ("UPDATE names SET place_id='n999'", 'place_name_orphan'),
    ("DELETE FROM names WHERE norm='大庆市'", 'place_primary_name_missing'),
    ("UPDATE places SET longitude=0", 'invalid_place_coordinate'),
    ("UPDATE places SET location_role='verified_entrance'", 'invalid_place_record'),
    ("UPDATE names SET norm='Daqing' WHERE norm='daqing'", 'invalid_place_search_name'),
    ("UPDATE metadata SET value='99' WHERE key='place_count'", 'place_count_mismatch'),
    ("CREATE VIEW injected AS SELECT * FROM places", 'invalid_place_schema'),
    ("UPDATE metadata SET value='{}' WHERE key='source'", 'place_source_mismatch'),
    ("UPDATE places SET name=' 大庆市 '", 'invalid_place_record'),
])
def test_transport_valid_but_inconsistent_database_rejected(tmp_path, sql, reason):
    with pytest.raises(ValueError, match=reason):
        validate(content(tmp_path, sql))


def test_invalid_sqlite_is_controlled_failure():
    with pytest.raises(ValueError):
        validate(b'not sqlite')


def test_timeout_is_enforced(tmp_path, monkeypatch):
    import app.services.place_index_validation as service
    data = content(tmp_path)
    ticks = iter([0, 100])
    monkeypatch.setattr(service.time, 'monotonic', lambda: next(ticks, 100))
    with pytest.raises(ValueError, match='place_validation_timeout'):
        validate(data, timeout_seconds=1)


def test_large_integer_bounds_are_rejected_without_overflow(tmp_path):
    with pytest.raises(ValueError):
        validate_place_index(content(tmp_path), source_sha256='a' * 64, region_sha256='b' * 64,
                             bounds=[-10**1000, 45, 127, 50])
