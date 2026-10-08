"""Typed intake and transactional revisions, using only synthetic SQLite data."""
from datetime import datetime, timezone

import pytest

from app.models.case import Case, CaseVehicle
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.case_source import CaseLocation, CaseRevision, ChangeDelivery, DomainChange, OilMeasurement
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.case_source_service import CaseSourceService
from tests.test_chain_analysis import _session


@pytest.fixture
def db():
    session = _session()
    session.info["authorized_area_ids"] = None
    yield session
    session.close()


def create(db, **values):
    return CaseService.create_case(db, case_number="V61-SYNTHETIC", description="时间不详，井场东侧发现痕迹", **values)


def test_unknown_time_and_units_are_saved_without_invented_values(db):
    case = create(db, oil_volume=120, time_expression="昨晚", initial_locations=[
        {"role": "discovery", "description": "井场东侧", "precision": "unknown"}], initial_measurements=[
        {"value": 120, "unit": "liter", "stage": "seized"},
        {"value": 0.05, "unit": "tonne", "stage": "recovered"}])
    assert case.occurred_time is None and case.time_precision == "unknown"
    assert case.oil_volume_unit == "unknown"
    assert db.query(CaseLocation).one().geometry is None
    assert {row.unit for row in db.query(OilMeasurement)} == {"liter", "tonne"}
    revision = db.query(CaseRevision).one()
    assert revision.payload["case"]["time_expression"] == "昨晚"
    change = db.query(DomainChange).one()
    assert change.source_revision_id == revision.id
    assert db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").one().domain_change_id == change.id
    assert {row.consumer for row in db.query(ChangeDelivery)} == {"case.analysis.requested", "history_index"}
    assert all(row.state == "pending" for row in db.query(ChangeDelivery))


def test_interval_is_not_promoted_to_exact_time(db):
    case = create(db, occurred_from=datetime(2026, 9, 1), occurred_to=datetime(2026, 9, 2))
    assert case.occurred_time is None and case.time_precision == "interval"
    assert case.occurred_from < case.occurred_to


def test_legacy_objects_are_preserved_as_source_but_only_child_rows_are_canonical(db):
    raw = {"vehicles": [{"plate": "合成甲", "type": "罐车"}, {"plate": "合成甲", "type": "罐车"}]}
    case = create(db, vehicle_info=raw, involved_persons=[{"name": "合成人"}])
    assert case.vehicle_info is None and case.involved_persons is None
    assert len(case.vehicles) == 2 and len(case.persons) == 1
    assert db.query(CaseRevision).one().payload["legacy_inputs"]["vehicle_info"] == raw
    assert all(row.oil_volume_unit == "unknown" for row in case.vehicles)


def test_same_values_and_derived_features_do_not_create_new_revision(db):
    records = [{"value": 1, "unit": "liter", "stage": "seized"}]
    case = create(db, initial_measurements=records)
    # v7.2 retains explicit identities; an ID-less row denotes a new source,
    # even when its values happen to match a deleted row.
    saved_records = [dict(records[0], id=db.query(OilMeasurement).one().id)]
    CaseService.update_case(db, case.id, initial_measurements=saved_records, description=case.description)
    case.features = {"derived_only": True}
    case.quality_score = 33
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"features", "quality_score"})
    db.commit()
    assert db.query(CaseRevision).count() == 1
    assert db.query(DomainChange).count() == 1
    assert db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").count() == 1


def test_subrecord_change_creates_new_source_revision_and_immutable_history(db):
    case = create(db, initial_vehicles=[{"vehicle_type": "罐车", "oil_volume": 12, "oil_volume_unit": "liter"}])
    old = db.query(CaseRevision).one()
    vehicle = db.query(CaseVehicle).one()
    vehicle.notes = "人工新增原始说明"
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"vehicles"})
    db.commit()
    assert db.query(CaseRevision).count() == 2
    assert old.payload["vehicles"][0]["notes"] is None
    assert CaseSourceService.latest_revision(db, case.id).payload["vehicles"][0]["notes"] == "人工新增原始说明"
    old.source_hash = "changed"
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()


