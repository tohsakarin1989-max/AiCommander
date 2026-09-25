#!/usr/bin/env python3
"""Disposable v5.4 PostgreSQL/Redis/ordinary-Worker and recovery evidence.

Run with the repository virtualenv and AIC_DISPOSABLE_FACILITIES=1. Uses only
installed images, synthetic fixtures, random loopback ports and owned tmpfs
containers. Evidence goes to ignored output/v54; no production URL is accepted.
This is not target-server, real-model or full production deployment acceptance.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4


PREVIOUS_REVISION = "e83f42c97ab3"
REVISION = "f94a53da8bc4"
POSTGRES_IMAGE = "aicommander-postgis-vector:16-0.8.6"
REDIS_IMAGE = "redis:7-alpine"
LABEL = "v54-facility-verification"


def main():
    if os.environ.get("AIC_DISPOSABLE_FACILITIES") != "1":
        raise RuntimeError("explicit_disposable_test_required")
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    evidence = root / "output/v54" / ("components-" + stamp)
    evidence.mkdir(parents=True, mode=0o700)
    os.chmod(evidence, 0o700)
    containers, worker, engines = [], None, []
    secret = secrets.token_hex(24)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
    env.update(
        PYTHONPATH=str(root / "backend"), ENVIRONMENT="test", SECRET_KEY=secrets.token_hex(32),
        ENABLE_VECTOR_DB="false", ENABLE_AGENT_LAB="false", AGENT_MODE="off",
        AGENT_USE_EXTERNAL_MODEL="false", AGENT_PROVIDER="deterministic", AUTO_CREATE_TABLES="false",
    )
    report = {
        "status": "running", "synthetic_only": True, "started_at": stamp,
        "host": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
        "target_server_verified": False, "real_model_verified": False,
        "login_flow_verified": False, "permission_api_uses_injected_test_principal": True,
        "agent_lab_enabled": False, "checks": {},
        "case_save_performance": "unchanged save path; reuse v5.3 report, not remeasured here",
    }
    evidence_sources = [
        "backend/app/api/facility_analysis.py", "backend/app/database.py",
        "backend/app/models/facility_summary.py", "backend/app/tasks/facility_summary_tasks.py",
        "backend/app/tasks/celery_app.py", "backend/app/services/facility_summary_service.py",
        "backend/app/services/facility_dossier_content.py", "backend/app/services/facility_condition_comparison.py",
    ]
    report["source_sha256"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in evidence_sources
    }

    def docker(*args, **kwargs):
        return subprocess.run(
            ["docker", *args], check=True, capture_output=True,
            env={**env, "POSTGRES_PASSWORD": secret}, timeout=60, **kwargs,
        )

    def container(image, port, *args):
        identifier = docker(
            "run", "-d", "--pull=never", "--name", "aic-v54-check-" + uuid4().hex[:12],
            "--label", "aicommander.disposable=" + LABEL, "-p", f"127.0.0.1::{port}",
            *args, image,
        ).stdout.decode().strip()
        containers.append(identifier)
        public_port = int(docker("port", identifier, str(port)).stdout.decode().strip().rsplit(":", 1)[1])
        return identifier, public_port

    def wait_until(predicate, message, seconds=45):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if worker is not None and worker.poll() is not None:
                raise RuntimeError("worker_stopped_early")
            time.sleep(0.25)
        raise RuntimeError(message)

    def stop_worker():
        nonlocal worker
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            worker = None

    try:
        for image in (POSTGRES_IMAGE, REDIS_IMAGE):
            details = json.loads(docker("image", "inspect", image).stdout)[0]
            report.setdefault("images", {})[image] = {
                "id": details["Id"], "architecture": details["Architecture"],
            }
        report["docker_version"] = docker("version", "--format", "{{.Server.Version}}").stdout.decode().strip()
        pg, pg_port = container(
            POSTGRES_IMAGE, 5432, "--tmpfs", "/var/lib/postgresql/data",
            "-e", "POSTGRES_USER=aic_facility_test", "-e", "POSTGRES_DB=aic_facility_test",
            "-e", "POSTGRES_PASSWORD",
        )
        redis_container, redis_port = container(REDIS_IMAGE, 6379, "--tmpfs", "/data")
        wait_until(
            lambda: subprocess.run(
                ["docker", "exec", pg, "pg_isready", "-h", "127.0.0.1", "-U", "aic_facility_test"],
                capture_output=True, timeout=5,
            ).returncode == 0, "database_not_ready",
        )
        url = f"postgresql://aic_facility_test:{secret}@127.0.0.1:{pg_port}/aic_facility_test"
        broker = f"redis://127.0.0.1:{redis_port}/0"
        env.update(DATABASE_URL=url, REDIS_URL=broker, CELERY_BROKER_URL=broker,
                   CELERY_RESULT_BACKEND=broker, AGENT_REDIS_QUEUE="unconsumed-agent-lab")
        with tempfile.TemporaryDirectory(prefix="aic-v54-components-") as temporary:
            os.chdir(temporary)  # Do not read workspace .env or a live database.
            os.environ.clear()
            os.environ.update(env)
            sys.path.insert(0, str(root / "backend"))
            from alembic import command
            from alembic.config import Config
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from sqlalchemy import create_engine, text
            from sqlalchemy.engine import make_url
            from sqlalchemy.orm import sessionmaker
            import app.models  # noqa: F401
            from app.api.facility_analysis import router
            from app.database import get_db
            from app.models.case import Case
            from app.models.case_pipeline import CaseAnalysisProfile
            from app.models.facility_summary import FacilityDerivedSummary
            from app.models.jurisdiction import JurisdictionAsset
            from app.models.map_foundation import OperationalArea, UserAreaScope
            from app.services.auth_service import AuthService
            from app.services.case_pipeline_service import CasePipelineService
            from app.services.jurisdiction_service import JurisdictionService
            from app.tasks.celery_app import celery_app

            config = Config(str(root / "backend/alembic.ini"))
            config.set_main_option("script_location", str(root / "backend/alembic"))
            command.upgrade(config, PREVIOUS_REVISION)
            engine = create_engine(url)
            engines.append(engine)
            sessions = sessionmaker(bind=engine, autoflush=False)

            def raw_rows(database_engine):
                with database_engine.connect() as connection:
                    return {table: list(connection.execute(text(
                        f"SELECT row_to_json({table})::text FROM {table} ORDER BY id"
                    )).scalars()) for table in ("cases", "jurisdiction_assets", "events")}

            with sessions() as db:
                user = AuthService.create_user(
                    db, username="synthetic-facility", display_name="合成设施验收",
                    password=secrets.token_urlsafe(24), role="viewer",
                )
                uid = user.id
                area_id = db.query(OperationalArea).filter_by(is_default=True).one().id
                hidden = OperationalArea(code="restricted-fixture", name="受限合成厂区", status="active")
                db.add(hidden)
                db.flush()
                hidden_area_id = hidden.id
                db.add(Case(case_number="SYNTHETIC-V53", operational_area_id=area_id,
                            occurred_time=datetime(2026, 9, 25), description="迁移前原始合成记录"))
                db.add_all([
                    JurisdictionAsset(external_id=external, name="合成同名井", asset_type="well",
                        operational_area_id=area_id, latitude=46.6, longitude=125.1,
                        attributes={"oil_type": "原油", "production_output": 10})
                    for external in ("SYNTHETIC-A", "SYNTHETIC-B")
                ])
                blocked = JurisdictionAsset(external_id="SYNTHETIC-HIDDEN", name="不得公开的合成井",
                    asset_type="well", operational_area_id=hidden_area_id)
                db.add(blocked)
                db.commit()
                hidden_id = blocked.id
                visible_id = db.query(JurisdictionAsset).filter_by(external_id="SYNTHETIC-A").one().id
            before_raw = raw_rows(engine)
            before_dump = docker("exec", pg, "pg_dump", "-U", "aic_facility_test", "-Fc", "aic_facility_test").stdout
            command.upgrade(config, REVISION)
            assert raw_rows(engine) == before_raw
            report["checks"]["incremental_upgrade_raw_data_unchanged"] = True
            report["schema_revision"] = REVISION
            with engine.connect() as conn:
                report["postgres_version"] = conn.execute(text("SHOW server_version")).scalar_one()
                report["extensions"] = dict(conn.execute(text("SELECT extname, extversion FROM pg_extension")).all())

            app = FastAPI()

            @app.middleware("http")
            async def fixture_principal(request, call_next):
                request.state.principal = SimpleNamespace(user_id=uid, role="viewer")
                return await call_next(request)

            def request_session():
                with sessions() as db:
                    yield db

            app.dependency_overrides[get_db] = request_session
            app.include_router(router, prefix="/api/facility-analysis")

            with TestClient(app) as http:
                first = http.get(f"/api/facility-analysis/assets/{visible_id}")
                assert first.status_code == 200, first.text
                assert first.json()["summary"]["state"] == "pending"
                region = http.get("/api/facility-analysis/region")
                assert region.status_code == 200, region.text
                assert region.json()["facilities"]["total"] == 2
                assert len({item["id"] for item in region.json()["facilities"]["items"]}) == 2
                assert http.get(f"/api/facility-analysis/assets/{hidden_id}").status_code == 404
                assert http.get(f"/api/facility-analysis/region?operational_area_id={hidden_area_id}").status_code == 403
                assert raw_rows(engine) == before_raw
                with sessions() as db:
                    assert db.query(FacilityDerivedSummary).count() == 0
                report["checks"]["authorized_read_same_name_ids_distinct_no_get_writes"] = True

                queue = celery_app.conf.task_default_queue
                entry = celery_app.conf.beat_schedule["reconcile-facility-catalog"]
                route = celery_app.amqp.router.route(entry.get("options", {}), entry["task"], (), {})
                assert route["queue"].name == queue
                report["beat_configuration"] = {"task": entry["task"], "interval_seconds": entry["schedule"],
                    "queue": queue, "executed_by_real_beat": False}
                with (evidence / "worker.log").open("w", encoding="utf-8") as log:
                    os.chmod(evidence / "worker.log", 0o600)
                    worker = subprocess.Popen(
                        [sys.executable, "-m", "celery", "-A", "app.tasks.celery_app:celery_app",
                         "worker", "--pool=solo", "--concurrency=1", "-Q", queue,
                         "--without-gossip", "--without-mingle", "--without-heartbeat", "--loglevel=WARNING"],
                        cwd=temporary, env=env, stdout=log, stderr=subprocess.STDOUT,
                    )

                    def revision(identifier):
                        with sessions() as db:
                            row = db.get(FacilityDerivedSummary, identifier)
                            return row.revision if row else None

                    celery_app.send_task(entry["task"], queue=queue)
                    wait_until(lambda: revision(visible_id) == 1, "worker_did_not_publish")
                    assert raw_rows(engine) == before_raw
                    report["checks"]["real_redis_default_worker_agent_off"] = True
                    with sessions() as db:
                        JurisdictionService.update_asset(db, visible_id, {"attributes": {
                            "oil_type": "原油", "production_output": 20,
                        }})
                    stale = http.get(f"/api/facility-analysis/assets/{visible_id}").json()
                    assert stale["summary"]["state"] == "stale"
                    celery_app.send_task(entry["task"], queue=queue)
                    wait_until(lambda: revision(visible_id) == 2, "worker_did_not_refresh")
                    refreshed = http.get(f"/api/facility-analysis/assets/{visible_id}").json()
                    assert refreshed["summary"]["state"] == "ready"
                    assert "生产及有效期资料" in refreshed["summary"]["changes"]
                    report["checks"]["source_change_explains_catalog_revision"] = True
                    stop_worker()

                with sessions() as db:
                    db.query(UserAreaScope).filter_by(user_id=uid).delete()
                    db.commit()
                assert http.get(f"/api/facility-analysis/assets/{visible_id}").status_code == 404
                with sessions() as db:
                    db.info["authorized_area_ids"] = [hidden_area_id]
                    assert db.query(FacilityDerivedSummary).filter_by(asset_id=visible_id).first() is None
                    assert db.query(FacilityDerivedSummary).filter_by(asset_id=hidden_id).first() is not None
                report["checks"]["revocation_and_orm_summary_scope"] = True
                with sessions() as db:
                    db.add(UserAreaScope(user_id=uid, operational_area_id=area_id, access_level="read"))
                    for number in range(1, 101):
                        db.add(JurisdictionAsset(external_id=f"PERF-{number:03d}", name=f"合成设施{number:03d}",
                            asset_type="well", operational_area_id=area_id, latitude=46.6 + number * .0001,
                            longitude=125.1, attributes={"oil_type": "原油", "production_status": "在产"}))
                    for number in range(1, 201):
                        row = Case(case_number=f"SYNTHETIC-AFTER-{number:03d}", operational_area_id=area_id,
                            occurred_time=datetime(2026, 9, 25), latitude=46.6 + number * .0001,
                            longitude=125.1, description="合成样本：井场发现软管，油品为原油。")
                        db.add(row)
                        db.flush()
                        payload = CasePipelineService.build_profile_payload(db, row)
                        db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=row.id, profile_version=1,
                            source_hash=payload["source_hash"], schema_version=payload["schema_version"],
                            dictionary_version=payload["dictionary_version"], payload=payload,
                            quality_score=50, analysis_readiness="partial", is_current=True))
                    db.commit()
                fixture_raw = raw_rows(engine)
                report["frozen_dataset"] = {
                    "authorized_facilities": 102, "authorized_cases": 201, "case_profiles": 200,
                    "restricted_facilities": 1, "seed_recipe": "v54-components-1",
                    "raw_sha256": hashlib.sha256(json.dumps(fixture_raw, sort_keys=True).encode()).hexdigest(),
                }
                report["performance_ms"] = {}
                for label, endpoint in {
                    "region_page20": "/api/facility-analysis/region?page_size=20",
                    "facility_dossier": f"/api/facility-analysis/assets/{visible_id}",
                }.items():
                    samples = []
                    for _ in range(5):
                        started = time.perf_counter()
                        response = http.get(endpoint)
                        elapsed = (time.perf_counter() - started) * 1000
                        assert response.status_code == 200, response.text
                        samples.append(round(elapsed, 3))
                    report["performance_ms"][label] = {"samples": samples, "first_read": samples[0],
                        "median": sorted(samples)[2], "observed_p95_nearest_rank": max(samples),
                        "boundary": "5 in-process API samples; local PostgreSQL; not target-server or browser latency"}
                assert raw_rows(engine) == fixture_raw

            after_dump = docker("exec", pg, "pg_dump", "-U", "aic_facility_test", "-Fc", "aic_facility_test").stdout
            for name, dump, revision in (
                ("aic_facility_restored", after_dump, REVISION),
                ("aic_facility_previous", before_dump, PREVIOUS_REVISION),
            ):
                docker("exec", pg, "createdb", "-U", "aic_facility_test", name)
                docker("exec", "-i", pg, "pg_restore", "-U", "aic_facility_test", "--exit-on-error",
                       "--no-owner", "-d", name, input=dump)
                restored = create_engine(make_url(url).set(database=name))
                engines.append(restored)
                with restored.connect() as conn:
                    assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
                    if revision == PREVIOUS_REVISION:
                        assert conn.execute(text("SELECT to_regclass('facility_derived_summaries')")).scalar_one() is None
                    else:
                        assert conn.execute(text("SELECT count(*) FROM facility_derived_summaries")).scalar_one() == 3
                assert raw_rows(restored) == (before_raw if revision == PREVIOUS_REVISION else fixture_raw)
            assert raw_rows(engine) == fixture_raw
            report["checks"]["separate_v53_and_v54_backup_restore"] = True
            report["checks"]["post_upgrade_raw_data_preserved"] = True
            report["backup_sha256"] = {"v53": hashlib.sha256(before_dump).hexdigest(),
                                        "v54": hashlib.sha256(after_dump).hexdigest()}
            report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "message": str(error).replace(secret, "[REDACTED]")[:2000]}
        raise
    finally:
        active_error = sys.exc_info()[0] is not None
        cleanup_errors = []
        stop_worker()
        for engine in engines:
            engine.dispose()
        for identifier in reversed(containers):
            try:
                label = docker("inspect", "-f", '{{index .Config.Labels "aicommander.disposable"}}', identifier).stdout.decode().strip()
                if label != LABEL:
                    raise RuntimeError("refuse_cleanup_unowned_container")
                docker("rm", "-f", "-v", identifier)
            except Exception as error:
                cleanup_errors.append({"container_id": identifier, "error_type": type(error).__name__})
        report["owned_resources_removed"] = not cleanup_errors
        if cleanup_errors:
            report["status"] = "failed"
            report["cleanup_errors"] = cleanup_errors
        report["source_changed_during_run"] = [
            name for name, digest in report["source_sha256"].items()
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
        ]
        (evidence / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(evidence / "result.json", 0o600)
        print(json.dumps({"status": report["status"], "evidence": str(evidence / "result.json"),
                          "checks": report["checks"], "owned_resources_removed": not cleanup_errors}, ensure_ascii=False), flush=True)
        if cleanup_errors and not active_error:
            raise RuntimeError("owned_resource_cleanup_incomplete_see_evidence")


if __name__ == "__main__":
    main()
