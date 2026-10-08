"""Stable source identities, with isolated synthetic SQLite records only."""
from copy import deepcopy

import pytest

from app.models.case import Case, CasePerson, CaseVehicle
from app.models.case_pipeline import OutboxEvent
from app.models.case_source import CaseLocation, CaseRevision, EvidenceObject, OilMeasurement, SourceReference
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService, DETAIL_MODELS
from tests.test_chain_analysis import _client, _session


@pytest.fixture
def db():
    session = _session()
    session.info["authorized_area_ids"] = None
    yield session
    session.close()


@pytest.fixture(params=[
    ("initial_locations", "locations", CaseLocation,
     {"role": "discovery", "description": "合成地点", "precision": "unknown"}),
    ("initial_measurements", "measurements", OilMeasurement,
     {"value": 12, "unit": "liter", "stage": "seized"}),
])
def detail(request):
    return request.param


def create(db, number="IDENTITY-A", **kwargs):
    return CaseService.create_case(db, case_number=number, description="合成原文不变", **kwargs)


def test_edit_reorder_and_identical_duplicates_retain_ids(db, detail):
    field, key, model, values = detail
    case = create(db, **{field: [deepcopy(values), deepcopy(values)]})
    ids = [row.id for row in db.query(model).order_by(model.id)]
    before = CaseSourceService.latest_revision(db, case.id)
    CaseService.update_case(db, case.id, **{field: [dict(values, id=identifier) for identifier in reversed(ids)]})
    assert [row.id for row in db.query(model).order_by(model.id)] == ids
    assert CaseSourceService.latest_revision(db, case.id).id == before.id
    assert {row["id"] for row in before.payload[key]} == set(ids)
    CaseService.update_case(db, case.id, **{field: [dict(values, id=ids[1], source_note="仅补第二条")]})
    current = db.query(model).one()
    assert current.id == ids[1] and current.source_note == "仅补第二条"
    assert len(before.payload[key]) == 2  # Immutable previous identities survive.


def test_clear_then_recreate_never_reuses_deleted_id(db, detail):
    field, key, model, values = detail
    case = create(db, **{field: [values]})
    old = CaseSourceService.latest_revision(db, case.id)
    old_id = db.query(model).one().id
    CaseService.update_case(db, case.id, **{field: []})
    CaseService.update_case(db, case.id, **{field: [values]})
    new = CaseSourceService.latest_revision(db, case.id)
    assert db.query(model).one().id > old_id
    assert new.payload[key][0]["id"] != old.payload[key][0]["id"]
    assert new.source_hash != old.source_hash
    assert CaseSourceService.content_hash(new.payload) == CaseSourceService.content_hash(old.payload)


def test_missing_ids_mean_new_records_not_value_matching(db, detail):
    field, key, model, values = detail
    case = create(db, **{field: [values]})
    old_id = db.query(model).one().id
    before = CaseSourceService.latest_revision(db, case.id)
    CaseService.update_case(db, case.id, **{field: [values, values]})
    after = CaseSourceService.latest_revision(db, case.id)
    assert old_id not in [row.id for row in db.query(model)]
    assert len(after.payload[key]) == 2
    assert CaseSourceService.content_hash(before.payload) != CaseSourceService.content_hash(after.payload)


@pytest.mark.parametrize("invalid", ["foreign", "missing", "duplicate", "boolean", "string"])
def test_invalid_ids_reject_entire_update_without_side_effects(db, detail, invalid):
    field, key, model, values = detail
    case = create(db, **{field: [values]})
    other = create(db, "IDENTITY-B", **{field: [values]})
    local_id = db.query(model).filter_by(case_id=case.id).one().id
    foreign_id = db.query(model).filter_by(case_id=other.id).one().id
    identifier = {"foreign": foreign_id, "missing": 987654, "duplicate": local_id,
                  "boolean": True, "string": str(local_id)}[invalid]
    rows = [dict(values, id=identifier)] * (2 if invalid == "duplicate" else 1)
    count = db.query(OutboxEvent).count()
    with pytest.raises(ValueError, match="detail_id"):
        CaseService.update_case(db, case.id, description="不应保存", **{field: rows})
    assert db.get(Case, case.id).description == "合成原文不变"
    assert db.query(model).filter_by(case_id=case.id).one().id == local_id
    assert db.query(model).filter_by(case_id=other.id).one().id == foreign_id
    assert db.query(CaseRevision).count() == 2
    assert db.query(OutboxEvent).count() == count


