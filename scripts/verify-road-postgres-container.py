"""Disposable road migration/concurrency and custom-format backup restore drill.

Run with backend/venv/bin/python. Requires an already downloaded PostGIS image.
Never accepts a database URL, existing container, or business backup as input.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


def run(*args, timeout=60, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True,
                            timeout=timeout, **kwargs)
    if result.returncode:
        # This runner owns all inputs and uses only synthetic data/credentials.
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result.stdout.strip()


def main():
    if os.environ.get("AIC_DISPOSABLE_ROAD_PG") != "1":
        raise RuntimeError("explicit_disposable_drill_opt_in_required")
    root = Path(__file__).resolve().parents[1]
    marker = str(uuid.uuid4())
    image = run("docker", "image", "inspect", "--format", "{{.Id}}", "postgis/postgis:16-3.4-alpine")
    container = run("docker", "run", "--rm", "-d", "--label", f"aic.road-drill={marker}",
                    "-e", "POSTGRES_PASSWORD=disposable-road-check-only", "-e", "POSTGRES_DB=aic_road_test",
                    "-p", "127.0.0.1::5432", image)
    if not re.fullmatch(r"[a-f0-9]{64}", container):
        raise RuntimeError("unexpected_container_identifier")
    try:
        for attempt in range(30):
            try:
                # The image's initialization server exposes only a Unix socket;
                # wait for TCP so initialization/restart cannot look ready early.
                run("docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", timeout=5)
                break
            except subprocess.CalledProcessError:
                time.sleep(0.5)
        else:
            raise RuntimeError("temporary_database_not_ready")
        endpoint = run("docker", "port", container, "5432")
        if not re.fullmatch(r"127\.0\.0\.1:\d+", endpoint):
            raise RuntimeError("database_not_loopback_only")
        env = dict(os.environ, DATABASE_URL=f"postgresql://postgres:disposable-road-check-only@{endpoint}/aic_road_test")
        print(run(sys.executable, str(root / "scripts/verify-road-postgres.py"), env=env, timeout=180), flush=True)

        def sql(database, query):
            return run("docker", "exec", container, "psql", "-X", "-U", "postgres", "-d", database,
                       "-v", "ON_ERROR_STOP=1", "-At", "-c", query)

        tables = sql("aic_road_test", "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        if not tables or not all(re.fullmatch(r"[a-z_][a-z0-9_]*", table) for table in tables):
            raise RuntimeError("unexpected_table_names")
        assert int(sql("aic_road_test", "SELECT count(*) FROM internal_road_reviews WHERE connection_evidence IS NOT NULL")) > 0
        run("docker", "exec", container, "pg_dump", "-U", "postgres", "-Fc", "-f", "/tmp/road-check.dump", "aic_road_test")
        run("docker", "exec", container, "createdb", "-U", "postgres", "aic_road_restore")
        run("docker", "exec", container, "pg_restore", "-U", "postgres", "--exit-on-error", "--no-owner",
            "-d", "aic_road_restore", "/tmp/road-check.dump")
        assert sql("aic_road_restore", "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines() == tables
        for table in tables:
            # Canonical JSON compares every value (not merely row counts), including
            # geometry source JSON, timestamps, connection evidence and review notes.
            query = f'SELECT COALESCE(jsonb_agg(row ORDER BY row::text), \'[]\'::jsonb)::text FROM (SELECT to_jsonb(t) AS row FROM "{table}" t) q'
            assert sql("aic_road_test", query) == sql("aic_road_restore", query), table
        sequence_query = "SELECT jsonb_agg(to_jsonb(s) ORDER BY sequencename)::text FROM pg_sequences s WHERE schemaname='public'"
        assert sql("aic_road_test", sequence_query) == sql("aic_road_restore", sequence_query)
        print(json.dumps({"backup_restore": "passed", "public_tables_compared": len(tables),
                          "sequence_state_compared": True, "image_id": image,
                          "scope": "synthetic road records; not full deployment or map-file backup"}), flush=True)
    finally:
        label = run("docker", "inspect", "--format", '{{ index .Config.Labels "aic.road-drill" }}', container)
        if label != marker:
            raise RuntimeError("refusing_cleanup_of_unowned_container")
        run("docker", "stop", container)
        print("disposable_road_database_and_backup_removed", flush=True)


if __name__ == "__main__":
    main()
