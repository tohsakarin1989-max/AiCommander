import subprocess
import sys
from pathlib import Path

import pytest

from app.release_checks.postgis_v36 import (
    REQUIRED_INDEXES,
    validate_disposable_database_name,
    validate_inventory,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_postgis_inventory_requires_head_extension_and_spatial_indexes():
    inventory = {
        "database": "aicommander_v36_verify_20260909_1",
        "revision": "a3e6b7c8d940",
        "postgis_version": "3.4.2",
        "indexes": sorted(REQUIRED_INDEXES),
        "invalid_case_coordinates": 0,
        "invalid_asset_coordinates": 0,
        "invalid_snapshot_coordinates": 0,
    }

    assert validate_inventory(inventory) == inventory


@pytest.mark.parametrize(
    "database_name",
    ["aicommander", "production", "aicommander_staging", "restore_check"],
)
def test_postgis_check_refuses_non_disposable_database(database_name):
    with pytest.raises(ValueError, match="disposable_database_required"):
        validate_disposable_database_name(database_name)


@pytest.mark.parametrize(
    "database_name",
    [
        "aicommander_v36_verify_20260909_1",
        "aicommander_postgis_verify_42",
    ],
)
def test_postgis_check_accepts_only_dedicated_verification_database(database_name):
    assert validate_disposable_database_name(database_name) == database_name


def test_postgis_inventory_rejects_missing_index_or_invalid_coordinate():
    with pytest.raises(RuntimeError, match="missing_indexes"):
        validate_inventory(
            {
                "database": "aicommander_v36_verify_1",
                "revision": "a3e6b7c8d940",
                "postgis_version": "3.4.2",
                "indexes": [],
                "invalid_case_coordinates": 0,
                "invalid_asset_coordinates": 0,
                "invalid_snapshot_coordinates": 0,
            }
        )

    with pytest.raises(RuntimeError, match="invalid_coordinates"):
        validate_inventory(
            {
                "database": "aicommander_v36_verify_1",
                "revision": "a3e6b7c8d940",
                "postgis_version": "3.4.2",
                "indexes": sorted(REQUIRED_INDEXES),
                "invalid_case_coordinates": 1,
                "invalid_asset_coordinates": 0,
                "invalid_snapshot_coordinates": 0,
            }
        )


def test_postgis_verifier_cli_has_a_read_only_help_path():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.release_checks.postgis_v36",
            "--help",
        ],
        cwd=REPOSITORY_ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "一次性验证数据库" in result.stdout


def test_postgis_rehearsal_script_is_isolated_and_records_evidence():
    source = (REPOSITORY_ROOT / "scripts/verify-v36-postgis.sh").read_text(
        encoding="utf-8"
    )

    assert "aicommander_v36_verify_" in source
    assert 'alembic upgrade head' in source
    assert "app.release_checks.postgis_v36" in source
    assert "dropdb" in source
    assert '"migration_status": "passed"' in source
    assert '"concurrency_status": "passed"' in source
    assert "POSTGIS_IMAGE" in source


def test_postgis_expression_indexes_keep_the_cast_inside_index_parentheses():
    first = (
        REPOSITORY_ROOT
        / "backend/alembic/versions/b8f1c2d3e405_map_foundation_v31.py"
    ).read_text(encoding="utf-8")
    second = (
        REPOSITORY_ROOT
        / "backend/alembic/versions/c9a2d3e4f506_offline_maps_v32.py"
    ).read_text(encoding="utf-8")
    migrations = f"{first}\n{second}"

    assert migrations.count("4326)::geography))") == 3
    assert "4326))::geography)" not in migrations


def test_offline_map_acceptance_cli_and_script_are_isolated():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.release_checks.offline_map_v36",
            "--help",
        ],
        cwd=REPOSITORY_ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "离线地图包" in result.stdout

    source = (REPOSITORY_ROOT / "scripts/verify-v36-offline-map.sh").read_text(
        encoding="utf-8"
    )
    module_source = (
        REPOSITORY_ROOT / "backend/app/release_checks/offline_map_v36.py"
    ).read_text(encoding="utf-8")
    assert "MAP_BUNDLE_FILE" in source
    assert "app.release_checks.offline_map_v36" in source
    assert "--retain-artifact" in source
    assert "network_isolation=passed" in source
    assert "rollback_status" in module_source


def test_release_rehearsal_supports_unreleased_candidate_without_changing_version():
    rehearsal = (REPOSITORY_ROOT / "scripts/rehearse-release.sh").read_text(
        encoding="utf-8"
    )
    preflight = (REPOSITORY_ROOT / "scripts/preflight-production.sh").read_text(
        encoding="utf-8"
    )
    compose = (REPOSITORY_ROOT / "docker-compose.production.yml").read_text(
        encoding="utf-8"
    )

    assert "REHEARSAL_APP_VERSION" in rehearsal
    assert "VERSION_FILE" in rehearsal
    assert 'ALEMBIC_TARGET="head"' in rehearsal
    assert "verify-v36-postgis.sh" in rehearsal
    assert "verify-v36-offline-map.sh" in rehearsal
    assert 'VERSION_FILE="${VERSION_FILE:-$ROOT_DIR/VERSION}"' in preflight
    assert 'POSTGRES_DB: "${DB_NAME:-aicommander}"' in compose
    assert 'DB_NAME: "${DB_NAME:-aicommander}"' in compose
