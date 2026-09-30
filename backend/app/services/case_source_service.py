"""Capture original intake in the business transaction; no model or queue IO."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from sqlalchemy import Float, func

from app.models.case import Case, CaseEvidence, CasePerson, CaseTip, CaseVehicle, OilRecoveryRecord
from app.models.case_source import (CaseLocation, CaseRevision, CaseSourceLink, ChangeDelivery,
                                    DomainChange, EvidenceObject, OilMeasurement)


DERIVED_FIELDS = {"id", "features", "quality_score", "quality_level", "quality_issues",
                  "quality_updated_at", "created_at", "updated_at"}
DETAIL_MODELS = {"vehicles": CaseVehicle, "persons": CasePerson, "evidence": CaseEvidence,
                 "oil_recovery": OilRecoveryRecord, "tips": CaseTip, "locations": CaseLocation,
                 "measurements": OilMeasurement, "source_links": CaseSourceLink}


def json_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def encode(payload):
    return json.dumps(json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def field_value(row, column):
    value = getattr(row, column.name)
    return float(value) if value is not None and isinstance(column.type, Float) else json_value(value)


class CaseSourceService:
    @staticmethod
    def latest_revision(db, case_id):
        return db.query(CaseRevision).filter_by(case_id=case_id).order_by(CaseRevision.revision.desc()).first()

    @staticmethod
    def source_payload(db, case):
        db.flush()
        # Keep the single-case write path lean; batch reads below use the same
        # canonical fields and encoding, with equivalence covered in tests.
        payload = {"case": {column.name: field_value(case, column)
                            for column in Case.__table__.columns if column.name not in DERIVED_FIELDS}}
        for key, model in DETAIL_MODELS.items():
            records = db.query(model).filter(model.case_id == case.id).order_by(model.id).all()
            payload[key] = [{column.name: field_value(row, column)
                             for column in model.__table__.columns
                             if column.name not in {"id", "case_id", "created_at", "updated_at"}}
                            for row in records]
            payload[key].sort(key=encode)
        object_ids = {item["evidence_object_id"] for item in payload["evidence"] if item.get("evidence_object_id") is not None}
        payload["evidence_objects"] = [
            {key: json_value(getattr(item, key)) for key in
             ("id", "sha256", "media_type", "sensitivity", "captured_at", "availability")}
            for item in db.query(EvidenceObject).filter(EvidenceObject.id.in_(object_ids)).order_by(EvidenceObject.id).all()
        ] if object_ids else []
        latest = CaseSourceService.latest_revision(db, case.id)
        legacy = deepcopy((latest.payload if latest else {}).get("legacy_inputs", {}))
        legacy.update(deepcopy(getattr(case, "_source_legacy_inputs", {})))
        if legacy:
            payload["legacy_inputs"] = json_value(legacy)
        return payload

    @staticmethod
    def source_payloads(db, cases):
        """The canonical source contract, batched for read-side validation.

        No flush on this read entry point. Lists do not create revisions or
        reload file bytes; source changes use source_payload after flushing.
        """
        result = {}
        cases = list(cases)
        with db.no_autoflush:
            for offset in range(0, len(cases), 400):
                batch = cases[offset:offset + 400]
                ids = [case.id for case in batch]
                values = {case.id: {"case": {column.name: field_value(case, column)
                    for column in Case.__table__.columns if column.name not in DERIVED_FIELDS},
                    **{key: [] for key in DETAIL_MODELS}} for case in batch}
                for key, model in DETAIL_MODELS.items():
                    for row in db.query(model).populate_existing().filter(model.case_id.in_(ids)).order_by(model.id):
                        values[row.case_id][key].append({column.name: field_value(row, column)
                            for column in model.__table__.columns
                            if column.name not in {"id", "case_id", "created_at", "updated_at"}})
                object_ids = {item["evidence_object_id"] for payload in values.values()
                    for item in payload["evidence"] if item.get("evidence_object_id") is not None}
                objects = {item.id: {key: json_value(getattr(item, key)) for key in
                    ("id", "sha256", "media_type", "sensitivity", "captured_at", "availability")}
                    for item in db.query(EvidenceObject).populate_existing().filter(EvidenceObject.id.in_(object_ids))} if object_ids else {}
                revisions = {}
                if len(ids) == 1:
                    latest = CaseSourceService.latest_revision(db, ids[0])
                    if latest is not None:
                        revisions[ids[0]] = latest
                else:
                    latest_ids = db.query(CaseRevision.case_id, func.max(CaseRevision.revision).label("revision")).filter(
                        CaseRevision.case_id.in_(ids)).group_by(CaseRevision.case_id).subquery()
                    for row in db.query(CaseRevision).join(latest_ids,
                        (CaseRevision.case_id == latest_ids.c.case_id) & (CaseRevision.revision == latest_ids.c.revision)):
                        revisions[row.case_id] = row
                for case in batch:
                    payload = values[case.id]
                    for key in DETAIL_MODELS:
                        payload[key].sort(key=encode)
                    refs = {item["evidence_object_id"] for item in payload["evidence"] if item.get("evidence_object_id") is not None}
                    payload["evidence_objects"] = [objects[key] for key in sorted(refs) if key in objects]
                    latest = revisions.get(case.id)
                    legacy = deepcopy((latest.payload if latest else {}).get("legacy_inputs", {}))
                    legacy.update(deepcopy(getattr(case, "_source_legacy_inputs", {})))
                    if legacy:
                        payload["legacy_inputs"] = json_value(legacy)
                result.update(values)
        return result

    @staticmethod
    def source_hash(db, case):
        return hashlib.sha256(encode(CaseSourceService.source_payload(db, case)).encode()).hexdigest()

    @staticmethod
    def capture_change(db, case, *, change_type="updated"):
        # A PostgreSQL case-row lock serializes revision allocation with source
        # edits. SQLite serializes writes; the unique revision key is the fence.
        db.flush()
        if db.get_bind().dialect.name == "postgresql":
            db.query(Case.id).filter(Case.id == case.id).with_for_update().one()
        payload = CaseSourceService.source_payload(db, case)
        signature = hashlib.sha256(encode(payload).encode()).hexdigest()
        latest = CaseSourceService.latest_revision(db, case.id)
        if latest is not None and latest.source_hash == signature:
            case.__dict__.pop("_source_legacy_inputs", None)
            return latest, None
        actor_id = db.info.get("principal_user_id")
        revision = CaseRevision(case_id=case.id, revision=(latest.revision + 1 if latest else 1),
                                source_hash=signature, payload=payload, actor_id=actor_id)
        db.add(revision)
        db.flush()
        change = DomainChange(subject_type="case", subject_id=case.id, source_revision_id=revision.id,
                              change_type=change_type if latest else "created", actor_id=actor_id)
        db.add(change)
        db.flush()
        case.__dict__.pop("_source_legacy_inputs", None)
        return revision, change

    @staticmethod
    def attach_delivery(db, outbox, change):
        if change is None:
            return
        outbox.domain_change_id = change.id
        existing = db.query(ChangeDelivery).filter_by(change_id=change.id, consumer=outbox.event_type).first()
        if existing is None:
            db.add(ChangeDelivery(change_id=change.id, consumer=outbox.event_type, state=outbox.status, attempts=0))
        else:
            existing.state, existing.error = outbox.status, None
        if outbox.event_type == "case.analysis.requested":
            history = db.query(ChangeDelivery).filter_by(change_id=change.id, consumer="history_index").first()
            if history is None:
                db.add(ChangeDelivery(change_id=change.id, consumer="history_index", state="pending", attempts=0))
            else:
                history.state, history.error = "pending", None

    @staticmethod
    def add_source_links(db, case_id, links):
        for raw in links or []:
            values = {key: raw[key] for key in ("source_type", "source_id", "source_snapshot")}
            if values["source_type"] not in {"event", "tip"}:
                raise ValueError("invalid_case_source_type")
            if not isinstance(values["source_snapshot"], dict):
                raise ValueError("invalid_case_source_snapshot")
            existing = db.query(CaseSourceLink).filter_by(case_id=case_id,
                source_type=values["source_type"], source_id=values["source_id"]).first()
            if existing is None:
                db.add(CaseSourceLink(case_id=case_id, **json_value(values)))
        db.flush()
