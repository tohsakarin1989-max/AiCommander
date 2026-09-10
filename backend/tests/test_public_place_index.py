import sqlite3

import pytest

from app.services.public_place_index import build_index, search_index


def place(identifier="n1", name="大庆市", aliases=None):
    return {"id": identifier, "name": name, "aliases": aliases or [],
            "kind": "city", "longitude": 125.1, "latitude": 46.6,
            "location_role": "name_reference_point"}


def test_chinese_partial_alias_and_normalized_search(tmp_path):
    target = tmp_path / "places.sqlite"
    build_index(target, [place(aliases=["Daqing", "大庆"])], {"source_sha256": "a" * 64})
    assert search_index(target, "大庆")["items"][0]["id"] == "n1"
    assert search_index(target, "庆市")["items"][0]["name"] == "大庆市"
    assert search_index(target, "ＤＡＱＩＮＧ")["items"][0]["id"] == "n1"
    assert search_index(target, "不存在")["items"] == []
    assert search_index(target, "大庆")["source"]["source_sha256"] == "a" * 64
    assert search_index(target, "大庆")["search_algorithm"] == "literal-ngram-place-priority-v1"


def test_exact_before_prefix_before_contains_and_stable_limit(tmp_path):
    path = tmp_path / "places.sqlite"
    build_index(path, [place("n3", "老大庆村"), place("n2", "大庆市"),
                       place("n1", "大庆")], {})
    assert [r["id"] for r in search_index(path, "大庆", limit=2)["items"]] == ["n1", "n2"]


def test_query_is_literal_not_sql_or_wildcards(tmp_path):
    path = tmp_path / "places.sqlite"
    build_index(path, [place(), place("n2", "测试%_名称")], {})
    assert search_index(path, "%_")["items"][0]["id"] == "n2"
    assert search_index(path, "' OR 1=1 --")["items"] == []
    with pytest.raises(ValueError):
        search_index(path, "庆")
    with pytest.raises(ValueError):
        search_index(path, "ab", limit=1000)


def test_build_failure_does_not_publish_partial_index(tmp_path):
    path = tmp_path / "places.sqlite"
    with pytest.raises(ValueError):
        build_index(path, [place(), place("n2", "")], {})
    assert not path.exists()


def test_no_overwrite_of_existing_index(tmp_path):
    path = tmp_path / "places.sqlite"
    build_index(path, [place()], {})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        build_index(path, [place("n2", "另一地点")], {})
    assert path.read_bytes() == before


def test_duplicate_id_fails_instead_of_merging_unrelated_locations(tmp_path):
    with pytest.raises(sqlite3.IntegrityError):
        build_index(tmp_path / "places.sqlite", [place(), place(name="另一个城市")], {})


@pytest.mark.parametrize("field,value", [("longitude", float("nan")),
                                       ("latitude", 91), ("id", "../file"),
                                       ("location_role", "verified_entrance")])
def test_invalid_record_rejected(tmp_path, field, value):
    record = place()
    record[field] = value
    with pytest.raises(ValueError):
        build_index(tmp_path / "places.sqlite", [record], {})


def test_query_never_creates_missing_database(tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        search_index(missing, "大庆")
    assert not missing.exists()


def test_city_name_has_priority_over_same_named_junction(tmp_path):
    path = tmp_path / "places.sqlite"
    junction = place("n1", "大庆")
    junction["kind"] = "motorway_junction"
    build_index(path, [junction, place("r2", "大庆市")], {})
    assert [item["id"] for item in search_index(path, "大庆")["items"]] == ["r2", "n1"]
