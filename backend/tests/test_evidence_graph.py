import json
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import graphs
from app.database import Base, get_db
from app.models.agent_run import AgentArtifact, AgentRun
from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle
from app.models.chain_link import ChainLink
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset
from app.services.evidence_graph_service import EvidenceGraphError, EvidenceGraphService


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(graphs.router, prefix="/api/graphs")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _case(
    db: Session,
    number: str,
    *,
    latitude: float | None = 46.6,
    longitude: float | None = 125.1,
) -> Case:
    case = Case(
        case_number=number,
        occurred_time=datetime(2026, 9, 8, 2, 10),
        location="北区井场",
        latitude=latitude,
        longitude=longitude,
        case_type="涉油盗窃",
        facility_type="输油管线",
        modus_operandi="破坏阀门盗取原油",
        description="已完成结构化录入的测试案件。",
        status="processing",
        quality_score=88,
        quality_issues={"missing_required": []},
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def _knowledge(
    db: Session,
    case: Case,
    *,
    asset_type: str,
    status: str,
    refs: list,
) -> KnowledgeAsset:
    asset = KnowledgeAsset(
        asset_type=asset_type,
        source_case_id=case.id,
        version=1,
        title=f"{case.case_number}-{asset_type}",
        content={"summary": "仅供人工复核的测试摘要"},
        evidence_refs=refs,
        source_signature=f"signature-{case.id}-{asset_type}",
        source_data_version=f"source-{case.id}-{asset_type}",
        status=status,
        reviewer_label="测试复核员" if status == "confirmed" else None,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def test_evidence_graph_connects_sources_context_and_confirmed_knowledge_without_sensitive_values():
    db = _session()
    case = _case(db, "EG-001")
    case.involved_persons = [{"name": "旧结构姓名", "phone": "13900000000"}]
    case.vehicle_info = {"plate_number": "吉B54321"}
    case.location = "不应出现的人名和旧结构姓名常住地附近"
    case.modus_operandi = "联系13800000000或13900000000后驾驶黑A12345、吉B54321离开"
    evidence = CaseEvidence(
        case_id=case.id,
        evidence_type="document",
        title="不应出现的人名现场勘验记录",
        file_path="/secret/cases/EG-001/full-record.pdf",
        requirement_key="scene_record",
        is_sensitive=True,
    )
    db.add_all(
        [
            evidence,
            CasePerson(case_id=case.id, name="不应出现的人名", phone="13800000000", id_number="230000000000000000"),
            CaseVehicle(case_id=case.id, plate_number="黑A12345"),
            JurisdictionAsset(
                name="重点井-01",
                asset_type="well",
                latitude=46.605,
                longitude=125.105,
                status="active",
                verified=True,
                source="/private/maps/wells.xlsx",
                attributes={"日产量": 18.6, "is_high_production": True, "作业区": "北区"},
            ),
        ]
    )
    db.commit()
    db.refresh(evidence)
    asset = _knowledge(
        db,
        case,
        asset_type="experience_card",
        status="confirmed",
        refs=[{"id": f"case_evidence:{evidence.id}", "kind": "case_evidence", "summary": "现场勘验记录"}],
    )

    first = EvidenceGraphService.build_case_graph(db, case.id, well_radius_km=5)
    second = EvidenceGraphService.build_case_graph(db, case.id, well_radius_km=5)

    nodes = {item["id"]: item for item in first["nodes"]}
    assert nodes[f"case:{case.id}"]["layer"] == "subject"
    assert nodes[f"case_evidence:{evidence.id}"]["layer"] == "source"
    assert nodes[f"knowledge_asset:{asset.id}"]["status"] == "confirmed"
    assert nodes[f"well:1"]["status"] == "verified"
    assert any(
        edge["source"] == f"case_evidence:{evidence.id}"
        and edge["target"] == f"knowledge_asset:{asset.id}"
        and edge["status"] == "confirmed"
        for edge in first["edges"]
    )
    spatial = next(edge for edge in first["edges"] if edge["relation"] == "spatial_reference")
    assert spatial["status"] == "contextual"
    assert "不能证明" in spatial["boundary"]
    assert first["summary"]["traceability_rate"] == 100
    assert first["source_snapshot"]["data_version"] == second["source_snapshot"]["data_version"]

    serialized = json.dumps(first, ensure_ascii=False)
    for sensitive in (
        "/secret/cases/EG-001/full-record.pdf",
        "不应出现的人名",
        "13800000000",
        "230000000000000000",
        "黑A12345",
        "旧结构姓名",
        "13900000000",
        "吉B54321",
        "46.605",
        "125.105",
        "/private/maps/wells.xlsx",
    ):
        assert sensitive not in serialized
    assert nodes[f"case_evidence:{evidence.id}"]["label"] == f"案件材料 #{evidence.id}"


def test_evidence_graph_marks_drafts_unresolved_refs_and_inferred_links_for_review_without_mutation():
    db = _session()
    case = _case(db, "EG-REVIEW")
    related = _case(db, "EG-RELATED", latitude=46.62, longitude=125.12)
    link = ChainLink(
        case_id_a=case.id,
        case_id_b=related.id,
        link_type="upstream_transport",
        status="inferred",
        confidence=0.72,
        distance_km=2.3,
        time_diff_days=4,
        reasoning="仅基于时空和环节条件形成的待确认假设。",
    )
    db.add(link)
    db.commit()
    draft = _knowledge(
        db,
        case,
        asset_type="case_report",
        status="draft",
        refs=[{"id": "case_evidence:999", "summary": "已失效引用"}],
    )
    before = {
        "cases": db.query(Case).count(),
        "links": db.query(ChainLink).count(),
        "assets": db.query(KnowledgeAsset).count(),
    }

    payload = EvidenceGraphService.build_case_graph(db, case.id)

    issue_codes = {item["code"] for item in payload["review_queue"]}
    assert {"draft_knowledge_asset", "unresolved_evidence_ref", "inferred_chain_link"}.issubset(issue_codes)
    assert payload["summary"]["graph_health"] == "review_needed"
    assert payload["summary"]["traceability_rate"] == 0
    draft_node = next(item for item in payload["nodes"] if item["id"] == f"knowledge_asset:{draft.id}")
    assert draft_node["is_human_confirmed"] is False
    chain_edge = next(item for item in payload["edges"] if item["relation"] == "chain_hypothesis")
    assert chain_edge["status"] == "inferred"
    assert "必须人工确认" in chain_edge["boundary"]
    assert before == {
        "cases": db.query(Case).count(),
        "links": db.query(ChainLink).count(),
        "assets": db.query(KnowledgeAsset).count(),
    }


def test_evidence_graph_surfaces_missing_coordinates_and_agent_artifact_without_evidence():
    db = _session()
    case = _case(db, "EG-GAPS", latitude=None, longitude=None)
    case.location = ""
    case.modus_operandi = None
    run = AgentRun(
        task_type="case_quality",
        query="内部规则质检",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        status="completed",
        data_version="run-data-version",
        input_payload={},
        result_summary={},
        runtime_state={},
    )
    db.add(run)
    db.flush()
    db.add(
        AgentArtifact(
            run_id=run.id,
            artifact_type="quality_report",
            version=1,
            content={"sensitive_payload": "不得进入图谱"},
            evidence_refs=[],
            source_signature="artifact-signature",
        )
    )
    db.commit()

    payload = EvidenceGraphService.build_case_graph(db, case.id)

    issue_codes = [item["code"] for item in payload["review_queue"]]
    assert "missing_coordinates" in issue_codes
    assert "missing_case_field" in issue_codes
    assert "agent_artifact_without_evidence" in issue_codes
    agent_node = next(item for item in payload["nodes"] if item["type"] == "agent_artifact")
    assert agent_node["layer"] == "analysis"
    assert agent_node["status"] == "derived"
    assert "sensitive_payload" not in json.dumps(payload, ensure_ascii=False)


def test_evidence_graph_resolves_agent_map_asset_references_without_exposing_coordinates():
    db = _session()
    case = _case(db, "EG-AGENT-ASSET")
    asset = JurisdictionAsset(
        name="生产井-引用",
        asset_type="well",
        latitude=46.7,
        longitude=125.2,
        status="active",
        verified=True,
        attributes={"日产量": 12.5},
    )
    db.add(asset)
    db.flush()
    run = AgentRun(
        task_type="dual_domain_analysis",
        query="双域只读分析",
        case_ids=[case.id],
        asset_ids=[asset.id],
        mode="shadow",
        status="completed",
        data_version="agent-source-version",
        input_payload={},
        result_summary={},
        runtime_state={},
    )
    db.add(run)
    db.flush()
    db.add(
        AgentArtifact(
            run_id=run.id,
            artifact_type="dual_domain_analysis",
            version=1,
            content={"coordinates": [46.7, 125.2]},
            evidence_refs=[f"case:{case.id}", f"asset:{asset.id}"],
            source_signature="dual-signature",
        )
    )
    db.commit()

    payload = EvidenceGraphService.build_case_graph(db, case.id, well_radius_km=1)

    assert any(item["id"] == f"well:{asset.id}" for item in payload["nodes"])
    assert any(
        item["source"] == f"well:{asset.id}"
        and item["relation"] == "supports_agent_artifact"
        for item in payload["edges"]
    )
    assert "agent_artifact_without_evidence" not in {
        item["code"] for item in payload["review_queue"]
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "46.7" not in serialized
    assert "125.2" not in serialized


def test_evidence_graph_flags_each_unresolved_agent_reference_even_with_other_support():
    db = _session()
    case = _case(db, "EG-PARTIAL-REF")
    run = AgentRun(
        task_type="case_quality",
        query="只读质检",
        case_ids=[case.id],
        asset_ids=[],
        mode="shadow",
        status="completed",
        data_version="partial-ref-version",
        input_payload={},
        result_summary={},
        runtime_state={},
    )
    db.add(run)
    db.flush()
    db.add(
        AgentArtifact(
            run_id=run.id,
            artifact_type="quality_report",
            version=1,
            content={},
            evidence_refs=[f"case:{case.id}", "asset:999999"],
            source_signature="partial-ref-signature",
        )
    )
    db.commit()

    payload = EvidenceGraphService.build_case_graph(db, case.id)

    issue_codes = {item["code"] for item in payload["review_queue"]}
    assert "unresolved_agent_evidence_ref" in issue_codes
    assert any(
        item["relation"] == "missing_agent_support"
        for item in payload["edges"]
    )
    assert payload["summary"]["traceability_rate"] == 100


def test_evidence_graph_version_changes_with_source_data_and_api_validates_scope():
    db = _session()
    case = _case(db, "EG-API")
    client = _client(db)

    first = client.get(f"/api/graphs/evidence/{case.id}?well_radius_km=3&max_context_nodes=10")
    missing = client.get("/api/graphs/evidence/999")
    invalid = client.get(f"/api/graphs/evidence/{case.id}?well_radius_km=100")
    first_version = first.json()["source_snapshot"]["data_version"]

    case.facility_type = "油罐车"
    db.commit()
    changed = client.get(f"/api/graphs/evidence/{case.id}?well_radius_km=3&max_context_nodes=10")

    assert first.status_code == 200
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert changed.json()["source_snapshot"]["data_version"] != first_version
    assert changed.json()["boundary"]["read_only"] is True
    evidence_route = next(
        route
        for route in graphs.router.routes
        if getattr(route, "path", "") == "/evidence/{case_id:int}"
    )
    assert evidence_route.methods == {"GET"}


def test_evidence_graph_service_rejects_unknown_case():
    db = _session()

    try:
        EvidenceGraphService.build_case_graph(db, 404)
    except EvidenceGraphError as exc:
        assert str(exc) == "case_not_found"
    else:
        raise AssertionError("missing case should fail")
