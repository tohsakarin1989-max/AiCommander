"""Retained v2/v3 workflows through real login and request area scoping.

Only synthetic records and local deterministic services are used. No API principal
or get_db override bypasses the production middleware/dependency integration.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app import database
from app.agent_runtime.runtime import AgentRunExecutor
from app.api import agent_runs, auth, graphs, jurisdiction, knowledge, map_foundation, situation, workbench
from app.config import settings
from app.models.agent_run import AgentRun
from app.models.case import Case, CaseEvidence
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset, KnowledgeReuseRecord
from app.models.map_foundation import JurisdictionAssetVersion, MapFeatureClaim, OperationalArea, UserAreaScope
from app.models.user import User
from app.security import AuthMiddleware
from app.services.auth_service import AuthService


@pytest.fixture
def retained_chain(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "AGENT_USE_EXTERNAL_MODEL", False)
    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    monkeypatch.setattr(settings, "ENABLE_AGENT_LAB", False)
    monkeypatch.setattr(settings, "AGENT_MODE", "off")
    password = "RetainedChain!2026"
    password_hash = AuthService.hash_password(password)
    with factory() as db:
        db.add_all([
            OperationalArea(id=1, code="north", name="北区", status="active", is_default=True,
                            boundary=[124, 46, 126, 47]),
            OperationalArea(id=2, code="south", name="南区", status="active"),
        ])
        db.flush()
        for user_id, role in enumerate(("admin", "analyst", "viewer"), 1):
            db.add(User(id=user_id, username=f"chain-{role}", display_name=role,
                        role=role, password_hash=password_hash))
            db.flush()
            if role != "admin":
                db.add(UserAreaScope(user_id=user_id, operational_area_id=1,
                                     access_level="write" if role == "analyst" else "read"))
        for case_id, area_id in ((1, 1), (2, 1), (3, 2)):
            db.add(Case(
                id=case_id, operational_area_id=area_id, case_number=f"RETAINED-{case_id}",
                occurred_time=datetime(2026, 9, 8, 2, 20), location="北区偏远井场",
                latitude=46.61, longitude=125.12, case_type="涉油盗窃", facility_type="管线",
                modus_operandi="软管抽油", source_type="技防预警", status="closed",
                description="现场发现软管和油桶，凌晨皮卡停留，已完成现场勘查。",
                quality_score=88, quality_issues={"missing_required": []},
            ))
            db.flush()
            db.add(CaseEvidence(case_id=case_id, evidence_type="photo", title="现场照片",
                                requirement_key="scene_photo"))
        db.commit()
    api = FastAPI()
    for module, prefix in ((auth, "auth"), (knowledge, "knowledge"), (workbench, "workbench"),
                           (graphs, "graphs"), (situation, "situation"),
                           (jurisdiction, "jurisdiction"), (agent_runs, "agent-runs")):
        api.include_router(module.router, prefix=f"/api/{prefix}")
    api.include_router(map_foundation.router, prefix="/api")
    api.add_middleware(AuthMiddleware, session_factory=factory, auth_required=True,
                       secure_cookie=False, allowed_origins=("http://testserver",))
    clients = {}
    for role in ("admin", "analyst", "viewer"):
        client = TestClient(api)
        response = client.post("/api/auth/login", json={"username": f"chain-{role}", "password": password})
        assert response.status_code == 200, response.text
        clients[role] = client
    try:
        yield SimpleNamespace(factory=factory, **clients)
    finally:
        for client in clients.values():
            client.close()
        engine.dispose()


def _post(client, path, body=None, expected=200):
    response = client.post(path, json=body)
    assert response.status_code == expected, response.text
    return response.json()


def _case_facts(factory):
    with factory() as db:
        return [(c.id, c.operational_area_id, c.case_number, c.occurred_time, c.location,
                 c.latitude, c.longitude, c.description, c.status, c.modus_operandi)
                for c in db.query(Case).order_by(Case.id)]


def _stage(client, case_id):
    response = client.get("/api/workbench/today")
    assert response.status_code == 200, response.text
    return next((t["stage"] for t in response.json()["tasks"] if t["source_id"] == case_id), "completed")


def test_experience_reuse_report_workbench_and_read_only_graph_situation_chain(retained_chain):
    scope = retained_chain
    client = scope.analyst
    facts = _case_facts(scope.factory)
    # Optional knowledge generation survives, but is not a compulsory daily task.
    assert client.get("/api/workbench/today").json()["tasks"] == []
    assert _stage(client, 1) == "completed"  # compatible key: no pending decision, not case closure
    _post(client, "/api/workbench/sessions", {
        "task_type": "experience_generate", "source_type": "case", "source_id": 1,
        "entry_path": "/case-intelligence?caseId=1",
    }, 409)
    generated = _post(client, "/api/knowledge/cases/1/experience-assets", expected=201)
    assert _stage(client, 1) == "experience_review"
    task = _post(client, "/api/workbench/sessions", {
        "task_type": "experience_review", "source_type": "case", "source_id": 1,
        "entry_path": "/case-intelligence?caseId=1",
    }, 201)["session"]
    assert task["entry_path"] == "/case-intelligence"
    _post(client, f"/api/knowledge/assets/{generated['id']}/review", {"status": "confirmed", "note": "人工核验"})
    assert _stage(client, 1) == "completed"
    recommended = client.get("/api/knowledge/cases/2/reuse-recommendations").json()
    assert generated["id"] in {item["asset_id"] for item in recommended["items"]}
    _post(client, "/api/knowledge/reuse-decisions", {
        "source_asset_id": generated["id"], "target_case_id": 2,
        "decision": "accepted", "purpose": "同类地点条件参考，逐项核验证据",
    }, 201)
    target_experience = _post(client, "/api/knowledge/cases/2/experience-assets", expected=201)
    _post(client, f"/api/knowledge/assets/{target_experience['id']}/review", {"status": "confirmed"})
    report = _post(client, "/api/knowledge/cases/2/report-snapshots", {
        "experience_asset_ids": [generated["id"]], "days": 365,
    }, 201)
    assert _stage(client, 2) == "report_review"
    assert report["content"]["reused_experience"][0]["asset_id"] == generated["id"]
    _post(client, f"/api/knowledge/assets/{report['id']}/review", {"status": "confirmed"})
    assert _stage(client, 2) == "completed"
    completed = _post(client, f"/api/workbench/sessions/{task['id']}/events", {"event": "completed"})
    assert completed["status"] == "completed"
    assert client.get("/api/workbench/sessions/active").json() is None
    with scope.factory() as db:
        before = (db.query(KnowledgeAsset).count(), db.query(KnowledgeReuseRecord).count())
    graph = client.get("/api/graphs/evidence/2").json()
    assert f"knowledge_asset:{report['id']}" in {node["id"] for node in graph["nodes"]}
    assert client.get("/api/graphs/evidence/2").json()["source_snapshot"]["data_version"] == graph["source_snapshot"]["data_version"]
    assert client.get("/api/graphs/evidence/3").status_code == 404
    serial = _post(client, "/api/graphs/serial", {"case_ids": [1, 2, 3]})
    assert {node["id"] for node in serial["nodes"]} == {1, 2}
    overview = client.get("/api/situation/overview", params={"as_of": "2026-09-10T12:00:00", "window_days": 14})
    assert overview.status_code == 200, overview.text
    assert overview.json()["summary"]["current_case_count"] == 2
    assert scope.viewer.get("/api/workbench/today").status_code == 200
    assert scope.viewer.post("/api/knowledge/cases/1/experience-assets").status_code == 403
    assert client.post("/api/knowledge/cases/3/experience-assets").status_code == 404
    assert _case_facts(scope.factory) == facts
    with scope.factory() as db:
        assert (db.query(KnowledgeAsset).count(), db.query(KnowledgeReuseRecord).count()) == before


def test_map_source_template_preview_ingest_conflict_reingest_and_scope_chain(retained_chain):
    scope = retained_chain
    client = scope.admin
    facts = _case_facts(scope.factory)
    source = _post(client, "/api/map-sources", {"source_key": "retained-ledger", "name": "隔离台账",
                   "source_type": "ledger", "trust_rank": 100, "operational_area_id": 1}, 201)
    template = _post(client, "/api/map-import-templates", {
        "source_id": source["id"], "name": "井点映射", "header_row": 1,
        "field_mapping": {"external_id": "编号", "name": "名称", "asset_type": "类型", "longitude": "经度", "latitude": "纬度"},
        "coordinate_system": "wgs84", "axis_order": "lon_lat", "coordinate_unit": "degree",
    }, 201)

    def upload(action, content, revision="rev-1", expected=None):
        response = client.post(f"/api/map-sources/{source['id']}/{action}",
                               params={"template_id": template["id"], "source_revision": revision},
                               files={"file": ("wells.csv", content.encode("utf-8-sig"), "text/csv")})
        assert response.status_code == (expected or (200 if action == "preview" else 201)), response.text
        return response.json()

    header = "编号,名称,类型,经度,纬度\n"
    content = header + "W1,北区井1,well,125.12,46.61\nW2,越界井,well,126.5,47.5\n"
    preview = upload("preview", content)
    assert preview["valid_rows"] == 1 and preview["quarantined_rows"] == 1
    with scope.factory() as db:
        assert db.query(JurisdictionAsset).count() == 0
        assert db.query(MapFeatureClaim).count() == 0
    ingested = upload("ingest", content)
    assert ingested["created_assets"] == 1
    assert ingested["quarantined_rows"] == 1
    assert upload("ingest", content, expected=200)["id"] == ingested["id"]
    assert client.get(f"/api/map-ingest-runs/{ingested['id']}").status_code == 200
    conflict = client.get("/api/map-conflicts").json()[0]
    assert conflict["error_code"] == "outside_operational_area"
    resolved = _post(client, f"/api/map-conflicts/{conflict['id']}/resolve", {"decision": "retry", "note": "核对源坐标后重导"})
    assert resolved["status"] == "awaiting_reingest"
    corrected = upload("ingest", header + "W1,北区井1,well,125.12,46.61\nW2,北区井2,well,125.13,46.62\n", "rev-2")
    assert corrected["created_assets"] == 1
    assert client.get("/api/map-conflicts").json() == []
    assert scope.analyst.get("/api/map-sources").status_code == 403
    assert scope.viewer.get("/api/map-conflicts").status_code == 403
    with scope.factory() as db:
        assert db.query(JurisdictionAsset).count() == 2
        assert db.query(JurisdictionAssetVersion).count() >= 2
        assert {asset.operational_area_id for asset in db.query(JurisdictionAsset)} == {1}
        db.add(JurisdictionAsset(name="南区不可见井", asset_type="well", status="active",
                                 operational_area_id=2, latitude=46.62, longitude=125.13))
        db.commit()
    assets = scope.analyst.get("/api/jurisdiction/assets")
    assert assets.status_code == 200, assets.text
    assert {asset["name"] for asset in assets.json()} == {"北区井1", "北区井2"}
    assert _case_facts(scope.factory) == facts


def test_agent_off_queue_failure_and_deterministic_core_remain_usable(retained_chain, monkeypatch):
    scope = retained_chain
    payload = {"task_type": "case_data_quality", "query": "检查所选案件完整性", "case_ids": [1]}
    assert scope.admin.post("/api/agent-runs", json=payload).status_code == 404
    assert scope.analyst.post("/api/agent-runs", json=payload).status_code == 403
    with scope.factory() as db:
        assert db.query(AgentRun).count() == 0
    monkeypatch.setattr(settings, "ENABLE_AGENT_LAB", True)
    monkeypatch.setattr(settings, "AGENT_MODE", "shadow")

    def unavailable(_run_id):
        raise ConnectionError("isolated queue unavailable")

    monkeypatch.setattr(agent_runs, "dispatch_agent_run", unavailable)
    failed = scope.admin.post("/api/agent-runs", json=payload)
    assert failed.status_code == 503
    with scope.factory() as db:
        run = db.query(AgentRun).one()
        assert run.status == "failed"
    queued_ids = []
    monkeypatch.setattr(agent_runs, "dispatch_agent_run", queued_ids.append)
    created = _post(scope.admin, "/api/agent-runs", payload, 202)
    assert queued_ids == [created["id"]]
    with scope.factory() as db:
        asyncio.run(AgentRunExecutor(narrator=None).execute(db, created["id"]))
    completed = scope.admin.get(f"/api/agent-runs/{created['id']}").json()
    assert completed["status"] == "completed"
    assert completed["result_summary"]["mode"] == "deterministic"
    assert completed["artifacts"]
    assert completed["model_provider"] is None
    events = scope.admin.get(f"/api/agent-runs/{created['id']}/events").json()
    assert events and events[-1]["status"] == "completed"
    monkeypatch.setattr(settings, "AGENT_MODE", "off")
    assert scope.admin.post(f"/api/agent-runs/{created['id']}/replay").status_code == 404
    with scope.factory() as db:
        assert db.query(AgentRun).count() == 2
    assert scope.analyst.get("/api/workbench/today").status_code == 200
    assert scope.analyst.get("/api/graphs/evidence/1").status_code == 200
    _post(scope.analyst, "/api/knowledge/cases/1/experience-assets", expected=201)
