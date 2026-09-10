import base64
import hashlib
import io
import json
import sqlite3
import subprocess
import sys
import urllib.request
import zipfile

import pytest

import app.services.public_map_bundle_verifier as verifier_module
from app.services.offline_map_service import OfflineMapService
from app.services.public_map_bundle_builder import (
    PublicMapBundleBuilder,
    PublicTileFetchPolicy,
    _AllowlistedRedirectHandler,
)
from app.services.public_map_bundle_verifier import PublicMapBundleVerifier


REPOSITORY_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


PNG_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
JPEG_TILE = b"\xff\xd8\xffpublic-fixture"


def test_builder_creates_an_importable_public_only_bundle(tmp_path):
    output = tmp_path / "public-map.zip"
    requested: list[tuple[int, int, int]] = []

    def fetch(z: int, x: int, y: int) -> bytes:
        requested.append((z, x, y))
        return PNG_TILE

    report = PublicMapBundleBuilder.build(
        output_path=output,
        bounds=[125.10, 46.59, 125.11, 46.60],
        min_zoom=10,
        max_zoom=10,
        bundle_id="public-2026-09-09",
        provider="approved-xyz",
        source_version="2026-09-09",
        license_record="approved-license-record",
        attribution="approved public map",
        fetch_tile=fetch,
    )

    manifest, tile_bytes = OfflineMapService._read_validated_archive(output.read_bytes())
    assert report["tile_count"] == len(requested) >= 1
    assert report["sha256"]
    assert manifest["contains_internal_data"] is False
    assert manifest["provider"] == "approved-xyz"
    assert manifest["license"] == "approved-license-record"
    assert manifest["attribution"] == "approved public map"
    assert not any(key in manifest for key in ("cases", "wells", "pipelines", "tech_defense"))

    database = tmp_path / "readback.mbtiles"
    database.write_bytes(tile_bytes)
    connection = sqlite3.connect(database)
    try:
        metadata = dict(connection.execute("SELECT name, value FROM metadata").fetchall())
        stored = connection.execute(
            "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
        ).fetchall()
    finally:
        connection.close()
    assert metadata["format"] == "png"
    assert metadata["bounds"] == "125.1,46.59,125.11,46.6"
    assert len(stored) == len(requested)
    assert all(row[3] == PNG_TILE for row in stored)


def test_builder_is_atomic_and_rejects_mixed_tile_formats(tmp_path):
    output = tmp_path / "mixed.zip"
    calls = 0

    def fetch(_z: int, _x: int, _y: int) -> bytes:
        nonlocal calls
        calls += 1
        return PNG_TILE if calls == 1 else JPEG_TILE

    with pytest.raises(ValueError, match="mixed_tile_formats"):
        PublicMapBundleBuilder.build(
            output_path=output,
            bounds=[0, -1, 2, 1],
            min_zoom=2,
            max_zoom=2,
            bundle_id="mixed",
            provider="fixture",
            source_version="1",
            license_record="license",
            attribution="fixture",
            fetch_tile=fetch,
        )

    assert not output.exists()


def test_builder_rejects_huge_tile_ranges_before_fetching_or_materializing_all_tiles(
    tmp_path,
):
    fetch_calls = 0

    def fetch(_z: int, _x: int, _y: int) -> bytes:
        nonlocal fetch_calls
        fetch_calls += 1
        return PNG_TILE

    with pytest.raises(ValueError, match="tile_count_limit_exceeded"):
        PublicMapBundleBuilder.build(
            output_path=tmp_path / "too-wide.zip",
            bounds=[-180.0, -85.0, 180.0, 85.0],
            min_zoom=22,
            max_zoom=22,
            bundle_id="too-wide",
            provider="fixture",
            source_version="1",
            license_record="license",
            attribution="fixture",
            fetch_tile=fetch,
            max_tile_count=3,
        )

    assert fetch_calls == 0


@pytest.mark.parametrize(
    ("url", "allowed_hosts", "error"),
    [
        ("http://tiles.example/{z}/{x}/{y}.png", {"tiles.example"}, "https_required"),
        ("https://evil.example/{z}/{x}/{y}.png", {"tiles.example"}, "tile_host_not_allowed"),
        ("https://tiles.example/static.png", {"tiles.example"}, "invalid_tile_url_template"),
    ],
)
def test_public_tile_fetch_policy_rejects_unsafe_sources(url, allowed_hosts, error):
    with pytest.raises(ValueError, match=error):
        PublicTileFetchPolicy(url_template=url, allowed_hosts=allowed_hosts)


def test_public_tile_redirect_is_rejected_before_following_unapproved_host():
    handler = _AllowlistedRedirectHandler({"tiles.example"})

    with pytest.raises(ValueError, match="unsafe_tile_redirect"):
        handler.redirect_request(
            urllib.request.Request("https://tiles.example/1/1/1.png"),
            None,
            302,
            "Found",
            {},
            "https://metadata.internal/latest",
        )