def test_source_links_are_captured_in_the_single_initial_revision(db):
    case = create(db, source_links=[{"source_type": "event", "source_id": 42,
                                   "source_snapshot": {"description": "原始发现", "oil_volume_liters": 120}}])
    revision = db.query(CaseRevision).one()
    assert revision.payload["source_links"][0]["source_id"] == 42
    assert revision.case_id == case.id


def test_batch_read_uses_same_full_source_contract_without_flushing(db):
    first = create(db, initial_locations=[{'role': 'discovery', 'description': '合成地点', 'precision': 'unknown'}],
        initial_measurements=[{'value': 12, 'unit': 'liter', 'stage': 'seized'}])
    second = CaseService.create_case(db, case_number='V61-SYNTHETIC-B', description='另一合成记录',
        source_links=[{'source_type': 'event', 'source_id': 41, 'source_snapshot': {'text': '原资料'}}])
    expected = {row.id: CaseSourceService.source_payload(db, row) for row in (first, second)}
    db.add(Case(case_number='MUST-NOT-FLUSH', description='只读期间未提交'))
    from sqlalchemy import event
    writes = []
    def capture(conn, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        assert CaseSourceService.source_payloads(db, [first, second]) == expected
        assert writes == []
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    db.rollback()


def test_outbox_failure_rolls_back_source_edit_and_revision(db, monkeypatch):
    case = create(db)
    old = case.description
    def fail(*args, **kwargs):
        raise RuntimeError("delivery_failure")
    monkeypatch.setattr(CaseSourceService, "attach_delivery", fail)
    with pytest.raises(RuntimeError, match="delivery_failure"):
        CaseService.update_case(db, case.id, description="不应落库的修改")
    assert db.get(Case, case.id).description == old
    assert db.query(CaseRevision).count() == 1
    assert db.query(DomainChange).count() == 1


def test_profile_and_delivery_bind_to_source_revision(db):
    case = create(db, occurred_time=datetime(2026, 9, 1, tzinfo=timezone.utc))
    event = db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").one()
    result = CasePipelineService.process_event(db, event.id)
    assert result["status"] == "completed"
    profile = db.query(CaseAnalysisProfile).one()
    assert profile.source_revision_id == db.query(CaseRevision).one().id
    assert profile.quality_score is None
    delivery = db.query(ChangeDelivery).filter_by(consumer="case.analysis.requested").one()
    assert delivery.state == "completed" and delivery.attempts == 1


def test_history_delivery_is_independent_and_rollback_does_not_acknowledge(db):
    from app.services.case_history_index_service import CaseHistoryIndexService
    create(db)
    CaseHistoryIndexService.reconcile_batch(db, limit=10)
    db.rollback()
    assert db.query(ChangeDelivery).filter_by(consumer="history_index").one().state == "pending"
    CaseHistoryIndexService.reconcile_batch(db, limit=10)
    db.commit()
    assert db.query(ChangeDelivery).filter_by(consumer="history_index").one().state == "completed"
    assert db.query(ChangeDelivery).filter_by(consumer="case.analysis.requested").one().state == "pending"


def test_unknown_time_is_not_a_zero_day_chain_match(db):
    from app.services.chain_analysis_service import ChainAnalysisService
    unknown = create(db, facility_type="管线", latitude=46.6, longitude=125.1)
    known = CaseService.create_case(db, "V61-KNOWN", datetime(2026, 9, 1),
                                   facility_type="油罐车", latitude=46.6, longitude=125.1)
    assert ChainAnalysisService._day_diff(None, known.occurred_time) is None
    assert ChainAnalysisService.scan_chain_links(known.id, db) == []
    assert ChainAnalysisService.scan_chain_links(unknown.id, db) == []


def test_material_revocation_changes_source_without_copying_blob(db):
    from app.models.case import CaseEvidence
    from app.models.case_source import EvidenceObject
    case = create(db)
    evidence = EvidenceObject(storage_key="opaque-id", sha256="a" * 64, media_type="text/plain",
                              sensitivity="internal", availability="available", content=b"private evidence")
    db.add(evidence)
    db.flush()
    db.add(CaseEvidence(case_id=case.id, evidence_object_id=evidence.id, title="合成材料"))
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"evidence"})
    db.commit()
    before = CaseSourceService.latest_revision(db, case.id)
    assert "private evidence" not in str(before.payload) and "opaque-id" not in str(before.payload)
    evidence.availability = "revoked"
    CasePipelineService.enqueue_case_change(db, case, changed_fields={"evidence"})
    db.commit()
    after = CaseSourceService.latest_revision(db, case.id)
    assert before.source_hash != after.source_hash
    assert after.payload["evidence_objects"][0]["availability"] == "revoked"


