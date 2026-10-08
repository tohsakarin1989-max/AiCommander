"""Synthetic receipt metadata and existing append-only bulk correction boundary."""
from copy import deepcopy

import pytest

from tests.test_map_foundation import db_session, _client  # noqa: F401
from tests.test_map_ledger_v72 import BASE, ingest, setup
from app.models.map_foundation import MapFeatureClaim, MapIngestRun
from app.services.map_ingest_execution import list_claims, retry_rows


def test_receipts_expose_only_consumed_state_and_preserve_pagination(db_session):
    source, template = setup(db_session)
    parent = ingest(db_session, source, template, [
        BASE, {**BASE, "井号": "B", "经度": "错误"}, {**BASE, "井号": "C", "经度": "错误"},
    ])
    rows = list_claims(db_session, parent.id)["items"]
    assert [row["retry_superseded"] for row in rows] == [False, False, False]
    request = {"request_id": "bulk-correction", "rows": [
        {"claim_id": row["id"], "values": {**row["raw_payload"], "经度": 125.1}} for row in rows[1:]
    ]}
    original = deepcopy(rows)
    plan = retry_rows(db_session, parent.id, request, preview=True)
    child, replay = retry_rows(db_session, parent.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert not replay and child.created_assets == 2
    receipt = list_claims(db_session, parent.id, classification="failed", offset=1, limit=1)
    assert receipt["total"] == 2 and len(receipt["items"]) == 1
    assert receipt["items"][0]["retry_superseded"] is True
    assert set(receipt["items"][0]) - set(original[2]) == set()
    assert receipt["items"][0]["raw_payload"] == original[2]["raw_payload"]
    assert "superseded_by_run_id" not in receipt["items"][0]
    assert "superseded_by_claim_id" not in receipt["items"][0]
    descendants = list_claims(db_session, child.id)["items"]
    assert {row["parent_claim_id"] for row in descendants} == {row["id"] for row in original[1:]}
    assert all(row["retry_superseded"] is False for row in descendants)
    same, replay = retry_rows(db_session, parent.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    assert replay and same.id == child.id
    assert db_session.query(MapIngestRun).count() == 2
    with pytest.raises(ValueError, match="retry_row_superseded"):
        retry_rows(db_session, parent.id, {**request, "request_id": "different-attempt"}, preview=True)


def test_failed_successor_also_consumes_parent_and_receipt_read_is_read_only(db_session):
    source, template = setup(db_session)
    parent = ingest(db_session, source, template, [{**BASE, "经度": "错误"}])
    row = list_claims(db_session, parent.id)["items"][0]
    request = {"request_id": "still-invalid", "rows": [{"claim_id": row["id"], "values": row["raw_payload"]}]}
    plan = retry_rows(db_session, parent.id, request, preview=True)
    child, _ = retry_rows(db_session, parent.id, {**request, "plan_token": plan["plan_token"]}, created_by=1)
    before = db_session.query(MapFeatureClaim).count()
    client = _client(db_session)
    response = client.get(f"/api/map-ingest-runs/{parent.id}/claims")
    assert response.status_code == 200 and response.json()["items"][0]["retry_superseded"] is True
    assert list_claims(db_session, child.id)["items"][0]["retry_superseded"] is False
    assert db_session.query(MapFeatureClaim).count() == before
    assert not db_session.new and not db_session.dirty
    assert _client(db_session, role="analyst").get(f"/api/map-ingest-runs/{parent.id}/claims").status_code == 403
