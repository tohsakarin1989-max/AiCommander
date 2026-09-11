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
import tempfile
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
    evidence = Path(tempfile.mkdtemp(prefix='road-pg-v42-', dir=root / 'output/validation'))
    (evidence / 'report.json').write_text(json.dumps({'passed': False, 'status': 'started'}))
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
        print(run(sys.executable, str(root / 'scripts/verify-road-v42-postgres.py'), 'prepare', env=env, timeout=60), flush=True)

        def sql(database, query):
            return run("docker", "exec", container, "psql", "-X", "-U", "postgres", "-d", database,
                       "-v", "ON_ERROR_STOP=1", "-At", "-c", query)

        def canonical(table):
            if not re.fullmatch(r'[a-z_][a-z0-9_]*', table):
                raise RuntimeError('unexpected_table_name')
            return f'SELECT COALESCE(jsonb_agg(row ORDER BY row::text), \'[]\'::jsonb)::text FROM (SELECT to_jsonb(t) AS row FROM "{table}" t) q'

        baseline_tables = sql('aic_road_test', "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        baseline_rows = {table: sql('aic_road_test', canonical(table)) for table in baseline_tables}
        run('docker', 'exec', container, 'pg_dump', '-U', 'postgres', '-Fc', '-f', '/tmp/v41-before.dump', 'aic_road_test')
        print(run(sys.executable, str(root / 'scripts/verify-road-v42-postgres.py'), 'verify', env=env, timeout=120), flush=True)

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
        run('docker', 'exec', container, 'createdb', '-U', 'postgres', 'aic_v41_restore')
        run('docker', 'exec', container, 'pg_restore', '-U', 'postgres', '--exit-on-error', '--no-owner',
            '-d', 'aic_v41_restore', '/tmp/v41-before.dump')
        assert sql('aic_v41_restore', "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines() == baseline_tables
        for table in baseline_tables:
            assert sql('aic_v41_restore', canonical(table)) == baseline_rows[table], table
        assert sql('aic_v41_restore', 'SELECT version_num FROM alembic_version') == '4ef1b75a80e5'
        assert sql('aic_road_test', 'SELECT count(*) FROM cases WHERE id=992') == '1'
        assert sql('aic_road_restore', 'SELECT count(*) FROM cases WHERE id=992') == '1'
        vehicle_query = "SELECT road_vehicle_kind || ':' || height_m::text || ':' || gross_weight_t::text FROM case_vehicles WHERE case_id=992"
        assert sql('aic_road_test', vehicle_query) == 'truck:3.2:12.5'
        assert sql('aic_road_restore', vehicle_query) == 'truck:3.2:12.5'
        assert sql('aic_v41_restore', 'SELECT count(*) FROM cases WHERE id=992') == '0'
        result = {'passed': True, 'head': '82d5f19ec429', 'backup_restore': 'passed',
                  'public_tables_compared': len(tables), 'v41_restore_tables_compared': len(baseline_tables),
                  'sequence_state_compared': True, 'v42_new_original_case_preserved': True,
                  'vehicle_conditions_restored': True,
                  'image_id': image, 'container_removed': False,
                  'scope': 'synthetic PostgreSQL migration, concurrent artifact storage and database restore; not routing or full deployment'}
        print(json.dumps({"backup_restore": "passed", "public_tables_compared": len(tables),
                          "sequence_state_compared": True, "image_id": image,
                          "scope": "synthetic road records; not full deployment or map-file backup"}), flush=True)
    finally:
        label = run("docker", "inspect", "--format", '{{ index .Config.Labels "aic.road-drill" }}', container)
        if label != marker:
            raise RuntimeError("refusing_cleanup_of_unowned_container")
        run("docker", "stop", container)
        print("disposable_road_database_and_backup_removed", flush=True)
    result['container_removed'] = True
    (evidence / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f'evidence={evidence}', flush=True)


if __name__ == "__main__":
    main()
