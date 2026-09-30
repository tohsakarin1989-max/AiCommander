"""Frozen synthetic create/update benchmark against published v5.4 source.

Both source trees are snapshotted before measuring. Only fresh temporary SQLite
databases are used; network access is denied. This is service-call latency, not
HTTP/PostgreSQL/target-server performance or a pre-edit dirty-worktree baseline.
"""
import hashlib
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

BASELINE = "56e63e455a97a6685925156be0eaab440702d60b"
WARMUP, SAMPLES, SEED_CASES = 10, 50, 200


def percentile(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


def worker(backend):
    from datetime import datetime, timedelta
    os.environ.update(DATABASE_URL="sqlite:///synthetic.sqlite", ENVIRONMENT="test",
        SECRET_KEY="synthetic-v60-performance-only", ENABLE_VECTOR_DB="false",
        ENABLE_AGENT_LAB="false", AGENT_MODE="off", AGENT_USE_EXTERNAL_MODEL="false",
        CASE_SEMANTIC_MODEL_ID="", CELERY_BROKER_URL="memory://", CELERY_RESULT_BACKEND="cache+memory://")

    def no_network(event, _args):
        if event == "socket.connect":
            raise RuntimeError("performance_network_forbidden")
    sys.addaudithook(no_network)
    sys.path.insert(0, str(backend))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import app.models  # noqa: F401
    from app.database import Base
    from app.models.case import Case
    from app.models.case_pipeline import OutboxEvent
    from app.models.map_foundation import OperationalArea
    from app.models.user import User
    from app.services.case_service import CaseService

    engine = create_engine("sqlite:///synthetic.sqlite")
    Base.metadata.create_all(engine)
    samples = {"create": [], "update": []}
    with Session(engine) as db:
        db.add(OperationalArea(id=1, code="synthetic-v60", name="合成测试厂区"))
        db.add(User(id=1, username="synthetic-v60", display_name="合成测试账号",
                    role="admin", password_hash="not-a-login"))
        db.flush()
        for index in range(SEED_CASES):
            db.add(Case(case_number=f"SYNTHETIC-{index}", operational_area_id=1,
                occurred_time=datetime(2026, 5, 1) + timedelta(hours=index),
                location="合成地名", description="合成历史记录，使用软管转运原油，来源仍待核验。",
                facility_type=("管线", "油罐车", "油库")[index % 3], case_type="涉油盗窃",
                latitude=46.6 + (index % 20) * .001,
                longitude=125.1 + (index % 20) * .001))
        db.commit()
        db.info.update(principal_user_id=1, authorized_area_ids=(1,), area_access_levels={1: "manage"})
        for index in range(WARMUP + SAMPLES):
            start = time.perf_counter_ns()
            case = CaseService.create_case(db, case_number=f"SYNTHETIC-NEW-{index}",
                operational_area_id=1, occurred_time=datetime(2026, 5, 3),
                location="合成地点", description="合成现场记录，发现软管，来源去向待核验。",
                facility_type="油罐车", case_type="涉油盗窃", oil_type="原油",
                latitude=46.61, longitude=125.11)
            create_ms = (time.perf_counter_ns() - start) / 1_000_000
            start = time.perf_counter_ns()
            CaseService.update_case(db, case.id, description="合成补录记录，未确认来源去向，新增现场材料。")
            update_ms = (time.perf_counter_ns() - start) / 1_000_000
            if index >= WARMUP:
                samples["create"].append(create_ms)
                samples["update"].append(update_ms)
        assert db.query(Case).count() == SEED_CASES + WARMUP + SAMPLES
        assert db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").count() == 2 * (WARMUP + SAMPLES)
    engine.dispose()
    print(json.dumps({"samples_ms": samples,
        "p95_ms": {key: percentile(value) for key, value in samples.items()},
        "median_ms": {key: statistics.median(value) for key, value in samples.items()}}))


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="aic-v60-performance-") as folder:
        area = Path(folder)
        archive = subprocess.check_output(["git", "archive", BASELINE, "backend/app"], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(area / "baseline", filter="data")
        frozen = area / "candidate" / "backend" / "app"
        shutil.copytree(root / "backend/app", frozen, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        digest = hashlib.sha256()
        for path in sorted(frozen.rglob("*.py")):
            digest.update(str(path.relative_to(frozen)).encode() + b"\0" + path.read_bytes())
        rows = []
        for index, label in enumerate(("baseline", "candidate", "candidate", "baseline", "baseline", "candidate")):
            run_dir = area / f"run-{index}"
            run_dir.mkdir()
            environment = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker",
                str(area / label / "backend")], cwd=run_dir, env=environment,
                capture_output=True, text=True, timeout=90)
            if run.returncode:
                raise RuntimeError(f"{label} synthetic benchmark failed: {run.stderr[-3000:]}")
            row = {"label": label, **json.loads(run.stdout.splitlines()[-1])}
            rows.append(row)
            print(json.dumps({"run": index, "label": label, "p95_ms": row["p95_ms"]}), flush=True)
    p95 = {label: {operation: percentile([sample for row in rows if row["label"] == label
            for sample in row["samples_ms"][operation]]) for operation in ("create", "update")}
            for label in ("baseline", "candidate")}
    change = {key: 100 * (p95["candidate"][key] / p95["baseline"][key] - 1) for key in ("create", "update")}
    report = {"baseline_commit": BASELINE, "candidate_app_sha256": digest.hexdigest(),
        "comparison_boundary": "published-v5.4 versus frozen-current-including-uncommitted-fixes",
        "platform": platform.platform(), "python": sys.version, "seed_cases": SEED_CASES,
        "samples_per_run_per_operation": SAMPLES, "warmup_per_run": WARMUP,
        "database": "temporary-file-sqlite", "network_allowed": False,
        "http_latency_measured": False, "postgresql_verified": False,
        "target_server_verified": False, "concurrent_workload_verified": False,
        "pooled_p95_ms": p95, "change_percent": change,
        "local_five_percent_target_passed": all(value <= 5 for value in change.values()), "records": rows}
    output = Path(tempfile.mkdtemp(prefix="aic-v60-performance-evidence-")) / "report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"report": str(output), "pooled_p95_ms": p95, "change_percent": change,
                      "local_five_percent_target_passed": report["local_five_percent_target_passed"]}))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]))
    else:
        main()
