"""使用真实离线地图包执行五轮 v3.6 竞赛全链路技术彩排。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.config import settings
from app.database import Base
from app.agent_runtime.runtime import AgentRunExecutor
from app.agent_runtime.service import AgentRunService
from app.models.agent_run import AgentUsageRecord
from app.models.case import (
    Case,
    CaseEvidence,
    CasePerson,
    CaseTip,
    CaseVehicle,
    OilRecoveryRecord,
)
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis
from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
from app.models.chain_link import ChainLink
from app.models.conclusion import Conclusion
from app.models.deployment_advisor import DeploymentRecommendation
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature, OperationalArea
from app.models.patrol import PatrolRecord
from app.services.case_insight_service import CaseInsightService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_service import CaseService
from app.services.deployment_advisor_service import DeploymentAdvisorService
from app.services.offline_map_service import MAX_BUNDLE_BYTES, OfflineMapService
from app.services.outbox_claim_service import OutboxClaimLostError, OutboxClaimService


FAULT_SCENARIOS = (
    "none",
    "external_model_unavailable",
    "outbox_worker_suspended_then_recovered",
    "worker_restart_after_claim",
    "idempotent_replay",
)

SOURCE_FINGERPRINT_EXCLUDED_ROOTS = {
    ".git",
    ".playwright-cli",
    "backups",
    "docs",
    "node_modules",
    "output",
    "outputs",
    "venv",
}
SOURCE_FINGERPRINT_EXCLUDED_FILES = {"design-qa.md"}


def _event_for_case(db: Session, case_id: int, event_type: str) -> OutboxEvent:
    event = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.aggregate_id == str(case_id),
            OutboxEvent.event_type == event_type,
        )
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
        .first()
    )
    if event is None:
        raise RuntimeError(f"missing_outbox_event:{event_type}")
    return event


def _coverage(items: list[Any], predicate) -> float:
    if not items:
        return 0.0
    return round(sum(1 for item in items if predicate(item)) / len(items), 4)


FORMAL_CASE_CHILD_MODELS = (
    CasePerson,
    CaseVehicle,
    CaseEvidence,
    OilRecoveryRecord,
    CaseTip,
)
FORMAL_DOMAIN_MODELS = (Conclusion, ChainLink, JurisdictionAsset, PatrolRecord)


def _row_values(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _formal_case_values(db: Session, case: Case) -> dict[str, Any]:
    """冻结正式案件及其直接事实子表，避免分析过程产生任何隐式改写。"""
    children = {
        model.__tablename__: [
            _row_values(row)
            for row in db.query(model).filter(model.case_id == case.id).order_by(model.id).all()
        ]
        for model in FORMAL_CASE_CHILD_MODELS
    }
    return {"case": _row_values(case), "children": children}


def _formal_domain_values(db: Session, case: Case) -> dict[str, Any]:
    """冻结分析链路不得改写的正式事实、结论、链条、资产和执行表。"""
    return {
        "case": _formal_case_values(db, case),
        "domain_tables": {
            model.__tablename__: [
                _row_values(row)
                for row in db.query(model).order_by(model.id).all()
            ]
            for model in FORMAL_DOMAIN_MODELS
        },
    }


class _UnavailableNarrator:
    """竞赛故障演练专用叙述器：真实进入模型边界后确定性超时。"""

    provider_name = "fault_injection"
    model_name = "unavailable-model"
    input_cost_per_million_usd = 0.0
    output_cost_per_million_usd = 0.0

    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        del query, payload
        self.calls += 1
        raise TimeoutError("injected_external_model_timeout")


def _exercise_model_failure(db: Session, case: Case, asset_id: int) -> dict[str, Any]:
    narrator = _UnavailableNarrator()
    agent_run = AgentRunService.create_run(
        db,
        task_type="dual_domain_analysis",
        query="验证外部叙述模型不可用时保留确定性结果",
        case_ids=[case.id],
        asset_ids=[asset_id],
        mode="shadow",
        created_by=None,
    )
    completed = asyncio.run(
        AgentRunExecutor(narrator=narrator).execute(db, agent_run.id)
    )
    usage = db.query(AgentUsageRecord).filter(
        AgentUsageRecord.run_id == agent_run.id
    ).one()
    if completed.status != "degraded" or narrator.calls != 1 or usage.status != "failed":
        raise RuntimeError("external_model_failure_not_exercised")
    if completed.result_summary.get("mode") != "deterministic_fallback":
        raise RuntimeError("external_model_fallback_missing")
    return {
        "agent_run_status": completed.status,
        "external_model_attempts": narrator.calls,
        "usage_error_code": usage.error_code,
        "fallback_mode": completed.result_summary.get("mode"),
    }


def _new_worker_session(db: Session) -> Session:
    return sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)()


def _candidate_source_fingerprint(repository_root: Path) -> tuple[str, int]:
    """为未提交的集成候选生成可复算指纹，避免证据只指向旧 HEAD。"""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: set[Path] = set()
    for relative in listed.stdout.splitlines():
        relative_path = Path(relative)
        if not relative_path.parts:
            continue
        if relative_path.parts[0] in SOURCE_FINGERPRINT_EXCLUDED_ROOTS:
            continue
        if relative_path.as_posix() in SOURCE_FINGERPRINT_EXCLUDED_FILES:
            continue
        path = repository_root / relative_path
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        paths.add(path)
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(repository_root).as_posix()):
        relative = path.relative_to(repository_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(paths)


def run_rehearsal_rounds(
    db: Session,
    *,
    operational_area_id: int,
    map_snapshot_id: str,
    run_count: int = 5,
) -> dict[str, Any]:
    """在隔离数据库里走案件保存、画像、双域研判和部署参考完整链路。"""
    if run_count != 5:
        raise ValueError("competition_rehearsal_requires_five_runs")
    area = db.query(OperationalArea).filter(OperationalArea.id == operational_area_id).first()
    snapshot = db.query(MapSnapshot).filter(MapSnapshot.id == map_snapshot_id).first()
    if area is None or area.status != "active":
        raise ValueError("operational_area_not_found")
    if snapshot is None or snapshot.status != "current":
        raise ValueError("current_map_snapshot_required")
    if snapshot.operational_area_id != area.id:
        raise ValueError("map_snapshot_area_mismatch")

    anchor = (
        db.query(MapSnapshotFeature)
        .filter(
            MapSnapshotFeature.snapshot_id == snapshot.id,
            MapSnapshotFeature.asset_type.in_(("well", "production_target")),
            MapSnapshotFeature.latitude.isnot(None),
            MapSnapshotFeature.longitude.isnot(None),
        )
        .order_by(MapSnapshotFeature.id)
        .first()
    )
    if anchor is None:
        raise ValueError("synthetic_source_feature_required")

    runs: list[dict[str, Any]] = []
    rehearsal_started = datetime.now(timezone.utc)
    for sequence, scenario in enumerate(FAULT_SCENARIOS, start=1):
        started = time.perf_counter()
        case_time = datetime.now(timezone.utc)
        if db.get_bind().dialect.name == "sqlite":
            # SQLite 不保留时区；显式使用无时区 UTC 以模拟数据库回读行为。
            case_time = case_time.replace(tzinfo=None)
        case = CaseService.create_case(
            db=db,
            case_number=f"V36-DEMO-{rehearsal_started:%Y%m%d%H%M%S}-{sequence:02d}",
            occurred_time=case_time - timedelta(minutes=sequence),
            location="脱敏演示网格",
            latitude=float(anchor.latitude) + sequence * 0.0001,
            longitude=float(anchor.longitude) + sequence * 0.0001,
            case_type="涉油盗窃",
            description=(
                "脱敏演示案件：夜间发现生产设施油品异常，"
                "需结合地图和历史条件核查。"
            ),
            oil_type="原油",
            oil_volume=1.5,
            facility_type="井口",
            facility_owner="演示单位",
            modus_operandi="车辆转运",
            report_time=case_time,
            report_unit="演示值班组",
            source_type="人工录入",
            oil_nature="原油",
            current_stage="reported",
            operational_area_id=area.id,
        )
        db.expire_all()
        case = db.query(Case).filter(Case.id == case.id).one()
        profile_event = _event_for_case(db, case.id, "case.analysis.requested")
        saved_before_background = (
            db.query(Case.id).filter(Case.id == case.id).first() is not None
            and profile_event.status == "pending"
        )
        formal_source_hash = CasePipelineService.source_hash(db, case)
        formal_domain_snapshot = _formal_domain_values(db, case)
        fault_observation: dict[str, Any] = {}
        external_model_calls = 0

        if scenario == "outbox_worker_suspended_then_recovered":
            # 模拟 Outbox Worker 停止：案件和 pending 事件已提交，然后由独立
            # Worker 会话恢复轮询，验证录入事务不依赖队列存活。
            db.commit()
            fault_observation["pending_before_recovery"] = profile_event.status == "pending"
            worker_db = _new_worker_session(db)
            try:
                recovery = CasePipelineService.process_pending(worker_db, limit=10)
                recovered_event = worker_db.query(OutboxEvent).filter(
                    OutboxEvent.id == profile_event.id
                ).one()
                profile_result = {
                    "event_id": recovered_event.id,
                    "status": recovered_event.status,
                }
            finally:
                worker_db.close()
            fault_observation["recovery_poll"] = recovery
            fault_observation["independent_worker_session"] = True
            db.expire_all()
        elif scenario == "worker_restart_after_claim":
            # Worker A 领取后失效，Worker B 过租约接管；最后用 A 的旧令牌
            # 尝试完成，必须被提交围栏拒绝。
            first_worker = _new_worker_session(db)
            try:
                claimed_event, claimed = OutboxClaimService.claim(
                    first_worker,
                    profile_event.id,
                    expected_type="case.analysis.requested",
                )
                if not claimed:
                    raise RuntimeError("worker_restart_claim_failed")
                stale_worker_id = str(claimed_event.worker_id)
                claimed_event.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                first_worker.commit()
            finally:
                first_worker.close()
            replacement_worker = _new_worker_session(db)
            try:
                profile_result = CasePipelineService.process_event(
                    replacement_worker,
                    profile_event.id,
                )
            finally:
                replacement_worker.close()
            stale_worker = _new_worker_session(db)
            try:
                with_stale_claim_rejected = False
                try:
                    OutboxClaimService.finish(
                        stale_worker,
                        event_id=profile_event.id,
                        worker_id=stale_worker_id,
                        status="completed",
                    )
                except OutboxClaimLostError:
                    stale_worker.rollback()
                    with_stale_claim_rejected = True
                if not with_stale_claim_rejected:
                    raise RuntimeError("stale_worker_commit_not_fenced")
            finally:
                stale_worker.close()
            fault_observation.update(
                {
                    "expired_claim_recovered": True,
                    "replacement_worker_session": True,
                    "stale_finish_rejected": True,
                }
            )
            db.expire_all()
        else:
            profile_result = CasePipelineService.process_event(db, profile_event.id)
        profile = (
            db.query(CaseAnalysisProfile)
            .filter(
                CaseAnalysisProfile.case_id == case.id,
                CaseAnalysisProfile.is_current.is_(True),
            )
            .first()
        )
        if profile is None:
            raise RuntimeError(f"profile_not_generated:{profile_result}")
        if scenario == "external_model_unavailable":
            model_observation = _exercise_model_failure(db, case, int(anchor.asset_id))
            external_model_calls = int(model_observation["external_model_attempts"])
            fault_observation.update(model_observation)
        insight_event = _event_for_case(db, case.id, "case.insights.requested")
        insight_result = CaseInsightService.process_event(db, insight_event.id)
        analysis_run = (
            db.query(CaseAnalysisRun)
            .filter(
                CaseAnalysisRun.case_id == case.id,
                CaseAnalysisRun.case_profile_id == profile.id,
                CaseAnalysisRun.map_snapshot_id == snapshot.id,
            )
            .one()
        )
        hypotheses = (
            db.query(CaseHypothesis)
            .filter(
                CaseHypothesis.analysis_run_id == analysis_run.id,
                CaseHypothesis.status == "candidate",
            )
            .order_by(CaseHypothesis.rank)
            .all()
        )

        profile_replayed = False
        insight_replayed = False
        if scenario == "idempotent_replay":
            profile_replay = CasePipelineService.process_event(db, profile_event.id)
            insight_replay = CaseInsightService.process_event(db, insight_event.id)
            profile_replayed = bool(profile_replay.get("idempotent_replay"))
            insight_replayed = bool(insight_replay.get("idempotent_replay"))
            if db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == case.id).count() != 1:
                raise RuntimeError("profile_replay_created_duplicate")
            if db.query(CaseAnalysisRun).filter(CaseAnalysisRun.case_id == case.id).count() != 1:
                raise RuntimeError("insight_replay_created_duplicate")

        brief, brief_replay = DeploymentAdvisorService.generate_brief(
            db,
            operational_area_id=area.id,
            period_type="daily",
            as_of=datetime.now(timezone.utc) + timedelta(seconds=1),
        )
        recommendations = (
            db.query(DeploymentRecommendation)
            .filter(DeploymentRecommendation.brief_id == brief.id)
            .order_by(DeploymentRecommendation.rank)
            .all()
        )
        refreshed_case = db.query(Case).filter(Case.id == case.id).one()
        final_source_hash = CasePipelineService.source_hash(db, refreshed_case)
        final_domain_snapshot = _formal_domain_values(db, refreshed_case)
        completed_profile_event = db.query(OutboxEvent).filter(
            OutboxEvent.id == profile_event.id
        ).one()

        candidate_count = len(hypotheses)
        recommendation_count = len(recommendations)
        evidence_coverage = _coverage(hypotheses, lambda item: bool(item.evidence_refs))
        counter_coverage = _coverage(
            hypotheses,
            lambda item: bool(item.counter_evidence or item.information_gaps),
        )
        if not 1 <= candidate_count <= 3:
            raise RuntimeError("candidate_count_out_of_bounds")
        if evidence_coverage != 1.0 or counter_coverage != 1.0:
            raise RuntimeError("candidate_evidence_incomplete")
        if not 1 <= recommendation_count <= 3:
            raise RuntimeError("recommendation_count_out_of_bounds")
        if any(not item.evidence_refs for item in recommendations):
            raise RuntimeError("recommendation_evidence_incomplete")
        if any(item.auto_execution_allowed for item in recommendations):
            raise RuntimeError("recommendation_execution_enabled")
        formal_domain_changed = (
            formal_source_hash != final_source_hash
            or formal_domain_snapshot != final_domain_snapshot
        )
        execution_task_created = (
            formal_domain_snapshot["domain_tables"][PatrolRecord.__tablename__]
            != final_domain_snapshot["domain_tables"][PatrolRecord.__tablename__]
        )
        if execution_task_created:
            raise RuntimeError("execution_task_created")
        if formal_domain_changed:
            raise RuntimeError("formal_domain_changed")
        if scenario == "idempotent_replay" and not (profile_replayed and insight_replayed):
            raise RuntimeError("idempotent_replay_not_confirmed")

        runs.append(
            {
                "sequence": sequence,
                "case_alias": f"CASE-{sequence:02d}",
                "fault_scenario": scenario,
                "case_saved_before_background_processing": saved_before_background,
                "profile_event_id": profile_event.id,
                "profile_event_attempts": completed_profile_event.attempts,
                "profile_status": profile_result["status"],
                "profile_id": profile.id,
                "analysis_event_id": insight_event.id,
                "analysis_run_id": analysis_run.id,
                "analysis_status": insight_result["status"],
                "candidate_count": candidate_count,
                "evidence_coverage": evidence_coverage,
                "counter_evidence_or_gap_coverage": counter_coverage,
                "brief_id": brief.id,
                "brief_replay": brief_replay,
                "recommendation_count": recommendation_count,
                "formal_case_changed": formal_domain_changed,
                "formal_domain_changed": formal_domain_changed,
                "execution_task_created": execution_task_created,
                "external_model_calls": external_model_calls,
                "fault_observation": fault_observation,
                "profile_idempotent_replay": profile_replayed,
                "insight_idempotent_replay": insight_replayed,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        )

    return {
        "status": "passed",
        "workflow": "case_save_to_profile_to_dual_domain_to_deployment_reference",
        "run_count": run_count,
        "successful_runs": len(runs),
        "started_at": rehearsal_started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "operational_area_alias": "COMPETITION-DEMO-AREA",
        "map_snapshot_version": snapshot.version,
        "deterministic_rules": True,
        "external_model_required": False,
        "redis_required_for_case_save": False,
        "runs": runs,
    }


def verify(bundle_path: Path, *, run_count: int = 5) -> dict[str, Any]:
    """用真实地图包建立一次性数据库，执行彩排后自动删除全部演示数据。"""
    repository_root = Path(__file__).resolve().parents[3]
    source_fingerprint_before, source_file_count_before = (
        _candidate_source_fingerprint(repository_root)
    )
    resolved_bundle = bundle_path.resolve(strict=True)
    if resolved_bundle.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("bundle_too_large")
    content = resolved_bundle.read_bytes()
    package_hash = hashlib.sha256(content).hexdigest()
    previous_map_root = settings.MAP_PACKAGE_ROOT
    previous_vector = settings.ENABLE_VECTOR_DB
    previous_external_model = settings.AGENT_USE_EXTERNAL_MODEL
    with tempfile.TemporaryDirectory(prefix="aicommander-v36-competition-") as temporary:
        work_dir = Path(temporary)
        engine = None
        db = None
        try:
            settings.MAP_PACKAGE_ROOT = str(work_dir / "map-packages")
            settings.ENABLE_VECTOR_DB = False
            settings.AGENT_USE_EXTERNAL_MODEL = False
            engine = create_engine(f"sqlite:///{work_dir / 'competition.db'}")
            Base.metadata.create_all(bind=engine)
            LocalSession = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
            )
            db = LocalSession()
            bundle, replay = OfflineMapService.import_bundle(
                db,
                filename=resolved_bundle.name,
                content=content,
                imported_by=None,
            )
            if replay:
                raise RuntimeError("isolated_competition_database_not_empty")
            west, south, east, north = (float(item) for item in bundle.bounds)
            center_lat = (south + north) / 2
            center_lon = (west + east) / 2
            area = OperationalArea(
                code=f"competition-demo-{uuid.uuid4().hex[:10]}",
                name="v3.6竞赛脱敏演示区",
                boundary={
                    "type": "Polygon",
                    "coordinates": [[
                        [center_lon - 0.05, center_lat - 0.05],
                        [center_lon + 0.05, center_lat - 0.05],
                        [center_lon + 0.05, center_lat + 0.05],
                        [center_lon - 0.05, center_lat + 0.05],
                        [center_lon - 0.05, center_lat - 0.05],
                    ]],
                },
                is_default=True,
                status="active",
            )
            db.add(area)
            db.flush()
            assets = (
                (
                    "脱敏生产目标A",
                    "well",
                    0.0,
                    0.0,
                    {"oil_type": "原油", "production_output": 95},
                ),
                (
                    "脱敏生产目标B",
                    "well",
                    0.006,
                    0.005,
                    {"oil_type": "原油", "production_output": 80},
                ),
                ("脱敏临时存储区C", "storage", 0.009, 0.008, {}),
                ("脱敏生产便道D", "road", 0.003, 0.002, {}),
            )
            for index, item in enumerate(assets, start=1):
                name, asset_type, lat_delta, lon_delta, attributes = item
                db.add(
                    JurisdictionAsset(
                        operational_area_id=area.id,
                        canonical_key=f"competition:{area.code}:{index}",
                        name=name,
                        asset_type=asset_type,
                        geometry_type="point",
                        latitude=center_lat + lat_delta,
                        longitude=center_lon + lon_delta,
                        source="synthetic_demo",
                        status="active",
                        verified=True,
                        verification_state="source_verified",
                        coordinate_system="EPSG:4326",
                        attributes=attributes,
                    )
                )
            db.commit()
            snapshot, snapshot_replay = OfflineMapService.build_snapshot(
                db,
                operational_area_id=area.id,
                public_bundle_id=bundle.id,
                built_by=None,
            )
            if snapshot_replay:
                raise RuntimeError("isolated_snapshot_replayed")
            OfflineMapService.publish_snapshot(db, snapshot.id)
            result = run_rehearsal_rounds(
                db,
                operational_area_id=area.id,
                map_snapshot_id=snapshot.id,
                run_count=run_count,
            )
            result["map_package"] = {
                "filename": resolved_bundle.name,
                "sha256": package_hash,
                "source_version": bundle.source_version,
                "provider": bundle.provider,
                "tile_count": int(bundle.manifest.get("tile_count") or 0),
                "min_zoom": bundle.manifest.get("min_zoom"),
                "max_zoom": bundle.manifest.get("max_zoom"),
            }
            result["isolated_database_deleted_after_run"] = True
            result["candidate_version"] = "v3.6-integration-candidate"
            result["formal_version_before_release"] = (
                repository_root / "VERSION"
            ).read_text(encoding="utf-8").strip()
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            result["base_revision"] = revision.stdout.strip() or "unknown"
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            result["worktree_dirty"] = bool(dirty.stdout.strip())
            source_fingerprint_after, source_file_count_after = _candidate_source_fingerprint(
                repository_root
            )
            if (
                source_fingerprint_after != source_fingerprint_before
                or source_file_count_after != source_file_count_before
            ):
                raise RuntimeError("candidate_source_changed_during_rehearsal")
            result["candidate_source_sha256"] = source_fingerprint_after
            result["candidate_source_file_count"] = source_file_count_after
            result["candidate_source_stable_during_rehearsal"] = True
            return result
        finally:
            if db is not None:
                db.close()
            if engine is not None:
                engine.dispose()
            settings.MAP_PACKAGE_ROOT = previous_map_root
            settings.ENABLE_VECTOR_DB = previous_vector
            settings.AGENT_USE_EXTERNAL_MODEL = previous_external_model


def _write_evidence_atomically(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("evidence_file_exists")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            os.fchmod(temporary.fileno(), 0o600)
            json.dump(result, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError as exc:
            raise ValueError("evidence_file_exists") from exc
        Path(temporary_name).unlink()
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用真实离线地图包执行五轮 v3.6 自动业务链路竞赛彩排。"
    )
    parser.add_argument(
        "--bundle",
        required=True,
        type=Path,
        help="已经深度验包的公共离线地图 ZIP",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        type=Path,
        help="输出不含业务原文的 JSON 证据",
    )
    parser.add_argument("--runs", type=int, default=5, help="固定为5轮")
    args = parser.parse_args()
    result = verify(args.bundle, run_count=args.runs)
    _write_evidence_atomically(args.evidence, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
