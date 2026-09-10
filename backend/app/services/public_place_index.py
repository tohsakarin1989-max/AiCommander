"""Versioned, read-only public gazetteer. No network or application DB access.

Paths are trusted artifact paths supplied by the package service, never API input.
Substring candidates use indexed 2/3-character grams (including Chinese), then an
exact substring check. Results are labels, not verified entrances or addresses.
"""

import json
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path


MAX_PLACES = 500_000


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _names(record: dict) -> list[str]:
    name = record.get("name")
    aliases = record.get("aliases", [])
    if not isinstance(name, str) or not isinstance(aliases, list) or len(aliases) > 16:
        raise ValueError("invalid_place_name")
    result = []
    for value in [name, *aliases]:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
            raise ValueError("invalid_place_name")
        if any(ord(c) < 32 for c in value):
            raise ValueError("invalid_place_name")
        if normalize(value) not in {normalize(item) for item in result}:
            result.append(value.strip())
    return result


def build_index(path: Path, records: Iterable[dict], source: dict) -> dict:
    """Atomically install a new index; a failed/repeated build never overwrites it."""
    if path.exists():
        raise FileExistsError(path)
    descriptor, filename = tempfile.mkstemp(prefix=".places-", suffix=".sqlite", dir=path.parent)
    os.close(descriptor)
    temporary = Path(filename)
    count = 0
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE places (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                    longitude REAL NOT NULL, latitude REAL NOT NULL,
                    location_role TEXT NOT NULL);
                CREATE TABLE names (
                    id INTEGER PRIMARY KEY, place_id TEXT NOT NULL, norm TEXT NOT NULL);
                CREATE TABLE grams (
                    gram TEXT NOT NULL, name_id INTEGER NOT NULL,
                    PRIMARY KEY (gram, name_id)) WITHOUT ROWID;
            """)
            with connection:
                for record in records:
                    count += 1
                    if count > MAX_PLACES:
                        raise ValueError("place_count_limit_exceeded")
                    names = _names(record)
                    identifier = record.get("id", "")
                    kind = record.get("kind", "")
                    if not isinstance(identifier, str) or not re.fullmatch(r"[nwr][1-9][0-9]{0,18}", identifier):
                        raise ValueError("invalid_place_id")
                    if not isinstance(kind, str) or not 1 <= len(kind) <= 80:
                        raise ValueError("invalid_place_kind")
                    lon, lat = record.get("longitude"), record.get("latitude")
                    if (any(type(value) not in (int, float) or not math.isfinite(value)
                            for value in (lon, lat)) or not -180 <= lon <= 180 or not -90 <= lat <= 90):
                        raise ValueError("invalid_place_coordinate")
                    if record.get("location_role") != "name_reference_point":
                        raise ValueError("invalid_location_role")
                    connection.execute("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?)",
                                       (identifier, names[0], kind, lon, lat, "name_reference_point"))
                    for name in names:
                        normalized = normalize(name)
                        name_id = connection.execute(
                            "INSERT INTO names(place_id,norm) VALUES (?,?)", (identifier, normalized)
                        ).lastrowid
                        grams = {normalized[i:i + size] for size in (2, 3)
                                 for i in range(len(normalized) - size + 1)}
                        connection.executemany("INSERT INTO grams VALUES (?,?)",
                                               [(gram, name_id) for gram in sorted(grams)])
                metadata = {"schema_version": "1", "source": json.dumps(source, ensure_ascii=False),
                            "place_count": str(count), "algorithm": "literal-ngram-v1"}
                connection.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
            connection.execute("PRAGMA optimize")
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"place_count": count, "schema_version": "1", "source": source}


def search_index(path: Path, query: str, *, limit: int = 20,
                 verified_content: bytes | None = None) -> dict:
    """Look up literal names in a verified local artifact, with bounded output."""
    if not isinstance(query, str) or not 2 <= len(query) <= 120:
        raise ValueError("invalid_place_query")
    query = normalize(query)
    if len(query) < 2 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("invalid_place_query")
    target = ":memory:" if verified_content is not None else path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(target, uri=True)) as connection:
        if verified_content is not None:
            # Query the exact bytes verified by the package service, not a file
            # that could have been replaced between checksum and SQLite open.
            connection.deserialize(verified_content)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        # Hard work bound, including malicious/corrupt package schemas. Import
        # verification must additionally authenticate and validate the artifact.
        budget = 0

        def stop_long_query() -> int:
            nonlocal budget
            budget += 1
            return int(budget > 10_000)

        connection.set_progress_handler(stop_long_query, 1000)
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        if metadata.get("schema_version") != "1":
            raise ValueError("unsupported_place_index")
        rows = connection.execute("""
            SELECT p.id, p.name, p.kind, p.longitude, p.latitude, p.location_role,
                   MIN(CASE WHEN n.norm=? THEN 0
                                WHEN instr(n.norm,?)=1 THEN 1 ELSE 2 END) AS match_rank
            FROM grams g JOIN names n ON n.id=g.name_id
            JOIN places p ON p.id=n.place_id
            WHERE g.gram=? AND instr(n.norm,?)>0
            GROUP BY p.id
            ORDER BY CASE WHEN p.kind IN ('city','region','administrative','county','district','province') THEN 0
                          WHEN p.kind IN ('town','village','hamlet','suburb') THEN 1
                          ELSE 2 END,
                     match_rank, length(p.name), p.name, p.id
            LIMIT ?
        """, (query, query, query[:3], query, limit + 1)).fetchall()
        return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit,
                "source": json.loads(metadata["source"]), "query": query,
                "search_algorithm": "literal-ngram-place-priority-v1",
                "location_role": "name_reference_point"}