def test_bundle_archive_contains_exactly_manifest_and_mbtiles(tmp_path):
    output = tmp_path / "public-map.zip"
    PublicMapBundleBuilder.build(
        output_path=output,
        bounds=[125.10, 46.59, 125.11, 46.60],
        min_zoom=10,
        max_zoom=10,
        bundle_id="public-members",
        provider="fixture",
        source_version="1",
        license_record="license",
        attribution="fixture",
        fetch_tile=lambda _z, _x, _y: PNG_TILE,
    )

    with zipfile.ZipFile(io.BytesIO(output.read_bytes())) as archive:
        assert sorted(archive.namelist()) == ["basemap.mbtiles", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["files"][0]["name"] == "basemap.mbtiles"


def test_release_verifier_reads_back_every_tile_and_manifest_count(tmp_path):
    output = tmp_path / "public-map.zip"
    PublicMapBundleBuilder.build(
        output_path=output,
        bounds=[125.10, 46.59, 125.11, 46.60],
        min_zoom=10,
        max_zoom=11,
        bundle_id="public-verify",
        provider="fixture",
        source_version="1",
        license_record="license",
        attribution="fixture",
        fetch_tile=lambda _z, _x, _y: PNG_TILE,
    )

    report = PublicMapBundleVerifier.verify_bytes(output.read_bytes())

    assert report["status"] == "passed"
    assert report["bundle_id"] == "public-verify"
    assert report["tile_count"] > 0
    assert report["min_zoom"] == 10
    assert report["max_zoom"] == 11


def test_release_verifier_rejects_a_false_manifest_tile_count(tmp_path):
    output = tmp_path / "public-map.zip"
    PublicMapBundleBuilder.build(
        output_path=output,
        bounds=[125.10, 46.59, 125.11, 46.60],
        min_zoom=10,
        max_zoom=10,
        bundle_id="public-false-count",
        provider="fixture",
        source_version="1",
        license_record="license",
        attribution="fixture",
        fetch_tile=lambda _z, _x, _y: PNG_TILE,
    )
    with zipfile.ZipFile(output, "r") as source:
        manifest = json.loads(source.read("manifest.json"))
        mbtiles = source.read("basemap.mbtiles")
    manifest["tile_count"] += 1
    manifest["files"][0]["sha256"] = hashlib.sha256(mbtiles).hexdigest()
    tampered = io.BytesIO()
    with zipfile.ZipFile(tampered, "w") as target:
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("basemap.mbtiles", mbtiles)

    with pytest.raises(ValueError, match="tile_count_mismatch"):
        PublicMapBundleVerifier.verify_bytes(tampered.getvalue())


@pytest.mark.parametrize(
    ("tile_format", "content"),
    [
        (
            "jpg",
            b"\xff\xd8"
            b"\xff\xc0\x00\x07\x08\x00\x01\x00\x01"
            b"\xff\xda\x00\x02not-jpeg-data\xff\xd9",
        ),
        (
            "webp",
            b"RIFF\x16\x00\x00\x00WEBPVP8 \x0a\x00\x00\x00"
            b"\x00\x00\x00\x9d\x01\x2anone",
        ),
    ],
)
def test_release_verifier_rejects_structured_but_undecodable_images(
    tile_format,
    content,
):
    with pytest.raises(ValueError, match="corrupt_tile_image"):
        PublicMapBundleVerifier._validate_tile_image(content, tile_format)


def test_release_verifier_rejects_tiles_outside_the_declared_coverage():
    with pytest.raises(ValueError, match="tile_coverage_mismatch"):
        PublicMapBundleVerifier._validate_declared_coverage(
            {
                "bounds": [-180.0, -85.0, 180.0, 85.0],
            },
            {
                "bounds": "-180,-85,180,85",
                "minzoom": "0",
                "maxzoom": "0",
            },
            {(0, 0, 0), (1, 0, 0)},
            0,
            0,
        )


def test_release_verifier_rejects_unbounded_declared_tile_count():
    with pytest.raises(ValueError, match="tile_count_limit_exceeded"):
        PublicMapBundleVerifier.verify_archive(
            {
                "tile_count": 100_001,
            },
            b"not-read-because-limit-is-checked-first",
        )


def test_release_verifier_counts_rows_before_decoding_an_unindexed_tile_table(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(verifier_module, "MAX_VERIFIED_TILE_COUNT", 3)
    path = tmp_path / "unindexed-over-limit.mbtiles"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    connection.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB)"
    )
    connection.executemany(
        "INSERT INTO tiles VALUES (0, 0, 0, ?)",
        [(PNG_TILE,)] * 4,
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="tile_count_limit_exceeded"):
        PublicMapBundleVerifier.verify_archive(
            {"tile_count": 3},
            path.read_bytes(),
        )


def test_release_verifier_rejects_a_tile_larger_than_two_megabytes():
    with pytest.raises(ValueError, match="tile_too_large"):
        PublicMapBundleVerifier._validate_tile_image(
            PNG_TILE + b"x" * (2 * 1024 * 1024),
            "png",
        )


@pytest.mark.parametrize(
    "script_name",
    ["build-public-map-bundle.py", "verify-public-map-bundle.py"],
)
def test_public_map_bundle_cli_tools_expose_help(script_name):
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts" / script_name), "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