def test_api_rejects_importing_another_cases_id_and_allows_owned_edit(db, detail):
    field, key, model, values = detail
    case = create(db, **{field: [values]})
    identifier = db.query(model).one().id
    client = _client(db)
    response = client.post("/api/cases/", json={"description": "合成新增", field: [dict(values, id=identifier)]})
    assert response.status_code == 422
    assert db.query(Case).count() == 1
    response = client.put(f"/api/cases/{case.id}", json={field: [dict(values, id=identifier, source_note="人工补充")]})
    assert response.status_code == 200
    assert db.query(model).one().id == identifier
    assert db.query(model).one().source_note == "人工补充"


def test_strict_editor_uses_owned_ids_and_rejects_stale_source_identity(db, detail):
    field, _key, model, values = detail
    case = create(db, **{field: [values]})
    client = _client(db)
    path = f"/api/cases/{case.id}/edit-snapshot"
    snapshot = client.get(path).json()
    original_id = snapshot[field][0]["id"]
    saved = client.put(path, json={"expected_revision": snapshot["source_revision"],
        "case_payload": {field: [dict(values, id=original_id, source_note="明确补录")]}})
    assert saved.status_code == 200
    latest = client.get(path).json()
    assert latest[field][0]["id"] == original_id
    assert latest["source_revision"] > snapshot["source_revision"]
    stale = client.put(path, json={"expected_revision": snapshot["source_revision"],
        "case_payload": {field: []}})
    assert stale.status_code == 409
    assert db.query(model).one().id == original_id
    assert db.query(model).one().source_note == "明确补录"


def test_revision_keeps_vehicle_and_person_ids_without_changing_their_updates(db):
    case = create(db, initial_vehicles=[{"plate_number": "合成甲"}], initial_persons=[{"name": "合成人"}])
    vehicle_id, person_id = db.query(CaseVehicle).one().id, db.query(CasePerson).one().id
    CaseService.update_case(db, case.id, initial_vehicles=[{"id": vehicle_id, "notes": "补充"}],
        initial_persons=[{"id": person_id, "notes": "补充"}], replace_vehicles=True, replace_persons=True)
    revision = CaseSourceService.latest_revision(db, case.id)
    assert revision.payload["vehicles"][0]["id"] == vehicle_id
    assert revision.payload["persons"][0]["id"] == person_id


def test_content_fingerprint_ignores_identity_order_but_not_duplicate_count(db):
    case = create(db, initial_measurements=[{"value": 1, "unit": "liter"}, {"value": 2, "unit": "liter"}])
    original = CaseSourceService.source_payload(db, case)
    copy = deepcopy(original)
    copy["measurements"].reverse()
    for index, row in enumerate(copy["measurements"]):
        row["id"] = 999 + index
    assert CaseSourceService.content_hash(original) == CaseSourceService.content_hash(copy)
    copy["measurements"].append(deepcopy(copy["measurements"][0]))
    assert CaseSourceService.content_hash(original) != CaseSourceService.content_hash(copy)
    assert "id" in original["measurements"][0]  # Fingerprinting must not mutate the frozen source.


def test_text_fingerprint_is_separate_and_keeps_exact_quote_offsets(db):
    case = create(db, initial_measurements=[{"value": 1, "unit": "liter"}])
    original = CaseSourceService.source_payload(db, case)
    changed = deepcopy(original)
    changed["measurements"][0].update(id=999, value=200)
    assert CaseSourceService.text_content_hash(original) == CaseSourceService.text_content_hash(changed)
    assert CaseSourceService.content_hash(original) != CaseSourceService.content_hash(changed)
    changed["case"]["description"] = " " + original["case"]["description"]
    assert CaseSourceService.text_content_hash(original) != CaseSourceService.text_content_hash(changed)