def test_area_incident_clears_old_point_and_has_no_fabricated_grid(db):
    case = create(db, latitude=46.6, longitude=125.1)
    CaseService.update_case(db, case.id, initial_locations=[
        {"role": "incident", "precision": "area", "description": "东侧区域",
         "geometry": {"type": "Polygon", "coordinates": [[[125, 46], [126, 46], [126, 47], [125, 46]]]}}])
    assert case.latitude is None and case.longitude is None
    assert CasePipelineService.build_profile_payload(db, case)["spatial_grid"] is None
    from tests.test_chain_analysis import _client
    response = _client(db).patch(f"/api/cases/{case.id}/location", json={"latitude": 46.6, "longitude": 125.1})
    assert response.status_code == 422
    assert case.latitude is None


def test_exact_incident_projection_and_removal_do_not_leave_ghost_point(db):
    point = {"role": "incident", "precision": "exact", "geometry": {"type": "Point", "coordinates": [125.1, 46.6]}}
    case = create(db, initial_locations=[point])
    assert (case.latitude, case.longitude) == (46.6, 125.1)
    with pytest.raises(ValueError, match="冲突"):
        CaseService.update_case(db, case.id, latitude=47, longitude=126, initial_locations=[point])
    with pytest.raises(ValueError, match="冲突"):
        CaseService.update_case(db, case.id, latitude=47, longitude=126)
    CaseService.update_case(db, case.id, initial_locations=[])
    assert case.latitude is None and case.longitude is None
    CaseService.update_case(db, case.id, latitude=45, longitude=124, initial_locations=[
        {"role": "discovery", "precision": "exact", "geometry": {"type": "Point", "coordinates": [127, 48]}}])
    assert (case.latitude, case.longitude) == (45, 124)


def test_returning_to_old_content_keeps_new_revision_and_profile_identity(db):
    case = create(db)
    CasePipelineService.process_event(db, db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").filter_by(status="pending").one().id)
    original_text = case.description
    for text in ("补录另一份原文", original_text):
        CaseService.update_case(db, case.id, description=text)
        CasePipelineService.process_event(db, db.query(OutboxEvent).filter_by(event_type="case.analysis.requested").filter_by(status="pending").one().id)
    revisions = db.query(CaseRevision).order_by(CaseRevision.revision).all()
    profiles = db.query(CaseAnalysisProfile).order_by(CaseAnalysisProfile.profile_version).all()
    assert len(revisions) == len(profiles) == 3
    assert revisions[0].source_hash == revisions[2].source_hash
    assert [row.source_revision_id for row in profiles] == [row.id for row in revisions]
    assert [row.is_current for row in profiles] == [False, False, True]


@pytest.mark.parametrize("values", [
    {"oil_volume": -1}, {"oil_volume_unit": "barrel"},
    {"time_precision": "exact"},
    {"occurred_from": datetime(2026, 9, 2), "occurred_to": datetime(2026, 9, 1)},
    {"initial_locations": [{"role": "incident", "precision": "exact", "geometry": None}]},
    {"initial_measurements": [{"value": -1, "unit": "liter", "stage": "seized"}]},
])
def test_invalid_typed_input_never_persists_case(db, values):
    with pytest.raises(ValueError):
        create(db, **values)
    db.rollback()
    assert db.query(Case).count() == 0
