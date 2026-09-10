"""在一次性 PostgreSQL/PostGIS 数据库中验证 v3.6 数据层。"""
from __future__ import annotations

import argparse
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import Engine, create_engine, text


EXPECTED_REVISION = "a3e6b7c8d940"
REQUIRED_INDEXES = {
    "ix_cases_postgis_point",
    "ix_assets_postgis_point",
    "ix_map_snapshot_features_postgis_point",
    "uq_map_snapshots_current_area",
    "uq_case_profiles_one_current",
}
_DISPOSABLE_DATABASE = re.compile(
    r"^aicommander_(?:v36|postgis)_verify_[a-zA-Z0-9_]+$"
)


def validate_disposable_database_name(database_name: str) -> str:
    """拒绝在正式库、暂存库或名称含糊的库上运行主动并发探针。"""
    if not _DISPOSABLE_DATABASE.fullmatch(database_name):
        raise ValueError("disposable_database_required")
    return database_name


def validate_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    validate_disposable_database_name(str(inventory.get("database") or ""))
    if inventory.get("revision") != EXPECTED_REVISION:
        raise RuntimeError(
            f"unexpected_revision:{inventory.get('revision') or 'missing'}"
        )
    if not inventory.get("postgis_version"):
        raise RuntimeError("postgis_extension_missing")

    missing = REQUIRED_INDEXES - set(inventory.get("indexes") or [])
    if missing:
        raise RuntimeError(f"missing_indexes:{','.join(sorted(missing))}")

    invalid_counts = {
        key: int(inventory.get(key) or 0)
        for key in (
            "invalid_case_coordinates",
            "invalid_asset_coordinates",
            "invalid_snapshot_coordinates",
        )
    }
    if any(invalid_counts.values()):
        raise RuntimeError(f"invalid_coordinates:{json.dumps(invalid_counts, sort_keys=True)}")
    return inventory


def collect_inventory(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()
        validate_disposable_database_name(str(database_name))
        postgis_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar_one_or_none()
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
        indexes = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname = ANY(:names)"
            ),
            {"names": sorted(REQUIRED_INDEXES)},
        ).scalars().all()
        invalid_case_coordinates = connection.execute(
            text(
                "SELECT count(*) FROM cases WHERE "
                "(longitude IS NOT NULL OR latitude IS NOT NULL) AND "
                "(longitude IS NULL OR latitude IS NULL OR "
                "longitude NOT BETWEEN -180 AND 180 OR latitude NOT BETWEEN -90 AND 90)"
            )
        ).scalar_one()
        invalid_asset_coordinates = connection.execute(
            text(
                "SELECT count(*) FROM jurisdiction_assets WHERE "
                "(longitude IS NOT NULL OR latitude IS NOT NULL) AND "
                "(longitude IS NULL OR latitude IS NULL OR "
                "longitude NOT BETWEEN -180 AND 180 OR latitude NOT BETWEEN -90 AND 90)"
            )
        ).scalar_one()
        invalid_snapshot_coordinates = connection.execute(
            text(
                "SELECT count(*) FROM map_snapshot_features WHERE "
                "(longitude IS NOT NULL OR latitude IS NOT NULL) AND "
                "(longitude IS NULL OR latitude IS NULL OR "
                "longitude NOT BETWEEN -180 AND 180 OR latitude NOT BETWEEN -90 AND 90)"
            )
        ).scalar_one()
    return {
        "database": str(database_name),
        "revision": revision,
        "postgis_version": postgis_version,
        "indexes": sorted(indexes),
        "invalid_case_coordinates": int(invalid_case_coordinates),
        "invalid_asset_coordinates": int(invalid_asset_coordinates),
        "invalid_snapshot_coordinates": int(invalid_snapshot_coordinates),
    }


def run_concurrency_probe(engine: Engine) -> dict[str, Any]:
    """验证 Worker 所依赖的 PostgreSQL 行锁与 SKIP LOCKED 行为。"""
    table_name = f"release_gate_claim_probe_{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)
    claimed: list[int] = []
    claimed_guard = threading.Lock()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE TABLE {table_name} ("
                    "id integer PRIMARY KEY, claimed boolean NOT NULL DEFAULT false)"
                )
            )
            connection.execute(
                text(f"INSERT INTO {table_name} (id) VALUES (1), (2)")
            )

        def claim_one() -> None:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                row_id = connection.execute(
                    text(
                        f"SELECT id FROM {table_name} WHERE claimed = false "
                        "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1"
                    )
                ).scalar_one()
                barrier.wait(timeout=5)
                connection.execute(
                    text(f"UPDATE {table_name} SET claimed = true WHERE id = :id"),
                    {"id": row_id},
                )
                with claimed_guard:
                    claimed.append(int(row_id))

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(claim_one) for _ in range(2)]
            for future in futures:
                future.result(timeout=10)

        if sorted(claimed) != [1, 2]:
            raise RuntimeError(f"concurrency_claim_collision:{claimed}")
        return {
            "workers": 2,
            "claimed_rows": sorted(claimed),
            "status": "passed",
        }
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def verify(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inventory = validate_inventory(collect_inventory(engine))
        concurrency = run_concurrency_probe(engine)
        return {
            "status": "passed",
            "expected_revision": EXPECTED_REVISION,
            "inventory": inventory,
            "concurrency": concurrency,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在一次性验证数据库中核对 v3.6 PostGIS 迁移、索引与并发行锁。"
    )
    parser.add_argument(
        "--database-url",
        help="一次性验证数据库连接；省略时读取应用 DATABASE_URL。",
    )
    args = parser.parse_args()

    if args.database_url:
        database_url = args.database_url
    else:
        from app.config import settings

        database_url = settings.DATABASE_URL
    print(json.dumps(verify(database_url), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