def test_identity_change_still_enqueues_new_revision_and_derived_output(db):
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.services.case_pipeline_service import CasePipelineService
    values = {"value": 1, "unit": "liter"}
    case = create(db, initial_measurements=[values])
    for revision_number in (1, 2):
        event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested", status="pending").one()
        assert CasePipelineService.process_event(db, event.id)["status"] == "completed"
        current = db.query(CaseAnalysisProfile).filter_by(is_current=True).one()
        revision = CaseSourceService.latest_revision(db, case.id)
        assert current.source_revision_id == revision.id
        assert current.source_hash == revision.source_hash
        assert revision.revision == revision_number
        if revision_number == 1:
            CaseService.update_case(db, case.id, initial_measurements=[values])
    assert db.query(CaseAnalysisProfile).count() == 2


def test_legacy_snapshot_content_remains_usable_without_inventing_identity(db):
    import hashlib
    from app.services.case_source_service import encode
    case = create(db, initial_measurements=[{"value": 1, "unit": "liter"}])
    current = CaseSourceService.source_payload(db, case)
    legacy = CaseSourceService.content_payload(current)
    assert CaseSourceService.content_hash(current) == hashlib.sha256(encode(legacy).encode()).hexdigest()
    assert CaseSourceService.content_hash(current) == CaseSourceService.content_hash(legacy)
    assert "id" not in legacy["measurements"][0]


@pytest.mark.parametrize("key", list(DETAIL_MODELS))
def test_all_snapshot_detail_tables_do_not_reuse_deleted_maximum_or_empty_ids(db, key):
    from app.services.case_pipeline_service import CasePipelineService
    case = create(db)
    model = DETAIL_MODELS[key]
    values = {"locations": {"role": "discovery"}, "measurements": {"value": 1, "unit": "liter"},
              "source_links": {"source_type": "event", "source_id": 987, "source_snapshot": {}}}.get(key, {})
    first = model(case_id=case.id, **values)
    db.add(first)
    CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    original_id = first.id
    original = CaseSourceService.latest_revision(db, case.id)
    assert original.payload[key][0]["id"] == original_id
    db.delete(first)
    CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    second = model(case_id=case.id, **values)
    db.add(second)
    CasePipelineService.enqueue_case_change(db, case)
    db.commit()
    assert second.id > original_id
    latest = CaseSourceService.latest_revision(db, case.id)
    assert latest.source_hash != original.source_hash
    assert CaseSourceService.content_hash(latest.payload) == CaseSourceService.content_hash(original.payload)


@pytest.mark.parametrize("model", [EvidenceObject, SourceReference])
def test_linked_source_objects_do_not_reuse_deleted_maximum_or_empty_ids(db, model):
    case = create(db)
    values = {"storage_key": "synthetic-only", "availability": "metadata_only"} if model is EvidenceObject else {
        "case_id": case.id, "kind": "text", "locator": {}}
    first = model(**values)
    db.add(first)
    db.commit()
    old_id = first.id
    db.delete(first)
    db.commit()
    replacement = model(**values)
    db.add(replacement)
    db.commit()
    assert replacement.id > old_id


def test_exchanging_values_does_not_exchange_source_identity(db):
    case = create(db, initial_measurements=[{"value": 1, "unit": "liter"}, {"value": 2, "unit": "liter"}])
    before = CaseSourceService.latest_revision(db, case.id)
    first, second = before.payload["measurements"]
    CaseService.update_case(db, case.id, initial_measurements=[
        {"id": first["id"], "value": 2, "unit": "liter"},
        {"id": second["id"], "value": 1, "unit": "liter"}])
    after = CaseSourceService.latest_revision(db, case.id)
    assert after.source_hash != before.source_hash
    assert CaseSourceService.content_hash(after.payload) == CaseSourceService.content_hash(before.payload)
    assert [(row["id"], row["value"]) for row in after.payload["measurements"]] == [(first["id"], 2), (second["id"], 1)]
