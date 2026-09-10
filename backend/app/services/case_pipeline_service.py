"""案件保存后自动运行的确定性治理流水线。"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord
from app.models.case_pipeline import CaseAnalysisProfile, CasePipelineState, OutboxEvent
from app.models.map_foundation import OperationalArea
from app.services.case_quality_service import CaseQualityService
from app.services.outbox_claim_service import OutboxClaimLostError, OutboxClaimService


CASE_PROFILE_SCHEMA_VERSION = "3.3.0"
CASE_DICTIONARY_VERSION = "oil-case-2026.09"
ANALYSIS_RELEVANT_FIELDS = {
    "case_number",
    "occurred_time",
    "location",
    "latitude",
    "longitude",
    "case_type",
    "description",
    "involved_persons",
    "involved_items",
    "loss_amount",
    "oil_type",
    "oil_volume",
    "oil_value",
    "facility_type",
    "facility_owner",
    "modus_operandi",
    "suspect_roles",
    "vehicle_info",
    "upstream_source",
    "downstream_destination",
    "report_time",
    "report_unit",
    "source_type",
    "source_detail",
    "police_reported",
    "case_filed",
    "police_officer",
    "police_phone",
    "security_officers",
    "oil_nature",
    "water_cut",
    "vehicle_handling",
    "person_handling",
    "oil_handling",
    "operation_role",
    "current_stage",
    "status",
    "vehicles",
    "persons",
    "evidence",
    "oil_recovery",
}


class CasePipelineService:
    """只写派生画像，不改写案件正式字段。"""

    @staticmethod
    def enqueue_case_change(
        db: Session,
        case: Case,
        *,
        changed_fields: Iterable[str] | None = None,
    ) -> OutboxEvent | None:
        changed = set(changed_fields or ANALYSIS_RELEVANT_FIELDS)
        if changed.isdisjoint(ANALYSIS_RELEVANT_FIELDS):
            return None
        source_hash = CasePipelineService.source_hash(db, case)
        state = (
            db.query(CasePipelineState)
            .filter(CasePipelineState.case_id == case.id)
            .first()
        )
        current_profile = (
            db.query(CaseAnalysisProfile)
            .filter(
                CaseAnalysisProfile.case_id == case.id,
                CaseAnalysisProfile.source_hash == source_hash,
                CaseAnalysisProfile.schema_version == CASE_PROFILE_SCHEMA_VERSION,
                CaseAnalysisProfile.dictionary_version == CASE_DICTIONARY_VERSION,
                CaseAnalysisProfile.is_current.is_(True),
            )
            .first()
        )
        if current_profile is not None:
            return None
        if (
            state is not None
            and state.source_hash == source_hash
            and state.schema_version == CASE_PROFILE_SCHEMA_VERSION
            and state.dictionary_version == CASE_DICTIONARY_VERSION
            and state.status in {"pending", "processing", "degraded"}
        ):
            return None
        idempotency_key = hashlib.sha256(
            (
                f"case:{case.id}:{source_hash}:{CASE_PROFILE_SCHEMA_VERSION}:"
                f"{CASE_DICTIONARY_VERSION}:after:{state.event_id if state else 'initial'}"
            ).encode()
        ).hexdigest()
        existing = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return None
        event = OutboxEvent(
            id=str(uuid.uuid4()),
            event_type="case.analysis.requested",
            aggregate_type="case",
            aggregate_id=str(case.id),
            payload={
                "case_id": case.id,
                "source_hash": source_hash,
                "changed_fields": sorted(changed.intersection(ANALYSIS_RELEVANT_FIELDS)),
                "schema_version": CASE_PROFILE_SCHEMA_VERSION,
                "dictionary_version": CASE_DICTIONARY_VERSION,
            },
            idempotency_key=idempotency_key,
            status="pending",
        )
        db.add(event)
        # CasePipelineState.event_id 具有外键约束；先持久化 Outbox 主记录，
        # 保证 SQLite 测试与 PostgreSQL 生产环境采用相同的写入顺序。
        db.flush()
        if state is None:
            state = CasePipelineState(
                case_id=case.id,
                status="pending",
                source_hash=source_hash,
                event_id=event.id,
                schema_version=CASE_PROFILE_SCHEMA_VERSION,
                dictionary_version=CASE_DICTIONARY_VERSION,
            )
            db.add(state)
        else:
            state.status = "pending"
            state.source_hash = source_hash
            state.event_id = event.id
            state.schema_version = CASE_PROFILE_SCHEMA_VERSION
            state.dictionary_version = CASE_DICTIONARY_VERSION
            state.requested_at = datetime.now(timezone.utc)
            state.completed_at = None
            state.last_error = None
        db.flush()
        return event

    @staticmethod
    def process_event(db: Session, event_id: str) -> dict[str, Any]:
        event, claimed = OutboxClaimService.claim(
            db,
            event_id,
            expected_type="case.analysis.requested",
        )
        if not claimed:
            return {
                "event_id": event.id,
                "status": event.status,
                "idempotent_replay": event.status in {"completed", "superseded"},
            }
        worker_id = str(event.worker_id)
        try:
            # 所有案件派生 Worker 统一按 case -> state/profile -> snapshot 加锁，
            # 与案件更新事务保持一致，避免 PostgreSQL 双会话交叉等待。
            case_query = db.query(Case).filter(Case.id == int(event.aggregate_id))
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                case_query = case_query.with_for_update()
            case = case_query.first()
            if not case:
                raise ValueError("case_not_found")
            if case.operational_area_id is not None:
                area_query = db.query(OperationalArea).filter(
                    OperationalArea.id == case.operational_area_id
                )
                if db.bind is not None and db.bind.dialect.name == "postgresql":
                    area_query = area_query.with_for_update()
                area_query.first()
            state_query = db.query(CasePipelineState).filter(
                CasePipelineState.case_id == case.id
            )
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                state_query = state_query.with_for_update()
            state = state_query.first()
            if state is not None and state.event_id != event.id:
                OutboxClaimService.finish(
                    db,
                    event_id=event.id,
                    worker_id=worker_id,
                    status="superseded",
                )
                db.commit()
                return {"event_id": event.id, "status": "superseded"}
            if state:
                state.status = "processing"
                state.attempts = event.attempts
            current_hash = CasePipelineService.source_hash(db, case)
            if current_hash != event.payload.get("source_hash"):
                CasePipelineService.enqueue_case_change(db, case)
                OutboxClaimService.finish(
                    db,
                    event_id=event.id,
                    worker_id=worker_id,
                    status="superseded",
                )
                db.commit()
                return {"event_id": event.id, "status": "superseded"}

            existing = (
                db.query(CaseAnalysisProfile)
                .filter(
                    CaseAnalysisProfile.case_id == case.id,
                    CaseAnalysisProfile.source_hash == current_hash,
                    CaseAnalysisProfile.schema_version == CASE_PROFILE_SCHEMA_VERSION,
                    CaseAnalysisProfile.dictionary_version == CASE_DICTIONARY_VERSION,
                )
                .first()
            )
            payload = (
                CasePipelineService.build_profile_payload(db, case)
                if existing is None
                else None
            )
            if state is not None:
                db.refresh(state)
            if (
                (state is not None and state.event_id != event.id)
                or CasePipelineService.source_hash(db, case) != current_hash
            ):
                db.rollback()
                current_event = db.query(OutboxEvent).filter(
                    OutboxEvent.id == event_id,
                    OutboxEvent.worker_id == worker_id,
                ).first()
                if current_event:
                    OutboxClaimService.finish(
                        db,
                        event_id=event_id,
                        worker_id=worker_id,
                        status="superseded",
                    )
                    db.commit()
                return {"event_id": event.id, "status": "superseded"}

            for old in (
                db.query(CaseAnalysisProfile)
                .filter(
                    CaseAnalysisProfile.case_id == case.id,
                    CaseAnalysisProfile.is_current.is_(True),
                )
                .all()
            ):
                old.is_current = False
            if existing is None:
                latest = (
                    db.query(CaseAnalysisProfile)
                    .filter(CaseAnalysisProfile.case_id == case.id)
                    .order_by(CaseAnalysisProfile.profile_version.desc())
                    .first()
                )
                existing = CaseAnalysisProfile(
                    id=str(uuid.uuid4()),
                    case_id=case.id,
                    profile_version=(latest.profile_version + 1) if latest else 1,
                    source_hash=current_hash,
                    schema_version=CASE_PROFILE_SCHEMA_VERSION,
                    dictionary_version=CASE_DICTIONARY_VERSION,
                    payload=payload,
                    quality_score=float(payload["quality"]["score"]),  # type: ignore[index]
                    analysis_readiness=payload["overall_readiness"],  # type: ignore[index]
                    is_current=True,
                )
                db.add(existing)
            else:
                existing.is_current = True

            if state is None:
                state = CasePipelineState(
                    case_id=case.id,
                    status="completed",
                    source_hash=current_hash,
                    event_id=event.id,
                    schema_version=CASE_PROFILE_SCHEMA_VERSION,
                    dictionary_version=CASE_DICTIONARY_VERSION,
                )
                db.add(state)
            state.status = "completed"
            state.source_hash = current_hash
            state.event_id = event.id
            state.last_error = None
            state.completed_at = datetime.now(timezone.utc)
            db.flush()
            from app.services.case_insight_service import CaseInsightService
            from app.services.offline_map_service import OfflineMapService

            snapshot = OfflineMapService.current_snapshot(
                db,
                area_id=case.operational_area_id,
            )
            if snapshot:
                CaseInsightService.enqueue_analysis(db, existing, snapshot)
            OutboxClaimService.finish(
                db,
                event_id=event.id,
                worker_id=worker_id,
                status="completed",
            )
            db.commit()
            db.refresh(existing)
            return {
                "event_id": event.id,
                "status": "completed",
                "profile_id": existing.id,
                "profile_version": existing.profile_version,
                "idempotent_replay": False,
            }
        except Exception as exc:
            db.rollback()
            failed_event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
            if failed_event and failed_event.worker_id == worker_id:
                failed_status = "retry" if failed_event.attempts < 3 else "failed"
                failed_state = (
                    db.query(CasePipelineState)
                    .filter(CasePipelineState.case_id == int(failed_event.aggregate_id))
                    .first()
                )
                if failed_state and failed_state.event_id == failed_event.id:
                    failed_state.status = "degraded" if failed_status == "retry" else "failed"
                    failed_state.last_error = str(exc)[:2000]
                OutboxClaimService.finish(
                    db,
                    event_id=event_id,
                    worker_id=worker_id,
                    status=failed_status,
                    error=str(exc)[:2000],
                    available_at=datetime.now(timezone.utc)
                    + timedelta(seconds=min(60, 2 ** failed_event.attempts)),
                )
                db.commit()
            if isinstance(exc, OutboxClaimLostError):
                return {"event_id": event_id, "status": "lease_lost"}
            raise

    @staticmethod
    def process_pending(db: Session, limit: int = 50) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        events = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.event_type == "case.analysis.requested",
                or_(
                    and_(
                        OutboxEvent.status.in_(("pending", "retry")),
                        OutboxEvent.available_at <= now,
                    ),
                    and_(
                        OutboxEvent.status == "processing",
                        or_(
                            OutboxEvent.lease_until.is_(None),
                            OutboxEvent.lease_until <= now,
                        ),
                    ),
                ),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(max(1, min(limit, 200)))
            .all()
        )
        completed = 0
        failed = 0
        for event in events:
            try:
                result = CasePipelineService.process_event(db, event.id)
                completed += int(result["status"] in {"completed", "superseded"})
            except Exception:
                failed += 1
        return {"selected": len(events), "completed": completed, "failed": failed}

    @staticmethod
    def backfill(
        db: Session,
        limit: int = 200,
        *,
        after_id: int = 0,
    ) -> dict[str, Any]:
        batch_limit = max(1, min(limit, 5000))
        cases = (
            db.query(Case)
            .filter(Case.id > max(0, after_id))
            .order_by(Case.id)
            .limit(batch_limit)
            .all()
        )
        enqueued = 0
        for case in cases:
            if CasePipelineService.enqueue_case_change(db, case):
                enqueued += 1
        db.commit()
        return {
            "scanned": len(cases),
            "enqueued": enqueued,
            "after_id": max(0, after_id),
            "next_after_id": cases[-1].id if len(cases) == batch_limit else None,
        }

    @staticmethod
    def source_hash(db: Session, case: Case) -> str:
        payload = {
            "case": {
                key: CasePipelineService._json_value(getattr(case, key))
                for key in sorted(ANALYSIS_RELEVANT_FIELDS)
                if key not in {"vehicles", "persons", "evidence", "oil_recovery"}
            },
            "vehicles": [
                CasePipelineService._model_values(
                    item,
                    (
                        "vehicle_type",
                        "color",
                        "brand",
                        "model",
                        "plate_number",
                        "oil_volume",
                        "water_cut",
                        "custody_location",
                        "current_location",
                        "handling_status",
                        "transferred_to_police",
                        "transfer_time",
                        "transfer_document_no",
                    ),
                )
                for item in db.query(CaseVehicle).filter(CaseVehicle.case_id == case.id).order_by(CaseVehicle.id).all()
            ],
            "persons": [
                CasePipelineService._model_values(
                    item,
                    (
                        "name",
                        "gender",
                        "id_number",
                        "home_address",
                        "phone",
                        "role",
                        "handling_status",
                    ),
                )
                for item in db.query(CasePerson).filter(CasePerson.case_id == case.id).order_by(CasePerson.id).all()
            ],
            "evidence": [
                CasePipelineService._model_values(
                    item,
                    (
                        "evidence_type",
                        "title",
                        "file_path",
                        "requirement_key",
                        "captured_at",
                        "latitude",
                        "longitude",
                        "is_sensitive",
                        "meta",
                    ),
                )
                for item in db.query(CaseEvidence).filter(CaseEvidence.case_id == case.id).order_by(CaseEvidence.id).all()
            ],
            "oil_recovery": [
                CasePipelineService._model_values(
                    item,
                    (
                        "oil_nature",
                        "volume_tons",
                        "water_cut",
                        "source",
                        "receiver",
                        "handled_at",
                        "handling_method",
                    ),
                )
                for item in db.query(OilRecoveryRecord).filter(OilRecoveryRecord.case_id == case.id).order_by(OilRecoveryRecord.id).all()
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def build_profile_payload(db: Session, case: Case) -> dict[str, Any]:
        feature_profile = CaseQualityService.build_case_feature_profile(db, case)
        quality = feature_profile["quality"]
        readiness = feature_profile["analysis_readiness"]
        gaps: list[dict[str, str]] = []
        for item in quality.get("missing_required", []):
            if isinstance(item, dict):
                gaps.append(
                    {
                        "field": str(item.get("field") or "unknown"),
                        "label": str(item.get("label") or item.get("field") or "待补充信息"),
                        "reason": "关键字段缺失",
                    }
                )
        for item in quality.get("warnings", []):
            if len(gaps) >= 3:
                break
            if isinstance(item, dict):
                gaps.append(
                    {
                        "field": str(item.get("field") or "unknown"),
                        "label": str(item.get("message") or "信息存在矛盾"),
                        "reason": "一致性待核验",
                    }
                )
        statuses = [
            item.get("status")
            for item in readiness.values()
            if isinstance(item, dict)
        ]
        overall = "ready" if statuses and all(item == "ready" for item in statuses) else "partial"
        if statuses and all(str(item).startswith("missing") for item in statuses):
            overall = "missing"
        return {
            "schema_version": CASE_PROFILE_SCHEMA_VERSION,
            "dictionary_version": CASE_DICTIONARY_VERSION,
            "case_id": case.id,
            "case_number": case.case_number,
            "source_hash": CasePipelineService.source_hash(db, case),
            "spatial_grid": CasePipelineService._spatial_grid(case.latitude, case.longitude),
            "standard": {
                "occurred_time": CasePipelineService._json_value(case.occurred_time),
                "location": CasePipelineService._normalize_text(case.location),
                "case_type": CasePipelineService._normalize_text(case.case_type),
                "oil_type": CasePipelineService._normalize_text(case.oil_type),
                "oil_nature": CasePipelineService._normalize_text(case.oil_nature),
                "facility_type": CasePipelineService._normalize_text(case.facility_type),
                "modus_operandi": CasePipelineService._normalize_text(case.modus_operandi),
                "report_unit": CasePipelineService._normalize_text(case.report_unit),
                "source_type": CasePipelineService._normalize_text(case.source_type),
            },
            "analysis_facts": {
                "latitude": case.latitude,
                "longitude": case.longitude,
                "oil_volume": case.oil_volume,
                "oil_value": case.oil_value,
                "water_cut": case.water_cut,
                "upstream_source": case.upstream_source,
                "downstream_destination": case.downstream_destination,
                "vehicle_count": quality.get("facts", {}).get("vehicle_count", 0),
                "person_count": quality.get("facts", {}).get("person_count", 0),
                "evidence_count": quality.get("facts", {}).get("evidence_count", 0),
            },
            "quality": quality,
            "critical_gaps": gaps[:3],
            "analysis_readiness": readiness,
            "overall_readiness": overall,
            "boundary": "派生画像不改写案件原始事实；缺项只作录入提示。",
        }

    @staticmethod
    def profile_to_dict(profile: CaseAnalysisProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "case_id": profile.case_id,
            "profile_version": profile.profile_version,
            "source_hash": profile.source_hash,
            "schema_version": profile.schema_version,
            "dictionary_version": profile.dictionary_version,
            "payload": profile.payload,
            "quality_score": profile.quality_score,
            "analysis_readiness": profile.analysis_readiness,
            "is_current": profile.is_current,
            "created_at": profile.created_at,
        }

    @staticmethod
    def state_to_dict(state: CasePipelineState | None, case_id: int) -> dict[str, Any]:
        if state is None:
            return {"case_id": case_id, "status": "not_started"}
        return {
            "case_id": state.case_id,
            "status": state.status,
            "source_hash": state.source_hash,
            "event_id": state.event_id,
            "schema_version": state.schema_version,
            "dictionary_version": state.dictionary_version,
            "attempts": state.attempts,
            "last_error": state.last_error,
            "requested_at": state.requested_at,
            "completed_at": state.completed_at,
        }

    @staticmethod
    def _spatial_grid(latitude: float | None, longitude: float | None) -> str | None:
        if latitude is None or longitude is None:
            return None
        return f"{latitude:.2f}:{longitude:.2f}"

    @staticmethod
    def _normalize_text(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        return cleaned or None

    @staticmethod
    def _model_values(model: Any, fields: Iterable[str]) -> dict[str, Any]:
        return {key: CasePipelineService._json_value(getattr(model, key)) for key in fields}

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, datetime):
            # 同一时刻入库前可能带时区，SQLite 读回后无时区；哈希保持一致。
            # 保留既有 SQLite UTC-naive 序列化形态，避免无意义全量重算。
            normalized = value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
            return normalized.isoformat()
        if value is None or isinstance(value, (str, int, float, bool, list, dict)):
            return value
        return str(value)
