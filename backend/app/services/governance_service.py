"""统一版本追踪、脱敏评测和无副作用部署方案对比。"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.deployment_advisor import DeploymentRecommendation, SituationBrief
from app.models.governance import (
    AlgorithmVersion,
    EvaluationDataset,
    EvaluationRun,
    ScopePolicyVersion,
)
from app.models.map_foundation import MapSnapshot
from app.repositories.spatial_repository import SpatialRepository
from app.services.case_insight_service import SOURCE_TYPES


SCOPE_POLICY_VERSION = "area-scope-3.6.0"
ALGORITHMS = {
    "case-profile": ("case-profile-3.3.0", {"mode": "deterministic", "max_gaps": 3}),
    "dual-domain": ("dual-domain-3.4.0", {"mode": "deterministic", "max_candidates": 3}),
    "deployment-advisor": ("deployment-advisor-3.5.0", {"mode": "deterministic", "max_advice": 3}),
}
SCOPE_POLICY = {
    "dimensions": ["operational_area", "role", "access_level"],
    "default": "deny",
    "raw_case_external_model": False,
    "precise_production_coordinate_external_model": False,
    "agent_formal_fact_write": False,
    "agent_execution_task_create": False,
}


class GovernanceService:
    @staticmethod
    def ensure_versions(db: Session) -> dict[str, Any]:
        algorithms = []
        for component, (version, configuration) in ALGORITHMS.items():
            checksum = GovernanceService._checksum(configuration)
            item = (
                db.query(AlgorithmVersion)
                .filter(
                    AlgorithmVersion.component == component,
                    AlgorithmVersion.version == version,
                )
                .first()
            )
            if item is None:
                item = AlgorithmVersion(
                    component=component,
                    version=version,
                    configuration=configuration,
                    checksum=checksum,
                    status="active",
                )
                db.add(item)
            algorithms.append({"component": component, "version": version, "checksum": checksum})
        policy = db.query(ScopePolicyVersion).filter(
            ScopePolicyVersion.version == SCOPE_POLICY_VERSION
        ).first()
        if policy is None:
            policy = ScopePolicyVersion(
                version=SCOPE_POLICY_VERSION,
                policy=SCOPE_POLICY,
                checksum=GovernanceService._checksum(SCOPE_POLICY),
                status="active",
            )
            db.add(policy)
        db.commit()
        return {
            "algorithms": algorithms,
            "scope_policy": {
                "version": policy.version,
                "checksum": policy.checksum,
            },
        }

    @staticmethod
    def create_dataset(
        db: Session,
        *,
        name: str,
        version: str,
        case_ids: list[int],
        classification: str,
        ground_truth: dict[str, list[dict[str, Any]]] | None = None,
        created_by: int | None = None,
    ) -> EvaluationDataset:
        if classification != "redacted":
            raise ValueError("redacted_dataset_required")
        normalized_ids = sorted(set(int(item) for item in case_ids))
        if not normalized_ids or len(normalized_ids) > 5000:
            raise ValueError("invalid_dataset_size")
        visible_ids = {
            item[0]
            for item in db.query(Case.id).filter(Case.id.in_(normalized_ids)).all()
        }
        if visible_ids != set(normalized_ids):
            raise ValueError("dataset_case_not_found_or_out_of_scope")
        normalized_ground_truth = GovernanceService._normalize_ground_truth(
            ground_truth or {}, normalized_ids
        )
        ground_truth_label_count = sum(
            len(labels) for labels in normalized_ground_truth.values()
        )
        manifest = {
            "case_count": len(normalized_ids),
            "case_ids": normalized_ids,
            "classification": "redacted",
            "contains_raw_case_text": False,
            "contains_precise_production_coordinates": False,
            "ground_truth_case_count": len(normalized_ground_truth),
            "ground_truth_label_count": ground_truth_label_count,
            "ground_truth_checksum": GovernanceService._checksum(normalized_ground_truth),
        }
        existing = (
            db.query(EvaluationDataset)
            .filter(EvaluationDataset.name == name.strip(), EvaluationDataset.version == version.strip())
            .first()
        )
        if existing:
            if existing.checksum != GovernanceService._checksum(manifest):
                raise ValueError("dataset_version_conflict")
            return existing
        dataset = EvaluationDataset(
            name=name.strip()[:200],
            version=version.strip()[:80],
            classification="redacted",
            case_ids=normalized_ids,
            ground_truth=normalized_ground_truth,
            manifest=manifest,
            checksum=GovernanceService._checksum(manifest),
            created_by=created_by,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        return dataset

    @staticmethod
    def run_evaluation(db: Session, *, dataset_id: int) -> EvaluationRun:
        dataset = db.query(EvaluationDataset).filter(EvaluationDataset.id == dataset_id).first()
        if not dataset:
            raise ValueError("dataset_not_found")
        versions = GovernanceService.ensure_versions(db)
        case_ids = list(dataset.case_ids or [])
        active_algorithm = ALGORITHMS["dual-domain"][0]
        hypotheses = (
            db.query(CaseHypothesis)
            .join(CaseAnalysisRun, CaseAnalysisRun.id == CaseHypothesis.analysis_run_id)
            .join(CaseAnalysisProfile, CaseAnalysisProfile.id == CaseAnalysisRun.case_profile_id)
            .join(MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id)
            .filter(
                CaseHypothesis.case_id.in_(case_ids),
                CaseHypothesis.status == "candidate",
                CaseAnalysisProfile.is_current.is_(True),
                MapSnapshot.status == "current",
                CaseAnalysisRun.algorithm_version == active_algorithm,
            )
            .order_by(CaseHypothesis.case_id, CaseHypothesis.rank)
            .all()
        )
        hypothesis_ids = [item.id for item in hypotheses]
        feedback_rows = (
            db.query(HypothesisFeedback)
            .filter(HypothesisFeedback.hypothesis_id.in_(hypothesis_ids))
            .order_by(HypothesisFeedback.created_at, HypothesisFeedback.id)
            .all()
            if hypothesis_ids
            else []
        )
        latest_feedback = {item.hypothesis_id: item.decision for item in feedback_rows}
        total = len(hypotheses)
        evidence_count = sum(bool(item.evidence_refs) for item in hypotheses)
        counter_or_gap_count = sum(
            bool(item.counter_evidence or item.information_gaps) for item in hypotheses
        )
        useful_cases = {
            item.case_id
            for item in hypotheses
            if item.rank <= 3 and latest_feedback.get(item.id) == "useful"
        }
        high_conf_items = [item for item in hypotheses if item.confidence >= 0.8]
        reviewed_high_conf_items = [
            item for item in high_conf_items if item.id in latest_feedback
        ]
        high_conf_feedback_errors = sum(
            latest_feedback.get(item.id) == "not_useful" for item in reviewed_high_conf_items
        )
        analysis_runs = (
            db.query(CaseAnalysisRun)
            .join(
                CaseAnalysisProfile,
                CaseAnalysisProfile.id == CaseAnalysisRun.case_profile_id,
            )
            .join(MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id)
            .filter(
                CaseAnalysisRun.case_id.in_(case_ids),
                CaseAnalysisRun.algorithm_version == active_algorithm,
                CaseAnalysisProfile.is_current.is_(True),
                MapSnapshot.status == "current",
            )
            .order_by(CaseAnalysisRun.started_at, CaseAnalysisRun.id)
            .all()
        )
        run_ids = sorted(item.id for item in analysis_runs)
        ground_truth = dict(dataset.ground_truth or {})
        labeled_case_ids = {int(case_id) for case_id in ground_truth}
        matched_labels = 0
        matched_cases: set[int] = set()
        ground_truth_label_count = sum(len(labels) for labels in ground_truth.values())
        hypotheses_by_case: dict[int, list[CaseHypothesis]] = {}
        for item in hypotheses:
            if item.rank <= 3:
                hypotheses_by_case.setdefault(item.case_id, []).append(item)
        for case_id_text, labels in ground_truth.items():
            case_id = int(case_id_text)
            case_matched = False
            for label in labels:
                if any(
                    GovernanceService._hypothesis_matches_ground_truth(item, label)
                    for item in hypotheses_by_case.get(case_id, [])
                ):
                    matched_labels += 1
                    case_matched = True
            if case_matched:
                matched_cases.add(case_id)

        analysis_runs_by_case = {item.case_id: item for item in analysis_runs}
        cases_by_id = {
            item.id: item
            for item in db.query(Case).filter(Case.id.in_(case_ids)).all()
        }
        source_assessable_cases: set[int] = set()
        source_algorithm_hits: set[int] = set()
        nearest_baseline_hits: set[int] = set()
        for case_id_text, labels in ground_truth.items():
            case_id = int(case_id_text)
            source_labels = [
                label
                for label in labels
                if label.get("hypothesis_type") == "possible_source"
            ]
            case = cases_by_id.get(case_id)
            analysis_run = analysis_runs_by_case.get(case_id)
            if (
                not source_labels
                or case is None
                or analysis_run is None
                or case.latitude is None
                or case.longitude is None
            ):
                continue
            source_assessable_cases.add(case_id)
            if any(
                GovernanceService._hypothesis_matches_ground_truth(item, label)
                for item in hypotheses_by_case.get(case_id, [])
                if item.hypothesis_type == "possible_source"
                for label in source_labels
            ):
                source_algorithm_hits.add(case_id)
            nearest = SpatialRepository.nearby_assets(
                db,
                latitude=case.latitude,
                longitude=case.longitude,
                asset_types=SOURCE_TYPES,
                radius_km=20,
                operational_area_id=case.operational_area_id,
                snapshot_id=analysis_run.map_snapshot_id,
                limit=1,
            )
            if nearest and any(
                GovernanceService._asset_matches_ground_truth(nearest[0][0], label)
                for label in source_labels
            ):
                nearest_baseline_hits.add(case_id)

        source_hit_rate = GovernanceService._optional_ratio(
            len(source_algorithm_hits), len(source_assessable_cases)
        )
        nearest_baseline_rate = GovernanceService._optional_ratio(
            len(nearest_baseline_hits), len(source_assessable_cases)
        )
        source_lift_percentage_points = (
            round((source_hit_rate - nearest_baseline_rate) * 100, 2)
            if source_hit_rate is not None and nearest_baseline_rate is not None
            else None
        )
        assessable_high_conf_items: list[CaseHypothesis] = []
        high_conf_ground_truth_errors = 0
        for item in high_conf_items:
            if item.rank > 3:
                continue
            labels = [
                label
                for label in ground_truth.get(str(item.case_id), [])
                if label.get("hypothesis_type") == item.hypothesis_type
            ]
            if not labels:
                continue
            assessable_high_conf_items.append(item)
            if not any(
                GovernanceService._hypothesis_matches_ground_truth(item, label)
                for label in labels
            ):
                high_conf_ground_truth_errors += 1
        metrics = {
            "case_count": len(case_ids),
            "candidate_count": total,
            "evidence_coverage": GovernanceService._ratio(evidence_count, total),
            "counter_or_gap_coverage": GovernanceService._ratio(counter_or_gap_count, total),
            "top3_useful_case_rate": GovernanceService._ratio(len(useful_cases), len(case_ids)),
            "top3_ground_truth_hit_rate": GovernanceService._optional_ratio(
                len(matched_cases), len(labeled_case_ids)
            ),
            "ground_truth_label_recall": GovernanceService._optional_ratio(
                matched_labels, ground_truth_label_count
            ),
            "ground_truth_coverage": GovernanceService._ratio(
                len(labeled_case_ids), len(case_ids)
            ),
            "high_confidence_error_rate": GovernanceService._optional_ratio(
                high_conf_ground_truth_errors, len(assessable_high_conf_items)
            ),
            "high_confidence_feedback_error_rate": GovernanceService._optional_ratio(
                high_conf_feedback_errors, len(reviewed_high_conf_items)
            ),
            "high_confidence_feedback_coverage": GovernanceService._ratio(
                len(reviewed_high_conf_items), len(high_conf_items)
            ),
            "source_top3_ground_truth_hit_rate": source_hit_rate,
            "nearest_facility_baseline_hit_rate": nearest_baseline_rate,
            "source_top3_lift_percentage_points": source_lift_percentage_points,
            "source_baseline_assessable_case_count": len(source_assessable_cases),
            "feedback_coverage": GovernanceService._ratio(len(latest_feedback), total),
            "metric_basis": "current_profile_current_map_ground_truth_and_human_feedback",
        }
        trace_manifest = {
            "dataset_checksum": dataset.checksum,
            "ground_truth_checksum": dataset.manifest.get("ground_truth_checksum"),
            "analysis_run_ids": run_ids,
            "case_profile_ids": sorted({item.case_profile_id for item in analysis_runs}),
            "map_snapshot_ids": sorted({item.map_snapshot_id for item in analysis_runs}),
            "algorithm_versions": sorted({item.algorithm_version for item in analysis_runs}),
        }
        evaluation = EvaluationRun(
            id=str(uuid.uuid4()),
            dataset_id=dataset.id,
            algorithm_manifest=versions["algorithms"],
            scope_policy_version=versions["scope_policy"]["version"],
            status="completed",
            metrics=metrics,
            trace_manifest=trace_manifest,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)
        return evaluation

    @staticmethod
    def case_lineage(db: Session, case_id: int) -> dict[str, Any]:
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError("case_not_found_or_out_of_scope")
        profile = (
            db.query(CaseAnalysisProfile)
            .filter(CaseAnalysisProfile.case_id == case.id, CaseAnalysisProfile.is_current.is_(True))
            .order_by(CaseAnalysisProfile.profile_version.desc())
            .first()
        )
        run = (
            db.query(CaseAnalysisRun)
            .join(MapSnapshot, MapSnapshot.id == CaseAnalysisRun.map_snapshot_id)
            .filter(
                CaseAnalysisRun.case_id == case.id,
                CaseAnalysisRun.case_profile_id == profile.id if profile else False,
                MapSnapshot.status == "current",
            )
            .order_by(CaseAnalysisRun.completed_at.desc(), CaseAnalysisRun.started_at.desc())
            .first()
        )
        snapshot = (
            db.query(MapSnapshot).filter(MapSnapshot.id == run.map_snapshot_id).first()
            if run
            else None
        )
        return {
            "case": {"id": case.id, "case_number": case.case_number},
            "case_profile": (
                {
                    "id": profile.id,
                    "version": profile.profile_version,
                    "schema_version": profile.schema_version,
                    "dictionary_version": profile.dictionary_version,
                    "source_hash": profile.source_hash,
                }
                if profile
                else None
            ),
            "analysis_run_id": run.id if run else None,
            "analysis_status": run.status if run else "pending_current_versions",
            "algorithm_version": run.algorithm_version if run else None,
            "map_snapshot": (
                {
                    "id": snapshot.id,
                    "version": snapshot.version,
                    "feature_watermark": snapshot.feature_watermark,
                }
                if snapshot
                else None
            ),
            "scope_policy_version": SCOPE_POLICY_VERSION,
            "formal_case_changed_by_agent": False,
        }

    @staticmethod
    def compare_deployment_scenarios(
        db: Session,
        *,
        recommendation_ids: list[str],
        scenarios: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ids = list(dict.fromkeys(recommendation_ids))[:20]
        recommendations = (
            db.query(DeploymentRecommendation)
            .join(SituationBrief, SituationBrief.id == DeploymentRecommendation.brief_id)
            .filter(DeploymentRecommendation.id.in_(ids))
            .all()
        )
        if len(recommendations) != len(ids):
            raise ValueError("recommendation_not_found_or_out_of_scope")
        results = []
        for scenario in scenarios[:5]:
            name = str(scenario.get("name") or "未命名方案")[:100]
            coverage_factor = max(0.0, min(1.0, float(scenario.get("coverage_factor", 1))))
            availability_factor = max(0.0, min(1.0, float(scenario.get("availability_factor", 1))))
            scores = [item.confidence * coverage_factor * availability_factor for item in recommendations]
            results.append({
                "name": name,
                "estimated_coverage_score": round(sum(scores) / max(1, len(scores)), 3),
                "assumptions": {
                    "coverage_factor": coverage_factor,
                    "availability_factor": availability_factor,
                },
                "boundary": "仅比较覆盖假设，不创建、不调度任何执行任务。",
            })
        results.sort(key=lambda item: (-item["estimated_coverage_score"], item["name"]))
        return {"scenarios": results, "execution_task_created": False, "persisted": False}

    @staticmethod
    def _checksum(payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    @staticmethod
    def _optional_ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    @staticmethod
    def _normalize_ground_truth(
        ground_truth: dict[str, list[dict[str, Any]]],
        case_ids: list[int],
    ) -> dict[str, list[dict[str, Any]]]:
        allowed_cases = set(case_ids)
        allowed_types = {
            "possible_source",
            "storage_area",
            "activity_area",
            "transfer_route",
        }
        if len(ground_truth) > len(case_ids):
            raise ValueError("invalid_ground_truth")
        normalized: dict[str, list[dict[str, Any]]] = {}
        total_labels = 0
        for raw_case_id, raw_labels in ground_truth.items():
            try:
                case_id = int(raw_case_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid_ground_truth") from exc
            if case_id not in allowed_cases or not isinstance(raw_labels, list):
                raise ValueError("invalid_ground_truth")
            if not raw_labels or len(raw_labels) > 20:
                raise ValueError("invalid_ground_truth")
            labels: list[dict[str, Any]] = []
            for raw_label in raw_labels:
                if not isinstance(raw_label, dict):
                    raise ValueError("invalid_ground_truth")
                hypothesis_type = str(raw_label.get("hypothesis_type") or "")
                if hypothesis_type not in allowed_types:
                    raise ValueError("invalid_ground_truth")
                try:
                    asset_ids = sorted(
                        {
                            int(item)
                            for item in (raw_label.get("expected_asset_ids") or [])
                            if int(item) > 0
                        }
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid_ground_truth") from exc
                if len(asset_ids) > 20:
                    raise ValueError("invalid_ground_truth")
                raw_grid = raw_label.get("expected_region_grid")
                region_grid = None
                if raw_grid:
                    try:
                        latitude_text, longitude_text = str(raw_grid).split(":", 1)
                        latitude = float(latitude_text)
                        longitude = float(longitude_text)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("invalid_ground_truth") from exc
                    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                        raise ValueError("invalid_ground_truth")
                    region_grid = f"{latitude:.2f}:{longitude:.2f}"
                if not asset_ids and region_grid is None:
                    raise ValueError("invalid_ground_truth")
                labels.append(
                    {
                        "hypothesis_type": hypothesis_type,
                        "expected_asset_ids": asset_ids,
                        "expected_region_grid": region_grid,
                    }
                )
            total_labels += len(labels)
            if total_labels > 10000:
                raise ValueError("invalid_ground_truth")
            normalized[str(case_id)] = labels
        return dict(sorted(normalized.items(), key=lambda item: int(item[0])))

    @staticmethod
    def _hypothesis_matches_ground_truth(
        hypothesis: CaseHypothesis,
        label: dict[str, Any],
    ) -> bool:
        if hypothesis.hypothesis_type != label.get("hypothesis_type"):
            return False
        expected_asset_ids = set(label.get("expected_asset_ids") or [])
        referenced_asset_ids: set[int] = set()
        for reference in hypothesis.evidence_refs or []:
            text = str(reference)
            if not text.startswith("map_asset:"):
                continue
            identifier = text.removeprefix("map_asset:").split("@", 1)[0]
            try:
                referenced_asset_ids.add(int(identifier))
            except ValueError:
                continue
        asset_match = bool(expected_asset_ids & referenced_asset_ids)

        expected_grid = label.get("expected_region_grid")
        region_match = False
        center = (hypothesis.region or {}).get("center")
        if expected_grid and isinstance(center, list) and len(center) == 2:
            try:
                longitude, latitude = float(center[0]), float(center[1])
                region_match = f"{latitude:.2f}:{longitude:.2f}" == expected_grid
            except (TypeError, ValueError):
                region_match = False
        return asset_match or region_match

    @staticmethod
    def _asset_matches_ground_truth(asset: Any, label: dict[str, Any]) -> bool:
        asset_id = getattr(asset, "asset_id", None) or getattr(asset, "id", None)
        if asset_id in set(label.get("expected_asset_ids") or []):
            return True
        expected_grid = label.get("expected_region_grid")
        latitude = getattr(asset, "latitude", None)
        longitude = getattr(asset, "longitude", None)
        if expected_grid and latitude is not None and longitude is not None:
            return f"{float(latitude):.2f}:{float(longitude):.2f}" == expected_grid
        return False
