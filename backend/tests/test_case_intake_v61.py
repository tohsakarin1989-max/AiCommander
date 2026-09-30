"""v6.1 scoped source intake; all data and attachments are synthetic."""
from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import cases, events
from app.database import get_db
from app.models.case import Case
from app.models.case_source import CaseRevision, DomainChange, CaseSourceLink, EvidenceObject
from app.models.event import Event
from app.services.case_intake_contract import normalize_intake
from app.services.case_pipeline_service import CasePipelineService
from tests.test_chain_analysis import _session


@pytest.fixture
def db():
    session = _session()
    yield session
    session.close()
    session.get_bind().dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")
    app.include_router(events.router, prefix="/api/events")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_unknown_time_saved_and_versioned_without_model_or_queue(client, db):
    response = client.post("/api/cases/", json={"description": "昨晚发现异常，时间待核", "time_expression": "昨晚", "oil_volume": 100, "oil_volume_unit": "liter"})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["occurred_time"] is None and value["time_precision"] == "unknown"
    assert value["oil_volume_unit"] == "liter"
    case_id = value["id"]
    original = client.get(f"/api/cases/{case_id}/sources").json()
    assert original["current_revision_id"] is not None
    assert len(original["revisions"]) == 1
    repeat = client.put(f"/api/cases/{case_id}", json={"description": value["description"]})
    assert repeat.status_code == 200, repeat.text
    assert db.query(CaseRevision).count() == 1
    assert db.query(DomainChange).count() == 1
    statistics = client.get("/api/cases/statistics").json()
    assert statistics["unknown_time_cases"] == 1


def test_interval_and_measurements_preserve_units_roles_and_are_read_only(client, db):
    payload = {"description": "井场周边发现痕迹", "time_precision": "interval",
               "occurred_from": "2026-09-01T00:00:00+08:00", "occurred_to": "2026-09-02T00:00:00+08:00",
               "initial_locations": [{"role": "mentioned", "description": "北侧区域", "precision": "area",
                 "geometry": {"type": "Polygon", "coordinates": [[[124, 47], [125, 47], [125, 48], [124, 47]]]}}],
               "initial_measurements": [{"value": 100, "unit": "liter", "stage": "seized"}, {"value": 0.05, "unit": "tonne", "stage": "recovered"}]}
    response = client.post("/api/cases/", json=payload)
    assert response.status_code == 200, response.text
    cid = response.json()["id"]
    assert response.json()["occurred_time"] is None
    before = db.query(CaseRevision).count()
    assert len(client.get(f"/api/cases/{cid}/measurements").json()) == 2
    assert client.get(f"/api/cases/{cid}/locations").json()[0]["role"] == "mentioned"
    assert db.query(CaseRevision).count() == before
    assert not db.dirty and not db.new
    response = client.put(f"/api/cases/{cid}", json={"initial_measurements": []})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/cases/{cid}/measurements").json() == []


def test_partial_interval_update_uses_stored_utc_without_reinterpreting_timezone(client):
    result = client.post("/api/cases/", json={"description": "合成区间",
        "time_precision": "interval", "time_timezone": "Asia/Shanghai",
        "occurred_from": "2026-09-27T01:00:00Z", "occurred_to": "2026-09-27T02:00:00Z"})
    assert result.status_code == 200, result.text
    cid = result.json()["id"]
    invalid = client.put(f"/api/cases/{cid}", json={"occurred_to": "2026-09-27T00:00:00Z"})
    assert invalid.status_code == 422, invalid.text
    valid = client.put(f"/api/cases/{cid}", json={"occurred_to": "2026-09-27T03:00:00Z"})
    assert valid.status_code == 200, valid.text
    assert valid.json()["occurred_from"].startswith("2026-09-27T01:00:00")


@pytest.mark.parametrize("payload", [
    {"time_precision": "exact"},
    {"time_precision": "unknown", "occurred_time": "2026-09-01T00:00:00Z"},
    {"time_precision": "interval", "occurred_from": "2026-09-02", "occurred_to": "2026-09-01"},
    {"oil_volume": -2}, {"oil_volume_unit": "gallon"}, {"latitude": 47},
    {"initial_locations": [{"role": "incident", "precision": "exact"}]},
    {"initial_measurements": [{"value": 1, "unit": "tonne", "water_cut": 101}]},
])
def test_invalid_intake_has_no_side_effects(payload, client, db):
    result = client.post("/api/cases/", json={"description": "合成材料", **payload})
    assert result.status_code == 422, result.text
    assert db.query(Case).count() == db.query(CaseRevision).count() == 0


