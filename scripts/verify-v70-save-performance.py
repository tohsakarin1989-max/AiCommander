#!/usr/bin/env python3
"""Compare real authenticated creates/edits, not idempotent replays.

Reuses benchmark-case-save.py's isolated authenticated ASGI transport and
verify-v62-save-performance.py's 200 seed / 10 warmup / 50 sample workload.
Every worker owns a new synthetic SQLite file. Network connections are denied.
This is not target-server, PostgreSQL, concurrent-load or employee acceptance.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
from importlib.metadata import version
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "40030e9dabb10bff65a3dcc83c8287a97ee91d52"
WARMUP, SAMPLES, SEED_CASES = 10, 50, 200
LABELS = ("baseline", "candidate", "candidate_no_key")
CREATE_PAYLOAD = {
    "occurred_time": "2026-09-10T01:00:00", "operational_area_id": 1,
    "location": "合成地点", "description": "合成现场记录，发现软管，来源去向待核验。",
    "facility_type": "油罐车", "case_type": "涉油盗窃", "oil_type": "原油",
    "latitude": 46.61, "longitude": 125.11,
}
UPDATE_PAYLOAD = {"description": "合成补录记录，未确认来源去向，新增现场材料。"}


def percentile(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


def digest(folder):
    result = hashlib.sha256()
    for path in sorted(folder.rglob("*.py")):
        result.update(str(path.relative_to(folder)).encode() + b"\0" + path.read_bytes())
    return result.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def worker(backend, label, output, *, use_creation_key=None, strict_edit=False,
           prepare_edit=False, verify_audits=False):
    # Defaults preserve the v7.0 protocol. Later comparisons may explicitly
    # select the existing worker's creation and editing paths.
    creation_key = label == "candidate" if use_creation_key is None else use_creation_key
    backend = backend.resolve()
    output = output.resolve()
    with tempfile.TemporaryDirectory(prefix="aic-v70-synthetic-db-") as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f"sqlite:///{directory}/synthetic.sqlite", ENVIRONMENT="test",
            SECRET_KEY="synthetic-v70-benchmark-not-a-real-secret", AUTH_REQUIRED="true",
            SESSION_COOKIE_SECURE="false", AUTO_CREATE_TABLES="false",
            ENABLE_VECTOR_DB="false", ENABLE_AGENT_LAB="false", AGENT_MODE="off",
            AGENT_USE_EXTERNAL_MODEL="false", CASE_SEMANTIC_MODEL_ID="",
            ALLOWED_HOSTS="testserver", FRONTEND_URL="http://testserver",
            CORS_ORIGINS="http://testserver", REDIS_URL=f"unix://{directory}/absent.sock",
            CELERY_BROKER_URL="memory://", CELERY_RESULT_BACKEND="cache+memory://",
        )

        def deny_network(event, _args):
            if event == "socket.connect":
                raise RuntimeError("benchmark_network_access_forbidden")

        sys.addaudithook(deny_network)
        sys.path.insert(0, str(backend))
        from fastapi.testclient import TestClient
        from sqlalchemy import event, inspect
        from app.main import app
        from app.database import Base, SessionLocal, engine
        from app.models.case import Case
        from app.models.case_pipeline import OutboxEvent
        from app.models.case_source import CaseRevision
        from app.models.map_foundation import OperationalArea, UserAreaScope
        from app.models.user import User
        from app.services.auth_service import AuthService

        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code="synthetic-v70", name="合成测试厂区", is_default=True))
            db.add(User(id=1, username="synthetic-save", display_name="合成测试账号",
                        role="analyst", password_hash=AuthService.hash_password("Synthetic-save-123!")))
            db.flush()
            db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level="write"))
            for index in range(SEED_CASES):
                db.add(Case(case_number=f"SYNTHETIC-HISTORY-{index:04}", operational_area_id=1,
                    occurred_time=datetime(2026, 5, 1) + timedelta(hours=index),
                    location="合成地名", description="合成历史记录，使用软管转运原油，来源仍待核验。",
                    facility_type=("管线", "油罐车", "油库")[index % 3], case_type="涉油盗窃",
                    latitude=46.6 + (index % 20) * .001, longitude=125.1 + (index % 20) * .001))
            db.commit()

        # The same low-overhead attribution runs on every side. Cursor timings
        # exclude commits/fsync/Python and cannot alone explain full latency.
        active = None

        @event.listens_for(engine, "before_cursor_execute")
        def before_cursor(_conn, _cursor, statement, _parameters, context, _many):
            if active is not None:
                active["sql_counts"][statement.split(None, 1)[0].upper()] += 1
                context._benchmark_started_ns = time.perf_counter_ns()

        @event.listens_for(engine, "after_cursor_execute")
        def after_cursor(_conn, _cursor, _statement, _parameters, context, _many):
            if active is not None and hasattr(context, "_benchmark_started_ns"):
                active["cursor_ms"] += (time.perf_counter_ns() - context._benchmark_started_ns) / 1_000_000

        records = {"create": [], "update": []}
        created_ids = []
        with TestClient(app) as client:
            login = client.post("/api/auth/login", json={
                "username": "synthetic-save", "password": "Synthetic-save-123!"},
                headers={"Origin": "http://testserver"})
            assert login.status_code == 200, login.text
            for index in range(WARMUP + SAMPLES):
                headers = {"Origin": "http://testserver"}
                if creation_key:
                    headers["Idempotency-Key"] = f"synthetic-new-{index:04}"
                active = {"sql_counts": Counter(), "cursor_ms": 0.0}
                started = time.perf_counter_ns()
                response = client.post("/api/cases/", json=CREATE_PAYLOAD, headers=headers)
                active["elapsed_ms"] = (time.perf_counter_ns() - started) / 1_000_000
                create_record, active = active, None
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["description"] == CREATE_PAYLOAD["description"]
                assert body["id"] not in created_ids, "create_must_not_be_a_replay"
                created_ids.append(body["id"])

                update_path, update_payload = f'/api/cases/{body["id"]}', UPDATE_PAYLOAD
                if strict_edit:
                    update_path += "/edit-snapshot"
                if prepare_edit or strict_edit:
                    # Preparation is intentionally outside save latency and SQL
                    # attribution. The strict editor needs its source token.
                    prepared = client.get(update_path)
                    assert prepared.status_code == 200, prepared.text
                    snapshot = prepared.json()
                    if strict_edit:
                        assert snapshot["case"]["id"] == body["id"]
                        assert isinstance(snapshot["source_revision"], int)
                        update_payload = {"expected_revision": snapshot["source_revision"],
                                          "case_payload": UPDATE_PAYLOAD}
                    else:
                        assert snapshot["id"] == body["id"]
                active = {"sql_counts": Counter(), "cursor_ms": 0.0}
                started = time.perf_counter_ns()
                response = client.put(update_path, json=update_payload,
                                      headers={"Origin": "http://testserver"})
                active["elapsed_ms"] = (time.perf_counter_ns() - started) / 1_000_000
                update_record, active = active, None
                assert response.status_code == 200, response.text
                updated = response.json()["case"] if strict_edit else response.json()
                assert updated["description"] == UPDATE_PAYLOAD["description"]
                if index >= WARMUP:
                    records["create"].append(create_record)
                    records["update"].append(update_record)

        with SessionLocal() as db:
            counts = {
                "cases": db.query(Case).count(),
                "distinct_case_numbers": db.query(Case.case_number).distinct().count(),
                "case_revisions": db.query(CaseRevision).count(),
                "analysis_outbox_events": db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").count(),
            }
            assert counts["cases"] == SEED_CASES + WARMUP + SAMPLES
            assert counts["distinct_case_numbers"] == counts["cases"]
            assert counts["case_revisions"] == 2 * (WARMUP + SAMPLES)
            assert counts["analysis_outbox_events"] == 2 * (WARMUP + SAMPLES)
            if inspect(engine).has_table("case_submission_receipts"):
                from app.models.case_submission import CaseSubmissionReceipt
                counts["submission_receipts"] = db.query(CaseSubmissionReceipt).count()
                assert counts["submission_receipts"] == (WARMUP + SAMPLES if creation_key else 0)
            else:
                assert label == "baseline"
                counts["submission_receipts"] = 0
            if verify_audits:
                from app.models.user import AuditLog
                for method, operation in (("POST", "create"), ("PUT", "update")):
                    counts[f"{operation}_audit_records"] = db.query(AuditLog).filter(
                        AuditLog.action == "api.mutation", AuditLog.method == method,
                        AuditLog.status_code == 200, AuditLog.path.startswith("/api/cases"),
                    ).count()
                    assert counts[f"{operation}_audit_records"] == WARMUP + SAMPLES, "save_audit_must_persist"
        samples = {op: [row["elapsed_ms"] for row in values] for op, values in records.items()}
        write_json(output, {
            "samples_ms": samples,
            "p95_ms": {op: percentile(values) for op, values in samples.items()},
            "median_ms": {op: statistics.median(values) for op, values in samples.items()},
            "measurements": records, "counts": counts, "created_ids": created_ids,
            "new_keys": WARMUP + SAMPLES if creation_key else 0,
            "replay_requests": 0, "automatic_number": True,
        })
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-backend", type=Path)
    parser.add_argument("--label", choices=LABELS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker_backend:
        if not args.label or not args.output:
            parser.error("worker requires --label and --output")
        worker(args.worker_backend, args.label, args.output)
        return
    result_root = args.output or ROOT / "output/v70/case-save-performance"
    result_root.mkdir(parents=True, exist_ok=True)
    results = Path(tempfile.mkdtemp(prefix="run-", dir=result_root)).resolve()
    baseline = subprocess.check_output(["git", "rev-parse", f"{BASELINE}^{{commit}}"], cwd=ROOT, text=True).strip()
    assert subprocess.check_output(["git", "show", f"{baseline}:VERSION"], cwd=ROOT, text=True).strip() == "6.5.0-stable"
    # Each label appears once in each position in the three interleaved rounds.
    order = ("baseline", "candidate", "candidate_no_key",
             "candidate_no_key", "baseline", "candidate",
             "candidate", "candidate_no_key", "baseline")
    metadata = {
        "baseline_commit": baseline, "baseline_version": "6.5.0-stable",
        "platform": platform.platform(), "python": sys.version,
        "shared_dependency_versions": {name: version(name) for name in ("fastapi", "sqlalchemy", "pydantic", "httpx")},
        "database": "fresh-temporary-file-sqlite", "transport": "authenticated-TestClient-ASGI",
        "authenticated_role": "analyst", "seed_cases": SEED_CASES,
        "samples_per_operation_per_run": SAMPLES, "warmup_per_run": WARMUP,
        "run_order": order, "create_payload": CREATE_PAYLOAD, "update_payload": UPDATE_PAYLOAD,
        "input_sha256": hashlib.sha256(json.dumps([CREATE_PAYLOAD, UPDATE_PAYLOAD], sort_keys=True).encode()).hexdigest(),
        "network_allowed": False, "external_models_allowed": False,
        "postgresql_verified": False, "target_server_verified": False, "concurrent_workload_verified": False,
        "comparison_boundary": "full authenticated ASGI request latency; distinct new case per POST; original PUT edits",
        "instrumentation": "identical per-cursor count/timing on all variants; cursor times exclude commit/fsync and Python",
    }
    rows = []
    with tempfile.TemporaryDirectory(prefix="aic-v70-frozen-source-") as directory:
        frozen = Path(directory)
        shutil.copytree(ROOT / "backend/app", frozen / "candidate/backend/app",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "VERSION", frozen / "candidate/VERSION")
        archive = subprocess.check_output(["git", "archive", baseline, "backend/app", "VERSION"], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(frozen / "baseline", filter="data")
        metadata["source_hashes"] = {label: digest(frozen / label / "backend/app") for label in ("baseline", "candidate")}
        write_json(results / "metadata.json", metadata)
        # Preserve both exact measured trees, even if the live checkout changes.
        with tarfile.open(results / "frozen-sources.tar.gz", "w:gz") as bundle:
            for label in ("baseline", "candidate"):
                bundle.add(frozen / label, arcname=label)
        print(json.dumps({"evidence_directory": str(results), "source_hashes": metadata["source_hashes"]}), flush=True)
        for index, label in enumerate(order):
            source = frozen / ("baseline" if label == "baseline" else "candidate") / "backend"
            target = results / f"{index}-{label}.json"
            log_path = results / f"{index}-{label}.log"
            with log_path.open("w") as log:
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    "--worker-backend", str(source), "--label", label, "--output", str(target)],
                    cwd=frozen, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            if run.returncode:
                write_json(results / "failure.json", {"run": index, "label": label, "exit_code": run.returncode, "log": str(log_path)})
                raise RuntimeError(f"{label} failed; retained evidence: {log_path}")
            row = {"run": index, "label": label, **json.loads(target.read_text())}
            rows.append(row)
            print(json.dumps({"run": index, "label": label, "p95_ms": row["p95_ms"]}), flush=True)
    pooled = {label: {op: [v for row in rows if row["label"] == label for v in row["samples_ms"][op]]
                     for op in ("create", "update")} for label in LABELS}
    p95 = {label: {op: percentile(values) for op, values in operations.items()} for label, operations in pooled.items()}
    median = {label: {op: statistics.median(values) for op, values in operations.items()} for label, operations in pooled.items()}
    change = {label: {op: 100 * (p95[label][op] / p95["baseline"][op] - 1) for op in ("create", "update")}
              for label in ("candidate", "candidate_no_key")}
    passed = all(value <= 5 for value in change["candidate"].values())
    write_json(results / "report.json", {
        **metadata, "pooled_p95_ms": p95, "pooled_median_ms": median,
        "change_percent_vs_baseline": change, "local_five_percent_target_passed": passed,
        "records": rows,
    })
    print(json.dumps({"report": str(results / "report.json"), "pooled_p95_ms": p95,
                      "change_percent_vs_baseline": change, "local_five_percent_target_passed": passed}))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
