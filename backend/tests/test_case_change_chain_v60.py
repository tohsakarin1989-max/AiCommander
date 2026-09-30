"""Synthetic, isolated regressions for transactional clues and derived chains."""
from datetime import datetime

import pytest

from app.api.cases import CaseTipCreate, create_case_tip
from app.models.case import CaseTip
from app.models.case_pipeline import OutboxEvent
from app.models.chain_link import ChainLink
from app.models.user import User
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.chain_analysis_service import ChainAnalysisService
from tests.test_chain_analysis import _case, _client, _session


@pytest.fixture
def db():
    session = _session()
    session.info["authorized_area_ids"] = None
    yield session
    session.close()


def test_save_and_location_patch_never_scan_chain_synchronously(db, monkeypatch):
    calls = []
    monkeypatch.setattr(ChainAnalysisService, "scan_chain_links", lambda *args, **kwargs: calls.append(args))
    case = CaseService.create_case(db, "V60-SAVE", datetime(2026, 5, 1), description="正常录入")
    CaseService.update_case(db, case.id, description="补充记录")
    response = _client(db).patch(f"/api/cases/{case.id}/location", json={"latitude": 46.6, "longitude": 125.1})
    assert response.status_code == 200
    assert calls == []


def test_tip_changes_source_and_queues_profile_without_promoting_to_fact(db):
    case = _case(db, "V60-TIP", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    before = CasePipelineService.source_hash(db, case)
    tip = create_case_tip(CaseTipCreate(case_id=case.id, content="举报某处可能囤油"), db)
    assert CasePipelineService.source_hash(db, case) != before
    event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").one()
    assert event.payload["changed_fields"] == ["tips"]
    payload = CasePipelineService.build_profile_payload(db, case)
    assert payload["source_clues"][0]["verification_status"] == "pending"
    assert payload["source_clues"][0]["usable_as_fact"] is False
    assert payload["source_clues"][0]["source_ref"] == f"case_tip:{tip.id}"
    assert "举报某处可能囤油" not in str(payload["analysis_facts"])


def test_tip_and_event_rollback_together(db, monkeypatch):
    case = _case(db, "V60-TIP-ROLLBACK", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    def fail(*args, **kwargs):
        raise RuntimeError("outbox_failure")
    monkeypatch.setattr(CasePipelineService, "enqueue_case_change", fail)
    with pytest.raises(RuntimeError, match="outbox_failure"):
        create_case_tip(CaseTipCreate(case_id=case.id, content="未核实线索"), db)
    db.rollback()
    assert db.query(CaseTip).count() == 0


def test_source_change_expires_candidate_but_preserves_confirmed_history(db):
    upstream = _case(db, "V60-UP", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    middle = _case(db, "V60-MID", "油罐车", datetime(2026, 5, 2), 46.62, 125.12)
    link = ChainAnalysisService.scan_chain_links(middle.id, db)[0]
    assert ChainAnalysisService.link_to_dict(link)["freshness"] == "current"
    ChainAnalysisService.confirm_link(link.id, "复核人", db)
    upstream.latitude = 50.0
    db.commit()
    result = ChainAnalysisService.link_to_dict(link)
    assert result["status"] == "confirmed"
    assert result["freshness"] == "source_changed"
    assert result["confirmed_by"] == "复核人"
    assert result["source_change_warning"]
    assert _client(db).get("/api/chain-links/map-data").json()["chain_links"] == []
    assert ChainAnalysisService.get_chain_context(middle.id, db)["summary"]["total"] == 0
    from app.services.evidence_graph_service import EvidenceGraphService
    nodes, edges, issues = [], [], []
    EvidenceGraphService._add_chain_context(db, middle, add_node=nodes.append,
        add_edge=edges.append, add_issue=issues.append, max_context_nodes=20)
    assert nodes == edges == issues == []
    assert not db.new and not db.dirty


def test_stale_inference_cannot_be_confirmed_and_rebuild_can_withdraw(db):
    upstream = _case(db, "V60-UP2", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    middle = _case(db, "V60-MID2", "油罐车", datetime(2026, 5, 2), 46.62, 125.12)
    link = ChainAnalysisService.scan_chain_links(middle.id, db)[0]
    upstream.latitude = 50.0
    db.commit()
    client = _client(db)
    assert client.get("/api/chain-links/").json() == []
    assert client.post(f"/api/chain-links/{link.id}/confirm", json={}).status_code == 409
    assert ChainAnalysisService.scan_chain_links(middle.id, db) == []
    assert db.get(type(link), link.id).status == "inferred"


def _bind_actor(db):
    actor = User(username="chain-eval", display_name="隔离测试", password_hash="unused", role="admin")
    db.add(actor)
    db.commit()
    db.info.update(principal_user_id=actor.id, authorized_area_ids=None)
    return actor


def test_durable_chain_worker_is_idempotent_and_save_only_records_intent(db):
    from app.services.chain_outbox_service import EVENT_TYPE, process_request
    _bind_actor(db)
    upstream = _case(db, "WORKER-UP", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    middle = _case(db, "WORKER-MID", "油罐车", datetime(2026, 5, 2), 46.62, 125.12)
    CasePipelineService.enqueue_case_change(db, middle)
    db.commit()
    request = db.query(OutboxEvent).filter_by(event_type=EVENT_TYPE).one()
    assert db.query(ChainLink).count() == 0
    assert process_request(db, request.id)["status"] == "completed"
    assert process_request(db, request.id)["claimed"] is False
    assert db.query(ChainLink).count() == 1
    assert db.query(ChainLink).one().case_id_a == upstream.id


def test_revoked_actor_fails_closed_and_worker_cannot_widen_scope(db):
    from app.services.chain_outbox_service import EVENT_TYPE, process_request
    actor = _bind_actor(db)
    case = _case(db, "WORKER-REVOKED", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    request = db.query(OutboxEvent).filter_by(event_type=EVENT_TYPE).one()
    actor.is_active = False
    db.commit()
    assert process_request(db, request.id)["status"] == "failed"
    assert db.query(ChainLink).count() == 0
    assert request.error == "chain_authority_unavailable"


def test_worker_retries_failure_and_recovers_expired_lease(db, monkeypatch):
    from datetime import timedelta, timezone
    from app.services.chain_outbox_service import EVENT_TYPE, process_request
    _bind_actor(db)
    case = _case(db, "WORKER-RETRY", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    request = db.query(OutboxEvent).filter_by(event_type=EVENT_TYPE).one()
    original = ChainAnalysisService.scan_chain_links
    def fail(*args, **kwargs):
        raise RuntimeError("isolated injected failure")
    monkeypatch.setattr(ChainAnalysisService, "scan_chain_links", fail)
    assert process_request(db, request.id)["status"] == "retry"
    request.status = "processing"
    request.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    request.worker_id = "dead-worker"
    db.commit()
    monkeypatch.setattr(ChainAnalysisService, "scan_chain_links", original)
    assert process_request(db, request.id)["status"] == "completed"


def test_legacy_inference_stays_historical_until_explicit_rebuild(db):
    upstream = _case(db, "OLD-UP", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    middle = _case(db, "OLD-MID", "油罐车", datetime(2026, 5, 2), 46.62, 125.12)
    link = ChainLink(case_id_a=upstream.id, case_id_b=middle.id, link_type="upstream_transport",
                     status="inferred", confidence=0.9)
    db.add(link)
    db.commit()
    client = _client(db)
    assert client.get("/api/chain-links/").json() == []
    history = client.get("/api/chain-links/", params={"include_stale": True}).json()
    assert history[0]["freshness"] == "legacy_unversioned"
    assert not db.new and not db.dirty
    rebuilt = ChainAnalysisService.scan_chain_links(middle.id, db)
    assert rebuilt[0].id == link.id
    assert ChainAnalysisService.link_to_dict(rebuilt[0])["freshness"] == "current"


def test_tip_edit_changes_source_and_retains_verification_boundary(db):
    case = _case(db, "TIP-EDIT", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    tip = create_case_tip(CaseTipCreate(case_id=case.id, content="待核实原文"), db)
    before = CasePipelineService.source_hash(db, case)
    response = _client(db).patch(f"/api/cases/tips/{tip.id}", json={
        "verification_status": "verified", "resolution": "已核实来电人身份，内容仍需调查",
    })
    assert response.status_code == 200
    assert CasePipelineService.source_hash(db, case) != before
    assert len(db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").all()) == 2
    clues = CasePipelineService.source_clues(db, case)
    assert clues[0]["verification_status"] == "verified"
    assert clues[0]["usable_as_fact"] is False


def test_tip_cannot_reassign_case_outside_current_write_scope(db):
    from app.models.map_foundation import OperationalArea
    first = OperationalArea(code="TIP-A", name="辖区甲")
    second = OperationalArea(code="TIP-B", name="辖区乙")
    db.add_all([first, second])
    db.commit()
    case = _case(db, "TIP-AUTH", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    other = _case(db, "TIP-HIDDEN", "管线", datetime(2026, 5, 1), 46.6, 125.1)
    case.operational_area_id, other.operational_area_id = first.id, second.id
    db.commit()
    tip = create_case_tip(CaseTipCreate(case_id=case.id, content="原始线索"), db)
    db.info.update(authorized_area_ids=(first.id,), area_access_levels={first.id: "write"})
    response = _client(db).patch(f"/api/cases/tips/{tip.id}", json={"case_id": other.id, "content": "不应保存"})
    assert response.status_code == 404
    assert db.get(CaseTip, tip.id).content == "原始线索"
    assert db.get(CaseTip, tip.id).case_id == case.id
