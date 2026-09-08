"""v2.6 研判报告、经验卡版本与历史案例复用服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle
from app.models.jurisdiction import JurisdictionAsset
from app.models.knowledge_asset import KnowledgeAsset, KnowledgeReuseRecord
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_quality_service import CaseQualityService


ASSET_TYPES = {"experience_card", "case_report"}
ASSET_STATUSES = {"draft", "confirmed", "archived"}
GENERATOR_VERSION = "2.6.0"
VOLATILE_KEYS = {
    "generated_at",
    "reviewed_at",
    "reviewer",
    "review_note",
    "manual_review_status",
}


class KnowledgeAssetError(ValueError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return value


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    return _json_value(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _stable_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class KnowledgeAssetService:
    """把即时研判结果固化为不可静默覆盖的可审核版本。"""

    @staticmethod
    def generate_experience_asset(
        db: Session,
        case_id: int,
        *,
        generated_by: Optional[int] = None,
    ) -> KnowledgeAsset:
        case = KnowledgeAssetService._case(db, case_id)
        KnowledgeAssetService._ensure_case_quality(db, case)
        analysis_days = 365
        source_data_version = KnowledgeAssetService._experience_source_version(
            db, case, analysis_days
        )
        # 旧版经验卡存放在 Case.features 中，生成动作会更新其中的 generated_at。
        # 版本签名只绑定业务源数据和生成器版本，避免“生成本身”制造新版本。
        source_signature = _digest(
            {
                "asset_type": "experience_card",
                "source_data_version": source_data_version,
                "generator_version": GENERATOR_VERSION,
            }
        )
        existing = KnowledgeAssetService._same_asset(
            db,
            asset_type="experience_card",
            case_id=case_id,
            source_signature=source_signature,
        )
        if existing:
            return existing

        card = CaseIntelligenceService.build_experience_card(db, case_id)
        card = _json_value(card)
        card["manual_review_status"] = "draft"
        card["scope"] = {
            "days": analysis_days,
            "data_version": source_data_version,
        }

        refs = KnowledgeAssetService._case_evidence_refs(db, case)
        asset = KnowledgeAsset(
            asset_type="experience_card",
            source_case_id=case.id,
            version=KnowledgeAssetService._next_version(
                db, "experience_card", case.id
            ),
            title=f"经验卡 {case.case_number}",
            content=card,
            evidence_refs=refs,
            source_signature=source_signature,
            source_data_version=source_data_version,
            status="draft",
            generated_by=generated_by,
        )
        db.add(asset)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            concurrent = KnowledgeAssetService._same_asset(
                db,
                asset_type="experience_card",
                case_id=case.id,
                source_signature=source_signature,
            )
            if concurrent:
                return concurrent
            raise
        db.refresh(asset)
        return asset

    @staticmethod
    def generate_report_snapshot(
        db: Session,
        case_id: int,
        *,
        experience_asset_ids: Iterable[int],
        days: int = 365,
        limit: int = 8,
        generated_by: Optional[int] = None,
    ) -> KnowledgeAsset:
        case = KnowledgeAssetService._case(db, case_id)
        KnowledgeAssetService._ensure_case_quality(db, case)
        selected_ids = list(dict.fromkeys(experience_asset_ids))
        if len(selected_ids) > 10:
            raise KnowledgeAssetError("too_many_experience_assets")

        source_assets: list[KnowledgeAsset] = []
        if selected_ids:
            source_assets = (
                db.query(KnowledgeAsset)
                .filter(KnowledgeAsset.id.in_(selected_ids))
                .order_by(KnowledgeAsset.id.asc())
                .all()
            )
            if len(source_assets) != len(selected_ids):
                raise KnowledgeAssetError("experience_asset_not_found")
            if any(
                item.asset_type != "experience_card"
                or item.status != "confirmed"
                or item.source_case_id == case.id
                for item in source_assets
            ):
                raise KnowledgeAssetError("experience_asset_not_reusable")

        source_data_version = KnowledgeAssetService.case_data_version(db, case)
        scope_data_version = KnowledgeAssetService._report_scope_version(db, days)
        source_signature = _digest(
            {
                "asset_type": "case_report",
                "source_data_version": source_data_version,
                "scope_data_version": scope_data_version,
                "source_asset_signatures": [item.source_signature for item in source_assets],
                "days": days,
                "limit": limit,
                "generator_version": GENERATOR_VERSION,
            }
        )
        existing = KnowledgeAssetService._same_asset(
            db,
            asset_type="case_report",
            case_id=case.id,
            source_signature=source_signature,
        )
        if existing:
            return existing

        report = _json_value(
            CaseIntelligenceService.build_report(
                db,
                case_id=case.id,
                days=days,
                limit=limit,
            )
        )
        reused = [
            KnowledgeAssetService._reused_experience_payload(db, item)
            for item in source_assets
        ]
        refs = list(report.get("ai_output", {}).get("evidence_refs") or [])
        for item in reused:
            refs.append(
                {
                    "id": f"knowledge_asset:{item['asset_id']}",
                    "kind": "confirmed_experience_card",
                    "summary": f"{item['source_case_number']} 已确认经验卡 v{item['version']}",
                    "basis": item["applicability_reasons"],
                }
            )

        if reused:
            lines = [
                "",
                "## 历史经验参考（需逐项核对适用性）",
                *[
                    f"- {item['source_case_number']} 经验卡 v{item['version']}："
                    f"{item['summary']}（仅作参考，不复制历史结论）"
                    for item in reused
                ],
            ]
            report["ai_output"]["markdown"] = (
                report["ai_output"].get("markdown", "").rstrip()
                + "\n"
                + "\n".join(lines)
            ).strip()
            report["markdown"] = (
                report.get("markdown", "").rstrip() + "\n" + "\n".join(lines)
            ).strip()
        report["ai_output"]["evidence_refs"] = refs
        content = {
            "report": report,
            "reused_experience": reused,
            "scope": {"days": days, "data_version": scope_data_version},
            "manual_review_required": True,
            "boundary": [
                "历史经验仅作为引用来源，不自动复制旧案结论。",
                "报告快照为草稿，人工确认前不得作为正式研判结论。",
                "任何坐标异常或条件不一致必须表述为待核验。",
            ],
        }
        asset = KnowledgeAsset(
            asset_type="case_report",
            source_case_id=case.id,
            version=KnowledgeAssetService._next_version(db, "case_report", case.id),
            title=report.get("title") or f"{case.case_number} 案件研判报告",
            content=content,
            evidence_refs=refs,
            source_signature=source_signature,
            source_data_version=source_data_version,
            status="draft",
            generated_by=generated_by,
        )
        db.add(asset)
        try:
            db.flush()
            for source in source_assets:
                KnowledgeAssetService._record_reuse(
                    db,
                    source_asset=source,
                    target_case=case,
                    decision="referenced",
                    purpose="引用到案件研判报告快照",
                    note="由人工选择后写入报告参考章节",
                    target_asset_id=asset.id,
                    created_by=generated_by,
                    applicability={
                        "manual_selection": True,
                        "historical_conclusion_copied": False,
                    },
                )
            db.commit()
        except IntegrityError:
            db.rollback()
            concurrent = KnowledgeAssetService._same_asset(
                db,
                asset_type="case_report",
                case_id=case.id,
                source_signature=source_signature,
            )
            if concurrent:
                return concurrent
            raise
        db.refresh(asset)
        return asset

    @staticmethod
    def review_asset(
        db: Session,
        asset_id: int,
        *,
        status: str,
        reviewed_by: Optional[int] = None,
        reviewer_label: Optional[str] = None,
        note: Optional[str] = None,
    ) -> KnowledgeAsset:
        if status not in {"confirmed", "archived"}:
            raise KnowledgeAssetError("invalid_asset_status")
        asset = KnowledgeAssetService._asset(db, asset_id)
        if asset.status == status:
            return asset
        if status == "confirmed":
            if asset.status != "draft":
                raise KnowledgeAssetError("invalid_asset_transition")
            if not asset.evidence_refs:
                raise KnowledgeAssetError("asset_missing_evidence")
            case = KnowledgeAssetService._case(db, asset.source_case_id)
            if asset.asset_type == "experience_card":
                content = asset.content or {}
                scope = content.get("scope") or {}
                scope_days = int(scope.get("days") or 365)
                current_source_version = (
                    KnowledgeAssetService._experience_source_version(
                        db, case, scope_days
                    )
                )
                if (
                    scope.get("data_version") != current_source_version
                    or asset.source_data_version != current_source_version
                ):
                    raise KnowledgeAssetError("source_changed_since_generation")
            elif asset.source_data_version != KnowledgeAssetService.case_data_version(
                db, case
            ):
                raise KnowledgeAssetError("source_changed_since_generation")
            if asset.asset_type == "case_report":
                content = asset.content or {}
                scope = content.get("scope") or {}
                scope_days = int(scope.get("days") or 365)
                if scope.get("data_version") != KnowledgeAssetService._report_scope_version(
                    db, scope_days
                ):
                    raise KnowledgeAssetError("source_changed_since_generation")
                reused_ids = [
                    item.get("asset_id")
                    for item in content.get("reused_experience", [])
                    if item.get("asset_id")
                ]
                if reused_ids:
                    confirmed_count = (
                        db.query(KnowledgeAsset.id)
                        .filter(
                            KnowledgeAsset.id.in_(reused_ids),
                            KnowledgeAsset.asset_type == "experience_card",
                            KnowledgeAsset.status == "confirmed",
                        )
                        .count()
                    )
                    if confirmed_count != len(set(reused_ids)):
                        raise KnowledgeAssetError("source_changed_since_generation")
        elif status == "archived" and asset.status not in {"draft", "confirmed"}:
            raise KnowledgeAssetError("invalid_asset_transition")

        asset.status = status
        asset.reviewed_by = reviewed_by
        asset.reviewer_label = reviewer_label
        asset.review_note = note
        asset.reviewed_at = datetime.utcnow()
        content = dict(asset.content or {})
        content["manual_review_status"] = status
        asset.content = content
        db.commit()
        db.refresh(asset)
        return asset

    @staticmethod
    def list_assets(
        db: Session,
        *,
        asset_type: Optional[str] = None,
        case_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        if asset_type and asset_type not in ASSET_TYPES:
            raise KnowledgeAssetError("invalid_asset_type")
        if status and status not in ASSET_STATUSES:
            raise KnowledgeAssetError("invalid_asset_status")
        query = db.query(KnowledgeAsset)
        if asset_type:
            query = query.filter(KnowledgeAsset.asset_type == asset_type)
        if case_id is not None:
            query = query.filter(KnowledgeAsset.source_case_id == case_id)
        if status:
            query = query.filter(KnowledgeAsset.status == status)
        assets = query.order_by(
            KnowledgeAsset.created_at.desc(), KnowledgeAsset.id.desc()
        ).limit(limit).all()
        return {
            "items": [KnowledgeAssetService.asset_payload(db, item) for item in assets],
            "total": len(assets),
        }

    @staticmethod
    def reuse_recommendations(
        db: Session,
        case_id: int,
        *,
        days: int = 730,
        limit: int = 8,
    ) -> Dict[str, Any]:
        target = KnowledgeAssetService._case(db, case_id)
        similar = CaseIntelligenceService.find_similar_cases(
            db, case_id, days=days, limit=200
        )
        items = []
        for candidate in similar.get("items", []):
            source_case = candidate.get("case") or {}
            source_case_id = source_case.get("id")
            if not source_case_id or source_case_id == target.id:
                continue
            asset = (
                db.query(KnowledgeAsset)
                .filter(
                    KnowledgeAsset.asset_type == "experience_card",
                    KnowledgeAsset.source_case_id == source_case_id,
                    KnowledgeAsset.status == "confirmed",
                )
                .order_by(KnowledgeAsset.version.desc())
                .first()
            )
            if not asset:
                continue
            latest_reuse = (
                db.query(KnowledgeReuseRecord)
                .filter(
                    KnowledgeReuseRecord.source_asset_id == asset.id,
                    KnowledgeReuseRecord.target_case_id == target.id,
                )
                .order_by(KnowledgeReuseRecord.created_at.desc(), KnowledgeReuseRecord.id.desc())
                .first()
            )
            warnings = list(candidate.get("duplicate_warnings") or [])
            warnings.append("历史经验仅证明旧案做法，当前案件仍需核对时间、地点和证据差异。")
            items.append(
                {
                    "asset_id": asset.id,
                    "version": asset.version,
                    "status": asset.status,
                    "source_case_id": source_case_id,
                    "source_case_number": source_case.get("case_number"),
                    "title": asset.title,
                    "summary": (asset.content or {}).get("summary") or asset.title,
                    "similarity_score": candidate.get("similarity_score", 0),
                    "applicability_reasons": candidate.get("reasons") or [],
                    "mismatch_risks": warnings,
                    "shared_tags": candidate.get("shared_tags") or [],
                    "evidence_refs": asset.evidence_refs or [],
                    "latest_decision": latest_reuse.decision if latest_reuse else None,
                    "already_reused": bool(
                        latest_reuse and latest_reuse.decision in {"accepted", "referenced"}
                    ),
                }
            )
            if len(items) >= limit:
                break
        return {
            "target_case_id": target.id,
            "target_case_number": target.case_number,
            "items": items,
            "manual_selection_required": True,
            "boundary": "只推荐已人工确认的历史经验；相似不等于同案，不复制旧结论，引用后仍需人工复核。",
        }

    @staticmethod
    def record_reuse_decision(
        db: Session,
        *,
        source_asset_id: int,
        target_case_id: int,
        decision: str,
        purpose: str,
        note: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> tuple[KnowledgeReuseRecord, bool]:
        if decision not in {"accepted", "rejected"}:
            raise KnowledgeAssetError("invalid_reuse_decision")
        purpose = purpose.strip()
        if not purpose:
            raise KnowledgeAssetError("invalid_reuse_purpose")
        source = KnowledgeAssetService._asset(db, source_asset_id)
        target = KnowledgeAssetService._case(db, target_case_id)
        if source.asset_type != "experience_card" or source.status != "confirmed":
            raise KnowledgeAssetError("experience_asset_not_reusable")
        if source.source_case_id == target.id:
            raise KnowledgeAssetError("cannot_reuse_same_case")
        key = _digest(
            {
                "source_asset_id": source.id,
                "target_case_id": target.id,
                "decision": decision,
                "purpose": purpose,
            }
        )
        existing = (
            db.query(KnowledgeReuseRecord)
            .filter(KnowledgeReuseRecord.idempotency_key == key)
            .first()
        )
        if existing:
            return existing, False
        record = KnowledgeAssetService._record_reuse(
            db,
            source_asset=source,
            target_case=target,
            decision=decision,
            purpose=purpose,
            note=note,
            created_by=created_by,
            applicability={
                "manual_decision": True,
                "target_mutated": False,
                "historical_conclusion_copied": False,
            },
            idempotency_key=key,
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            concurrent = (
                db.query(KnowledgeReuseRecord)
                .filter(KnowledgeReuseRecord.idempotency_key == key)
                .first()
            )
            if concurrent:
                return concurrent, False
            raise
        db.refresh(record)
        return record, True

    @staticmethod
    def list_reuse_records(
        db: Session,
        *,
        target_case_id: int,
        limit: int = 100,
    ) -> Dict[str, Any]:
        KnowledgeAssetService._case(db, target_case_id)
        records = (
            db.query(KnowledgeReuseRecord)
            .filter(KnowledgeReuseRecord.target_case_id == target_case_id)
            .order_by(KnowledgeReuseRecord.created_at.desc(), KnowledgeReuseRecord.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "target_case_id": target_case_id,
            "items": [KnowledgeAssetService.reuse_payload(db, item) for item in records],
            "total": len(records),
        }

    @staticmethod
    def asset_payload(db: Session, asset: KnowledgeAsset) -> Dict[str, Any]:
        case = db.query(Case).filter(Case.id == asset.source_case_id).first()
        return {
            "id": asset.id,
            "asset_type": asset.asset_type,
            "source_case_id": asset.source_case_id,
            "source_case_number": case.case_number if case else None,
            "version": asset.version,
            "title": asset.title,
            "content": asset.content or {},
            "evidence_refs": asset.evidence_refs or [],
            "source_signature": asset.source_signature,
            "source_data_version": asset.source_data_version,
            "status": asset.status,
            "reviewer_label": asset.reviewer_label,
            "review_note": asset.review_note,
            "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        }

    @staticmethod
    def reuse_payload(db: Session, record: KnowledgeReuseRecord) -> Dict[str, Any]:
        source = db.query(KnowledgeAsset).filter(KnowledgeAsset.id == record.source_asset_id).first()
        source_case = (
            db.query(Case).filter(Case.id == source.source_case_id).first()
            if source
            else None
        )
        return {
            "id": record.id,
            "source_asset_id": record.source_asset_id,
            "source_case_id": source.source_case_id if source else None,
            "source_case_number": source_case.case_number if source_case else None,
            "target_case_id": record.target_case_id,
            "target_asset_id": record.target_asset_id,
            "decision": record.decision,
            "purpose": record.purpose,
            "applicability": record.applicability or {},
            "note": record.note,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    @staticmethod
    def case_data_version(db: Session, case: Case) -> str:
        evidence = (
            db.query(CaseEvidence)
            .filter(CaseEvidence.case_id == case.id)
            .order_by(CaseEvidence.id.asc())
            .all()
        )
        vehicles = (
            db.query(CaseVehicle)
            .filter(CaseVehicle.case_id == case.id)
            .order_by(CaseVehicle.id.asc())
            .all()
        )
        persons = (
            db.query(CasePerson)
            .filter(CasePerson.case_id == case.id)
            .order_by(CasePerson.id.asc())
            .all()
        )
        return _digest(
            KnowledgeAssetService._case_data_payload(
                case,
                evidence=evidence,
                vehicles=vehicles,
                persons=persons,
            )
        )

    @staticmethod
    def _experience_source_version(
        db: Session,
        case: Case,
        days: int,
    ) -> str:
        tags = CaseIntelligenceService.build_case_tags(db, case)
        similar = CaseIntelligenceService.find_similar_cases(
            db,
            case.id,
            days=days,
            limit=8,
        )
        return _digest(
            {
                "case_data_version": KnowledgeAssetService.case_data_version(
                    db, case
                ),
                "feature_tags": tags,
                "similar_cases": similar,
                "days": days,
            }
        )

    @staticmethod
    def _report_scope_version(db: Session, days: int) -> str:
        cutoff = datetime.utcnow() - timedelta(days=days)
        cases = (
            db.query(Case)
            .filter(Case.occurred_time >= cutoff)
            .order_by(Case.id.asc())
            .all()
        )
        assets = (
            db.query(JurisdictionAsset)
            .order_by(JurisdictionAsset.id.asc())
            .all()
        )
        case_ids = [item.id for item in cases]
        evidence_by_case: Dict[int, list[CaseEvidence]] = {}
        vehicles_by_case: Dict[int, list[CaseVehicle]] = {}
        persons_by_case: Dict[int, list[CasePerson]] = {}
        if case_ids:
            for item in (
                db.query(CaseEvidence)
                .filter(CaseEvidence.case_id.in_(case_ids))
                .order_by(CaseEvidence.case_id.asc(), CaseEvidence.id.asc())
                .all()
            ):
                evidence_by_case.setdefault(item.case_id, []).append(item)
            for item in (
                db.query(CaseVehicle)
                .filter(CaseVehicle.case_id.in_(case_ids))
                .order_by(CaseVehicle.case_id.asc(), CaseVehicle.id.asc())
                .all()
            ):
                vehicles_by_case.setdefault(item.case_id, []).append(item)
            for item in (
                db.query(CasePerson)
                .filter(CasePerson.case_id.in_(case_ids))
                .order_by(CasePerson.case_id.asc(), CasePerson.id.asc())
                .all()
            ):
                persons_by_case.setdefault(item.case_id, []).append(item)
        return _digest(
            {
                "cases": [
                    _digest(
                        KnowledgeAssetService._case_data_payload(
                            item,
                            evidence=evidence_by_case.get(item.id, []),
                            vehicles=vehicles_by_case.get(item.id, []),
                            persons=persons_by_case.get(item.id, []),
                        )
                    )
                    for item in cases
                ],
                "jurisdiction_assets": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "asset_type": item.asset_type,
                        "geometry_type": item.geometry_type,
                        "latitude": item.latitude,
                        "longitude": item.longitude,
                        "status": item.status,
                        "verified": item.verified,
                        "risk_level": item.risk_level,
                        "tags": item.tags,
                    }
                    for item in assets
                ],
            }
        )

    @staticmethod
    def _case_data_payload(
        case: Case,
        *,
        evidence: Iterable[CaseEvidence],
        vehicles: Iterable[CaseVehicle],
        persons: Iterable[CasePerson],
    ) -> Dict[str, Any]:
        case_fields = {
            column.name: getattr(case, column.name)
            for column in Case.__table__.columns
            if column.name not in {"created_at", "updated_at", "quality_updated_at"}
        }
        features = dict(case_fields.get("features") or {})
        intelligence = dict(features.get("intelligence") or {})
        intelligence.pop("experience_card", None)
        if intelligence:
            features["intelligence"] = intelligence
        else:
            features.pop("intelligence", None)
        case_fields["features"] = features
        return {
            "case": case_fields,
            "evidence": [
                {
                    column.name: getattr(item, column.name)
                    for column in CaseEvidence.__table__.columns
                    if column.name not in {"created_at", "updated_at"}
                }
                for item in evidence
            ],
            "vehicles": [
                {
                    column.name: getattr(item, column.name)
                    for column in CaseVehicle.__table__.columns
                    if column.name not in {"created_at", "updated_at"}
                }
                for item in vehicles
            ],
            "persons": [
                {
                    column.name: getattr(item, column.name)
                    for column in CasePerson.__table__.columns
                    if column.name not in {"created_at", "updated_at"}
                }
                for item in persons
            ],
        }

    @staticmethod
    def _ensure_case_quality(db: Session, case: Case) -> None:
        if case.quality_issues:
            return
        CaseQualityService.refresh_case_quality(db, case)
        db.refresh(case)

    @staticmethod
    def _case_evidence_refs(db: Session, case: Case) -> list[Dict[str, Any]]:
        refs = [
            {
                "id": f"case:{case.id}",
                "kind": "case",
                "summary": f"案件 {case.case_number}",
            }
        ]
        refs.extend(
            {
                "id": f"case_evidence:{item.id}",
                "kind": "case_evidence",
                "summary": item.title or item.requirement_key or "案件证据",
            }
            for item in db.query(CaseEvidence)
            .filter(CaseEvidence.case_id == case.id)
            .order_by(CaseEvidence.id.asc())
            .limit(20)
            .all()
        )
        return refs

    @staticmethod
    def _reused_experience_payload(
        db: Session, asset: KnowledgeAsset
    ) -> Dict[str, Any]:
        case = KnowledgeAssetService._case(db, asset.source_case_id)
        content = asset.content or {}
        return {
            "asset_id": asset.id,
            "version": asset.version,
            "source_case_id": case.id,
            "source_case_number": case.case_number,
            "summary": content.get("summary") or asset.title,
            "applicability_reasons": [
                "该经验卡已经人工确认。",
                "由研判人员主动选入本次报告，仍需逐项核对当前案件差异。",
            ],
            "evidence_refs": asset.evidence_refs or [],
        }

    @staticmethod
    def _record_reuse(
        db: Session,
        *,
        source_asset: KnowledgeAsset,
        target_case: Case,
        decision: str,
        purpose: str,
        applicability: Dict[str, Any],
        note: Optional[str] = None,
        target_asset_id: Optional[int] = None,
        created_by: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> KnowledgeReuseRecord:
        key = idempotency_key or _digest(
            {
                "source_asset_id": source_asset.id,
                "target_case_id": target_case.id,
                "target_asset_id": target_asset_id,
                "decision": decision,
                "purpose": purpose,
            }
        )
        existing = (
            db.query(KnowledgeReuseRecord)
            .filter(KnowledgeReuseRecord.idempotency_key == key)
            .first()
        )
        if existing:
            return existing
        record = KnowledgeReuseRecord(
            source_asset_id=source_asset.id,
            target_case_id=target_case.id,
            target_asset_id=target_asset_id,
            decision=decision,
            purpose=purpose.strip(),
            applicability=applicability,
            note=note,
            idempotency_key=key,
            created_by=created_by,
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def _same_asset(
        db: Session,
        *,
        asset_type: str,
        case_id: int,
        source_signature: str,
    ) -> Optional[KnowledgeAsset]:
        return (
            db.query(KnowledgeAsset)
            .filter(
                KnowledgeAsset.asset_type == asset_type,
                KnowledgeAsset.source_case_id == case_id,
                KnowledgeAsset.source_signature == source_signature,
            )
            .order_by(KnowledgeAsset.version.desc())
            .first()
        )

    @staticmethod
    def _next_version(db: Session, asset_type: str, case_id: int) -> int:
        latest = (
            db.query(KnowledgeAsset)
            .filter(
                KnowledgeAsset.asset_type == asset_type,
                KnowledgeAsset.source_case_id == case_id,
            )
            .order_by(KnowledgeAsset.version.desc())
            .first()
        )
        return (latest.version if latest else 0) + 1

    @staticmethod
    def _case(db: Session, case_id: int) -> Case:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise KnowledgeAssetError("case_not_found")
        return case

    @staticmethod
    def _asset(db: Session, asset_id: int) -> KnowledgeAsset:
        asset = db.query(KnowledgeAsset).filter(KnowledgeAsset.id == asset_id).first()
        if not asset:
            raise KnowledgeAssetError("knowledge_asset_not_found")
        return asset