def test_text_reference_frozen_and_blob_hash_download_revocation(client, db):
    case = client.post("/api/cases/", json={"description": "合成原始资料"}).json()
    cid = case["id"]
    revision = client.get(f"/api/cases/{cid}/sources").json()["current_revision_id"]
    reference = client.post(f"/api/cases/{cid}/source-references", json={"source_revision_id": revision, "field": "description", "start": 0, "end": 2})
    assert reference.status_code == 201, reference.text
    assert reference.json()["locator"]["quote"] == "合成"
    client.put(f"/api/cases/{cid}", json={"description": "更正后的资料"})
    assert client.get(f"/api/cases/{cid}/source-references/{reference.json()['id']}").json()["locator"]["quote"] == "合成"
    content = b"%PDF-1.4\nsynthetic evidence only"
    uploaded = client.post(f"/api/cases/{cid}/evidence-files", files={"file": ("../../example.pdf", content, "text/html")})
    assert uploaded.status_code == 201, uploaded.text
    result = uploaded.json()
    assert result["sha256"] == sha256(content).hexdigest()
    rid = result["reference_id"]
    downloaded = client.get(f"/api/cases/{cid}/source-references/{rid}/file")
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "application/octet-stream"
    again = client.post(f"/api/cases/{cid}/evidence-files", files={"file": ("example.pdf", content)})
    assert again.json()["reference_id"] == rid and again.json()["reused"]
    before = db.query(CaseRevision).count()
    assert client.post(f"/api/cases/{cid}/source-references/{rid}/revoke").status_code == 200
    assert db.query(CaseRevision).count() == before + 1
    assert client.get(f"/api/cases/{cid}/source-references/{rid}/file").status_code == 409


def test_event_conversion_atomic_and_idempotent(client, db, monkeypatch):
    from datetime import datetime
    event = Event(event_number="SYNTHETIC-EVENT", event_type="other", occurred_time=datetime(2026, 9, 1), description="合成事件", oil_volume_liters=20)
    db.add(event)
    db.commit()
    result = client.post(f"/api/events/{event.id}/convert-to-case")
    assert result.status_code == 200, result.text
    cid = result.json()["case_id"]
    assert db.get(Case, cid).oil_volume_unit == "liter"
    assert db.get(Case, cid).occurred_time == datetime(2026, 9, 1)
    assert db.query(CaseSourceLink).one().source_id == event.id
    assert client.post(f"/api/events/{event.id}/convert-to-case").json()["case_id"] == cid
    assert db.query(Case).count() == 1


def test_unscoped_tip_can_be_recorded_without_fake_case(client, db):
    response = client.post("/api/cases/tips", json={"content": "未核实线索，日期地点待核"})
    assert response.status_code == 200, response.text
    assert response.json()["case_id"] is None
    assert db.query(Case).count() == 0


def test_event_conversion_failure_does_not_leave_an_orphan_case(client, db, monkeypatch):
    from datetime import datetime
    event = Event(event_number="SYNTHETIC-ROLLBACK", event_type="other", occurred_time=datetime(2026, 9, 1), description="合成事件")
    db.add(event)
    db.commit()
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic_outbox_failure")
    monkeypatch.setattr(CasePipelineService, "enqueue_case_change", fail)
    with pytest.raises(RuntimeError, match="synthetic_outbox_failure"):
        client.post(f"/api/events/{event.id}/convert-to-case")
    db.rollback()
    assert db.query(Case).count() == 0
    assert db.query(CaseSourceLink).count() == 0
    assert db.get(Event, event.id).related_case_id is None


def test_source_and_attachments_reauthorize_current_scope(client, db):
    from app.models.map_foundation import OperationalArea
    areas = [OperationalArea(code=f"SYNTHETIC-{i}", name=f"测试辖区{i}", is_default=i == 1, status="active") for i in (1, 2)]
    db.add_all(areas)
    db.commit()
    area_a, area_b = [area.id for area in areas]
    cid = client.post("/api/cases/", json={"description": "合成资料", "operational_area_id": area_a}).json()["id"]
    rid = client.get(f"/api/cases/{cid}/sources").json()["current_revision_id"]
    ref = client.post(f"/api/cases/{cid}/source-references", json={"source_revision_id": rid, "field": "description", "start": 0, "end": 2}).json()["id"]
    db.info.update(authorized_area_ids=[area_b], area_access_levels={area_b: "write"}, default_operational_area_id=area_b)
    for suffix in ("sources", f"sources/{rid}", "locations", "measurements", f"source-references/{ref}"):
        assert client.get(f"/api/cases/{cid}/{suffix}").status_code == 404
    assert db.query(CaseRevision).count() == 0
    # An independent tip belongs to the caller's scope without requiring a case.
    tip = client.post("/api/cases/tips", json={"content": "合成独立线索"})
    assert tip.status_code == 200 and tip.json()["operational_area_id"] == area_b
    db.info.update(authorized_area_ids=[area_a], area_access_levels={area_a: "write"})
    assert client.get("/api/cases/tips").json() == []


def test_import_accepts_unknown_time_without_assuming_oil_unit(client):
    content = "案情描述,涉油量\n合成发现记录,100\n".encode()
    result = client.post("/api/cases/import", files={"file": ("synthetic.csv", content, "text/csv")})
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 1, result.text
    items = client.get("/api/cases/page").json()["items"]
    assert items[0]["occurred_time"] is None and items[0]["oil_volume_unit"] == "unknown"


def test_case_delete_does_not_fail_with_frozen_source_references(client, db):
    cid = client.post("/api/cases/", json={"description": "合成删除样本"}).json()["id"]
    revision = client.get(f"/api/cases/{cid}/sources").json()["current_revision_id"]
    assert client.post(f"/api/cases/{cid}/source-references", json={"source_revision_id": revision, "field": "description", "start": 0, "end": 2}).status_code == 201
    deleted = client.delete(f"/api/cases/{cid}")
    assert deleted.status_code == 200, deleted.text
    assert db.query(Case).count() == 0
