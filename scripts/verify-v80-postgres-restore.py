#!/usr/bin/env python3
"""Native, disposable v8.0 feedback backup/restore; never uses deployment config."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "aicommander_v80_restore_source"
TARGET = "aicommander_v80_restore_target"
DB_IMAGE = "aicommander-postgis-vector:16-0.8.6"
APP_IMAGE = "aicommander-v70-runtime:validation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new or empty evidence directory")
    parser.add_argument("--test-libraries", type=Path, help="existing pure Python pytest libraries, appended after image libraries")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Evidence directory must be empty; previous evidence is never overwritten.")
    libraries = args.test_libraries
    if libraries is None:
        candidates = sorted((ROOT / "backend/venv/lib").glob("python*/site-packages"))
        if len(candidates) != 1:
            raise SystemExit("Specify --test-libraries for an existing pytest installation; no download is performed.")
        libraries = candidates[0]
    libraries = libraries.resolve(strict=True)
    container = "aicommander-v80-restore-" + uuid4().hex[:10]

    def run(command, label, *, timeout=120):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        (output / f"{label}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"{label} failed; see {output / (label + '.log')}")
        return result.stdout.strip()

    images = {name: run(["docker", "image", "inspect", "--format", "{{.Id}}", name], f"image-{index}")
              for index, name in enumerate((DB_IMAGE, APP_IMAGE))}
    started = False
    try:
        run(["docker", "run", "--pull=never", "--rm", "--detach", "--name", container,
             "--network", "none", "--tmpfs", "/var/lib/postgresql/data:rw,size=512m",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", f"POSTGRES_DB={SOURCE}",
             "-v", f"{output}:/evidence", DB_IMAGE], "database-start")
        started = True
        for _ in range(40):
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", SOURCE], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("Isolated PostgreSQL did not become ready")

        def pytest_phase(phase, database, test):
            url = f"postgresql://postgres@127.0.0.1:5432/{database}"
            command = ["docker", "run", "--pull=never", "--rm", "--network", f"container:{container}",
                "--read-only", "--tmpfs", "/tmp:rw,size=512m", "--entrypoint", "python"]
            for key, value in {"DATABASE_URL": url, "AIC_V80_RESTORE_URL": url, "AIC_V80_RESTORE_PHASE": phase,
                "AIC_V80_RESTORE_EVIDENCE": "/evidence", "SECRET_KEY": "synthetic-restore-only-not-a-deployment-secret",
                "AUTH_REQUIRED": "false", "ENABLE_VECTOR_DB": "false", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}.items():
                command.extend(["-e", f"{key}={value}"])
            for path in ("app", "tests", "alembic", "alembic.ini", "pytest.ini"):
                command.extend(["-v", f"{ROOT / 'backend' / path}:/workspace/backend/{path}:ro"])
            command.extend(["-v", f"{libraries}:/host-test-packages:ro", "-v", f"{output}:/evidence",
                "-w", "/workspace/backend", APP_IMAGE, "-c",
                'import sys; sys.path.append("/host-test-packages"); import pytest; raise SystemExit(pytest.main('
                + repr([f"tests/test_case_feedback_restore_postgres_v80.py::{test}", "-q", "-o", "cache_dir=/tmp/pytest-cache",
                        "-o", "junit_family=xunit1", f"--junitxml=/evidence/{phase}.xml"]) + "))"])
            run(command, phase, timeout=180)

        pytest_phase("seed", SOURCE, "test_seed_legacy_and_new_feedback_before_native_backup")
        dump_version = run(["docker", "exec", container, "pg_dump", "--version"], "pg-dump-version")
        run(["docker", "exec", container, "pg_dump", "-U", "postgres", "-d", SOURCE,
             "--format=custom", "--file=/evidence/feedback-v80.dump"], "pg-dump")
        run(["docker", "exec", container, "createdb", "-U", "postgres", "--template=template0", TARGET], "create-target")
        run(["docker", "exec", container, "pg_restore", "-U", "postgres", "--exit-on-error", "--single-transaction",
             "--no-owner", "--no-privileges", "-d", TARGET, "/evidence/feedback-v80.dump"], "pg-restore")
        pytest_phase("verify", TARGET, "test_native_restore_preserves_schema_new_originals_and_feedback_semantics")
        report = {"synthetic_only": True, "images": images, "postgres_client": dump_version,
            "source_database": SOURCE, "target_database": TARGET, "network": "isolated, no exposed host ports",
            "restore": "pg_restore --exit-on-error --single-transaction --no-owner --no-privileges into empty database",
            "dump_sha256": hashlib.sha256((output / "feedback-v80.dump").read_bytes()).hexdigest(),
            "verification": json.loads((output / "restore-verification.json").read_text())}
        (output / "restore-report.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        print(json.dumps({"status": "passed", "evidence": str(output), "dump_sha256": report["dump_sha256"]}))
    finally:
        if started:
            run(["docker", "stop", "--timeout", "5", container], "database-cleanup", timeout=30)


if __name__ == "__main__":
    main()
