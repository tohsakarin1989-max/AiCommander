from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, object_session

from app.models.case import Case
from app.models.chain_link import ChainLink
from app.services.system_config_service import SystemConfigService
from app.utils.chain_classifier import ChainPosition, classify_chain_position, get_chain_position_meta
from app.utils.geo import bounding_box, haversine_km


class ChainAnalysisService:
    ALGORITHM_VERSION = "chain-6.0-source-bound-1"
    DEFAULT_RADIUS_KM = 20.0
    DEFAULT_TIME_WINDOW_DAYS = 180
    DEFAULT_MIN_CONFIDENCE = 0.3

    @staticmethod
    def _float_config(db: Session, key: str, default: float) -> float:
        value = SystemConfigService.get_config_value(db, key, str(default))
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int_config(db: Session, key: str, default: int) -> int:
        value = SystemConfigService.get_config_value(db, key, str(default))
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _config(db: Session) -> Dict[str, float | int]:
        return {
            "radius_km": ChainAnalysisService._float_config(db, "chain_radius_km", ChainAnalysisService.DEFAULT_RADIUS_KM),
            "time_window_days": ChainAnalysisService._int_config(
                db, "chain_time_window_days", ChainAnalysisService.DEFAULT_TIME_WINDOW_DAYS
            ),
            "min_confidence": ChainAnalysisService._float_config(
                db, "chain_min_confidence", ChainAnalysisService.DEFAULT_MIN_CONFIDENCE
            ),
        }

    @staticmethod
    def _has_geo(case: Case) -> bool:
        return case.latitude is not None and case.longitude is not None

    @staticmethod
    def _day_diff(a: Optional[datetime], b: Optional[datetime]) -> Optional[int]:
        if not a or not b:
            return None
        return abs((a - b).days)

    @staticmethod
    def _candidate_pairs(position: ChainPosition) -> List[Tuple[ChainPosition, ChainPosition, str]]:
        if position == "midstream":
            return [
                ("upstream", "midstream", "upstream_transport"),
                ("midstream", "downstream", "transport_storage"),
            ]
        if position == "upstream":
            return [("upstream", "midstream", "upstream_transport")]
        if position == "downstream":
            return [("midstream", "downstream", "transport_storage")]
        return []

    @staticmethod
    def _query_nearby_candidates(
        db: Session,
        base_case: Case,
        expected_position: ChainPosition,
        radius_km: float,
        time_window_days: int,
    ) -> List[Case]:
        if not ChainAnalysisService._has_geo(base_case) or base_case.occurred_time is None:
            return []

        min_lat, max_lat, min_lon, max_lon = bounding_box(base_case.latitude, base_case.longitude, radius_km)
        rough_candidates = (
            db.query(Case)
            .filter(
                Case.id != base_case.id,
                Case.latitude.isnot(None),
                Case.longitude.isnot(None),
                Case.latitude >= min_lat,
                Case.latitude <= max_lat,
                Case.longitude >= min_lon,
                Case.longitude <= max_lon,
            )
            .all()
        )

        candidates: List[Case] = []
        for item in rough_candidates:
            if classify_chain_position(item) != expected_position:
                continue
            time_gap = ChainAnalysisService._day_diff(base_case.occurred_time, item.occurred_time)
            if time_gap is None or time_gap > time_window_days:
                continue
            distance = haversine_km(base_case.latitude, base_case.longitude, item.latitude, item.longitude)
            if distance <= radius_km:
                candidates.append(item)
        return candidates

    @staticmethod
    def _ordered_pair(base_case: Case, candidate: Case, from_position: ChainPosition) -> Tuple[int, int]:
        if classify_chain_position(base_case) == from_position:
            return base_case.id, candidate.id
        return candidate.id, base_case.id

    @staticmethod
    def _rejected_count(db: Session, case_id: int, link_type: str) -> int:
        return (
            db.query(ChainLink)
            .filter(
                ChainLink.link_type == link_type,
                ChainLink.status == "rejected",
                or_(ChainLink.case_id_a == case_id, ChainLink.case_id_b == case_id),
            )
            .count()
        )

    @staticmethod
    def calculate_confidence(
        distance_km: float,
        time_diff_days: int,
        rejected_count: int,
        radius_km: float,
        time_window_days: int,
    ) -> float:
        if radius_km <= 0 or time_window_days <= 0:
            return 0.0
        confidence = (
            1
            - (distance_km / radius_km) * 0.5
            - (time_diff_days / time_window_days) * 0.3
            - rejected_count * 0.2
        )
        return round(max(0.0, min(1.0, confidence)), 4)

    @staticmethod
    def _reasoning(link_type: str, distance_km: float, time_diff_days: int) -> str:
        if link_type == "upstream_transport":
            return f"运输与盗采记录直线相距{distance_km:.1f}公里，时间差{time_diff_days}天；仅为待核验的时空关联，不证明取油路径。"
        return f"运输与囤储记录直线相距{distance_km:.1f}公里，时间差{time_diff_days}天；仅为待核验的时空关联，不证明实际转运去向。"

    @staticmethod
    def scan_chain_links(case_id: int, db: Session, *, commit: bool = True) -> List[ChainLink]:
        base_case = db.query(Case).filter(Case.id == case_id).first()
        if not base_case or not ChainAnalysisService._has_geo(base_case):
            return []

        position = classify_chain_position(base_case)
        if position == "unknown":
            return []

        config = ChainAnalysisService._config(db)
        radius_km = float(config["radius_km"])
        time_window_days = int(config["time_window_days"])
        min_confidence = float(config["min_confidence"])
        links: List[ChainLink] = []

        for from_position, to_position, link_type in ChainAnalysisService._candidate_pairs(position):
            expected_position = to_position if position == from_position else from_position
            candidates = ChainAnalysisService._query_nearby_candidates(
                db, base_case, expected_position, radius_km, time_window_days
            )
            for candidate in candidates:
                case_id_a, case_id_b = ChainAnalysisService._ordered_pair(base_case, candidate, from_position)
                existing = (
                    db.query(ChainLink)
                    .filter(
                        ChainLink.case_id_a == case_id_a,
                        ChainLink.case_id_b == case_id_b,
                        ChainLink.link_type == link_type,
                    )
                    .first()
                )
                if existing:
                    # Human decisions belong to the reviewed source version.
                    # Never overwrite/reconfirm them when a case changes.
                    if existing.status in {"confirmed", "rejected"}:
                        if ChainAnalysisService.freshness(existing, db) == "current":
                            links.append(existing)
                        continue

                distance_km = haversine_km(base_case.latitude, base_case.longitude, candidate.latitude, candidate.longitude)
                time_diff_days = ChainAnalysisService._day_diff(base_case.occurred_time, candidate.occurred_time)
                rejected_count = ChainAnalysisService._rejected_count(db, base_case.id, link_type)
                confidence = ChainAnalysisService.calculate_confidence(
                    distance_km, time_diff_days, rejected_count, radius_km, time_window_days
                )
                if confidence < min_confidence:
                    continue

                link = existing or ChainLink(case_id_a=case_id_a, case_id_b=case_id_b, link_type=link_type)
                link.status = "inferred"
                link.confidence = confidence
                link.distance_km = round(distance_km, 3)
                link.time_diff_days = time_diff_days
                link.reasoning = ChainAnalysisService._reasoning(link_type, distance_km, time_diff_days)
                from app.services.case_pipeline_service import CasePipelineService
                source_a, source_b = (base_case, candidate) if base_case.id == case_id_a else (candidate, base_case)
                link.source_hash_a = CasePipelineService.source_hash(db, source_a)
                link.source_hash_b = CasePipelineService.source_hash(db, source_b)
                link.algorithm_version = ChainAnalysisService.ALGORITHM_VERSION
                db.add(link)
                links.append(link)

        db.flush()
        if commit:
            db.commit()
            for link in links:
                db.refresh(link)
        return sorted(links, key=lambda item: (-item.confidence, item.id))

    @staticmethod
    def confirm_link(link_id: int, operator: str, db: Session) -> Optional[ChainLink]:
        link = db.query(ChainLink).filter(ChainLink.id == link_id).first()
        if not link:
            return None
        if link.status == "confirmed":
            return link
        if ChainAnalysisService.freshness(link, db) != "current":
            raise ValueError("chain_source_changed")
        link.status = "confirmed"
        link.confirmed_by = operator or "人工确认"
        link.confirmed_at = datetime.utcnow()
        db.commit()
        db.refresh(link)
        return link

    @staticmethod
    def reject_link(link_id: int, db: Session) -> Optional[ChainLink]:
        link = db.query(ChainLink).filter(ChainLink.id == link_id).first()
        if not link:
            return None
        link.status = "rejected"
        link.confirmed_by = None
        link.confirmed_at = None
        db.commit()
        db.refresh(link)
        return link

    @staticmethod
    def list_links(db: Session, case_id: Optional[int] = None, include_rejected: bool = False,
                   include_stale: bool = False) -> List[ChainLink]:
        query = db.query(ChainLink)
        if case_id is not None:
            query = query.filter(or_(ChainLink.case_id_a == case_id, ChainLink.case_id_b == case_id))
        if not include_rejected:
            query = query.filter(ChainLink.status != "rejected")
        rows = query.order_by(ChainLink.status.asc(), ChainLink.confidence.desc(), ChainLink.created_at.desc()).all()
        return [link for link in rows if include_stale or link.status in {"confirmed", "rejected"}
                or ChainAnalysisService.freshness(link, db) == "current"]

    @staticmethod
    def get_chain_context(case_id: int, db: Session) -> Dict[str, Any]:
        links = ChainAnalysisService.list_links(db, case_id=case_id, include_rejected=False)
        links = [link for link in links if ChainAnalysisService.freshness(link, db) == "current"]
        upstream: List[Dict[str, Any]] = []
        downstream: List[Dict[str, Any]] = []
        for link in links:
            item = ChainAnalysisService.link_to_dict(link)
            if link.case_id_b == case_id:
                upstream.append(item)
            if link.case_id_a == case_id:
                downstream.append(item)
        return {
            "case_id": case_id,
            "upstream": upstream,
            "downstream": downstream,
            "summary": {
                "total": len(links),
                "confirmed": sum(1 for link in links if link.status == "confirmed"),
                "inferred": sum(1 for link in links if link.status == "inferred"),
            },
            "boundary": "链条关联仅是基于直线距离、时间和环节的辅助假设，不代表实际路径、正式串并案或真实团伙；来源变化后旧推断不再供当前研判使用。",
        }

    @staticmethod
    def freshness(link: ChainLink, db: Session | None = None) -> str:
        """Read-only validity: old confirmations are preserved, not silently rewritten."""
        if not link.source_hash_a or not link.source_hash_b or not link.algorithm_version:
            return "legacy_unversioned"
        if link.algorithm_version != ChainAnalysisService.ALGORITHM_VERSION:
            return "algorithm_changed"
        db = db or object_session(link)
        if db is None:
            return "source_unavailable"
        from app.services.case_pipeline_service import CasePipelineService
        for case_id, expected in ((link.case_id_a, link.source_hash_a), (link.case_id_b, link.source_hash_b)):
            case = db.query(Case).filter(Case.id == case_id).first()
            if case is None:
                return "source_unavailable"
            if CasePipelineService.source_hash(db, case) != expected:
                return "source_changed"
        return "current"

    @staticmethod
    def _case_brief(case: Optional[Case]) -> Optional[Dict[str, Any]]:
        if not case:
            return None
        return {
            "id": case.id,
            "case_number": case.case_number,
            "case_type": case.case_type,
            "facility_type": case.facility_type,
            "chain_position": classify_chain_position(case),
            "chain_label": get_chain_position_meta(classify_chain_position(case))["label"],
            "occurred_time": case.occurred_time.isoformat() if case.occurred_time else None,
            "location": case.location,
            "latitude": case.latitude,
            "longitude": case.longitude,
        }

    @staticmethod
    def link_to_dict(link: ChainLink) -> Dict[str, Any]:
        freshness = ChainAnalysisService.freshness(link)
        return {
            "id": link.id,
            "case_id_a": link.case_id_a,
            "case_id_b": link.case_id_b,
            "link_type": link.link_type,
            "status": link.status,
            "confidence": link.confidence,
            "score_kind": "rule_support",
            "freshness": freshness,
            "source_hash_a": link.source_hash_a,
            "source_hash_b": link.source_hash_b,
            "algorithm_version": link.algorithm_version,
            "source_change_warning": (
                "来源已变化或旧记录未绑定版本，仅保留历史判断，不作为当前有效关联。"
                if freshness != "current" else None
            ),
            "distance_km": link.distance_km,
            "time_diff_days": link.time_diff_days,
            "reasoning": link.reasoning,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "confirmed_by": link.confirmed_by,
            "confirmed_at": link.confirmed_at.isoformat() if link.confirmed_at else None,
            "from_case": ChainAnalysisService._case_brief(link.from_case),
            "to_case": ChainAnalysisService._case_brief(link.to_case),
        }
