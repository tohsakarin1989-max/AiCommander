#!/usr/bin/env python3
"""Compare staged v7.0 saves with the frozen v7.1 strict daily editor.

The baseline is exported read-only from stage-0 Git index blob IDs. No commit,
write-tree, business database, external model or network connection is used.
The v7.0 worker remains backward-compatible; both arms explicitly use new keys.
Only save requests are timed: edit GET preparation is excluded on both sides.
"""
import argparse
import hashlib
import importlib.util
from importlib.metadata import version
import io
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = Path(__file__).with_name("verify-v70-save-performance.py")
LABELS = ("baseline", "candidate")
ORDER = ("baseline", "candidate", "candidate", "baseline", "baseline", "candidate")


def load_worker():
    spec = importlib.util.spec_from_file_location("save_benchmark_v70", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_index_manifest(root):
    raw = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z", "--", "backend/app", "VERSION"], cwd=root)
    entries = []
    for line in raw.split(b"\0"):
        if not line:
            continue
        metadata, raw_path = line.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ValueError(f"baseline requires resolved regular stage-0 files: {path}")
        if path != "VERSION" and not path.startswith("backend/app/"):
            raise ValueError(f"unexpected baseline path: {path}")
        if ".." in Path(path).parts or Path(path).is_absolute():
            raise ValueError("unsafe index path")
        entries.append({"path": path, "mode": mode, "blob": oid})
    if not entries or not any(row["path"] == "VERSION" for row in entries):
        raise ValueError("missing staged baseline")
    return sorted(entries, key=lambda row: row["path"])


def export_index_blobs(root, destination, entries):
    # A single immutable object-ID list captures the index exactly even if the
    # live index later changes. cat-file is read-only; no Git objects are made.
    request = "".join(row["blob"] + "\n" for row in entries).encode("ascii")
    result = subprocess.run(["git", "cat-file", "--batch"], input=request, cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    stream = io.BytesIO(result.stdout)
    for row in entries:
        oid, kind, size = stream.readline().decode("ascii").split()
        if oid != row["blob"] or kind != "blob":
            raise ValueError("baseline object mismatch")
        content = stream.read(int(size))
        if len(content) != int(size) or stream.read(1) != b"\n":
            raise ValueError("truncated baseline object")
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(int(row["mode"], 8) & 0o777)
    if stream.read():
        raise ValueError("unexpected baseline object output")
    if (destination / "VERSION").read_text().strip() != "7.0.0-stable":
        raise ValueError("baseline index must be the confirmed v7.0.0-stable checkpoint")


def summarize(worker, rows):
    pooled = {label: {operation: [sample for row in rows if row["label"] == label
                                 for sample in row["samples_ms"][operation]]
                      for operation in ("create", "update")} for label in LABELS}
    p95 = {label: {operation: worker.percentile(values) for operation, values in group.items()}
           for label, group in pooled.items()}
    median = {label: {operation: statistics.median(values) for operation, values in group.items()}
              for label, group in pooled.items()}
    delta = {operation: 100 * (p95["candidate"][operation] / p95["baseline"][operation] - 1)
             for operation in ("create", "update")}
    return {"pooled_p95_ms": p95, "pooled_median_ms": median,
            "change_percent_vs_baseline": delta,
            "local_five_percent_target_passed": all(value <= 5 for value in delta.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-backend", type=Path)
    parser.add_argument("--label", choices=LABELS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    worker = load_worker()
    if args.worker_backend:
        if not args.label or not args.output:
            parser.error("worker requires --label and --output")
        worker.worker(args.worker_backend, args.label, args.output, use_creation_key=True,
                      strict_edit=args.label == "candidate", prepare_edit=True, verify_audits=True)
        return
    result_root = args.output or ROOT / "output/v71/case-save-performance"
    result_root.mkdir(parents=True, exist_ok=True)
    results = Path(tempfile.mkdtemp(prefix="run-", dir=result_root)).resolve()
    entries = read_index_manifest(ROOT)
    manifest_bytes = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    metadata = {
        "baseline_source": "read-only-stage-0-index-blobs", "baseline_version": "7.0.0-stable",
        "index_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "platform": platform.platform(), "python": sys.version,
        "shared_dependency_versions": {name: version(name) for name in ("fastapi", "sqlalchemy", "pydantic", "httpx")},
        "database": "fresh-temporary-file-sqlite", "transport": "authenticated-TestClient-ASGI",
        "authenticated_role": "analyst", "seed_cases": worker.SEED_CASES,
        "samples_per_operation_per_run": worker.SAMPLES, "warmup_per_run": worker.WARMUP,
        "run_order": ORDER, "create_payload": worker.CREATE_PAYLOAD, "update_payload": worker.UPDATE_PAYLOAD,
        "input_sha256": hashlib.sha256(json.dumps([worker.CREATE_PAYLOAD, worker.UPDATE_PAYLOAD], sort_keys=True).encode()).hexdigest(),
        "network_allowed": False, "external_models_allowed": False, "replay_requests": 0,
        "postgresql_verified": False, "target_server_verified": False, "concurrent_workload_verified": False,
        "comparison_boundary": "v70 idempotent POST + legacy PUT versus v71 idempotent POST + strict edit-snapshot PUT",
        "edit_preparation": "GET case detail (baseline) or GET edit-snapshot (candidate), excluded from save time and SQL counts",
        "instrumentation": "same v70 cursor count/timing; excludes commit/fsync/Python from cursor timing, not request timing",
        "post_run_audit_check": "both arms must persist 60 create audits and 60 update audits; excluded from save timing",
        "threshold_percent": 5, "candidate_checkout_version": (ROOT / "VERSION").read_text().strip(),
    }
    rows = []
    with tempfile.TemporaryDirectory(prefix="aic-v71-frozen-source-") as directory:
        frozen = Path(directory)
        export_index_blobs(ROOT, frozen / "baseline", entries)
        shutil.copytree(ROOT / "backend/app", frozen / "candidate/backend/app",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "VERSION", frozen / "candidate/VERSION")
        scripts = frozen / "scripts"
        scripts.mkdir()
        for source in (Path(__file__).resolve(), WORKER_PATH):
            shutil.copy2(source, scripts / source.name)
        metadata["source_hashes"] = {label: worker.digest(frozen / label / "backend/app") for label in LABELS}
        metadata["script_sha256"] = {source.name: hashlib.sha256(source.read_bytes()).hexdigest()
                                      for source in sorted(scripts.iterdir())}
        worker.write_json(results / "index-manifest.json", entries)
        worker.write_json(results / "metadata.json", metadata)
        with tarfile.open(results / "frozen-sources.tar.gz", "w:gz") as archive:
            for name in (*LABELS, "scripts"):
                archive.add(frozen / name, arcname=name)
        print(json.dumps({"evidence_directory": str(results), "source_hashes": metadata["source_hashes"]}), flush=True)
        for index, label in enumerate(ORDER):
            target, log_path = results / f"{index}-{label}.json", results / f"{index}-{label}.log"
            with log_path.open("w") as log:
                try:
                    run = subprocess.run([sys.executable, str(scripts / Path(__file__).name),
                        "--worker-backend", str(frozen / label / "backend"), "--label", label, "--output", str(target)],
                        cwd=frozen, stdout=log, stderr=subprocess.STDOUT, timeout=300)
                except subprocess.TimeoutExpired:
                    worker.write_json(results / "failure.json", {"run": index, "label": label,
                        "reason": "worker_timeout", "timeout_seconds": 300, "log": str(log_path)})
                    raise
            if run.returncode:
                worker.write_json(results / "failure.json", {"run": index, "label": label,
                    "exit_code": run.returncode, "log": str(log_path)})
                raise RuntimeError(f"{label} failed; retained evidence: {log_path}")
            row = {"run": index, "round": index // 2 + 1, "label": label, **json.loads(target.read_text())}
            rows.append(row)
            print(json.dumps({"run": index, "label": label, "p95_ms": row["p95_ms"]}), flush=True)
    summary = summarize(worker, rows)
    report = {**metadata, **summary, "records": rows}
    worker.write_json(results / "report.json", report)
    print(json.dumps({"report": str(results / "report.json"), **summary}), flush=True)
    if not summary["local_five_percent_target_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
