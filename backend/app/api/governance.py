"""v3.6 统一版本、评测、追溯与部署方案对比 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.governance import EvaluationDataset, EvaluationRun
from app.services.governance_service import GovernanceService


router = APIRouter()


class GroundTruthLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    hypothesis_type: str = Field(
        pattern="^(possible_source|storage_area|activity_area|transfer_route)$"
    )
    expected_asset_ids: list[int] = Field(default_factory=list, max_length=20)
    expected_region_grid: str | None = Field(default=None, max_length=32)


class EvaluationDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    classification: str = Field(default="redacted", pattern="^redacted$")
    case_ids: list[int] = Field(min_length=1, max_length=5000)
    ground_truth: dict[int, list[GroundTruthLabel]] = Field(default_factory=dict)


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)


class DeploymentScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    coverage_factor: float = Field(default=1, ge=0, le=1)
    availability_factor: float = Field(default=1, ge=0, le=1)


class DeploymentSandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_ids: list[str] = Field(min_length=1, max_length=20)
    scenarios: list[DeploymentScenario] = Field(min_length=1, max_length=5)


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _require_admin(request: Request):
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以维护评测与运行版本")
    return principal


def _user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


@router.post("/admin/evaluations/datasets", status_code=201)
def create_evaluation_dataset(
    payload: EvaluationDatasetRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_admin(request)
    try:
        dataset = GovernanceService.create_dataset(
            db,
            name=payload.name,
            version=payload.version,
            case_ids=payload.case_ids,
            classification=payload.classification,
            ground_truth={
                str(case_id): [label.model_dump() for label in labels]
                for case_id, labels in payload.ground_truth.items()
            },
            created_by=_user_id(principal),
        )
    except ValueError as exc:
        code = str(exc)
        if code == "dataset_version_conflict":
            raise HTTPException(status_code=409, detail="同名评测集版本已存在且内容不同") from exc
        raise HTTPException(status_code=422, detail="评测集只能包含当前权限内的脱敏案件") from exc
    return _dataset_dict(dataset)


@router.post("/admin/evaluations/run", status_code=201)
def run_evaluation(
    payload: EvaluationRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        run = GovernanceService.run_evaluation(db, dataset_id=payload.dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc
    return _run_dict(run)


@router.get("/admin/evaluations/runs")
def list_evaluation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
    runs = db.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(limit).all()
    return [_run_dict(item) for item in runs]


@router.get("/admin/intelligence-runtime/overview")
def intelligence_runtime_overview(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    versions = GovernanceService.ensure_versions(db)
    latest_evaluation = db.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).first()
    return {
        "orchestrator": "deterministic-event-orchestrator",
        "business_agents": [
            "geographic-foundation",
            "case-governance",
            "dual-domain-insight",
            "deployment-advisor",
        ],
        "versions": versions,
        "latest_evaluation": _run_dict(latest_evaluation) if latest_evaluation else None,
        "formal_case_mutations_allowed": False,
        "execution_task_creation_allowed": False,
        "external_model_required": False,
    }


@router.get("/cases/{case_id}/analysis-lineage")
def case_analysis_lineage(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    try:
        return GovernanceService.case_lineage(db, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="案件不存在或无权访问") from exc


@router.post("/deployment-sandbox/compare")
def compare_deployment_scenarios(
    payload: DeploymentSandboxRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="只读账号不能运行部署方案对比")
    try:
        return GovernanceService.compare_deployment_scenarios(
            db,
            recommendation_ids=payload.recommendation_ids,
            scenarios=[item.model_dump() for item in payload.scenarios],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="部署建议不存在或无权访问") from exc


def _dataset_dict(dataset: EvaluationDataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "classification": dataset.classification,
        "manifest": dataset.manifest,
        "checksum": dataset.checksum,
        "created_at": dataset.created_at,
    }


def _run_dict(run: EvaluationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "status": run.status,
        "algorithm_manifest": run.algorithm_manifest,
        "scope_policy_version": run.scope_policy_version,
        "metrics": run.metrics,
        "trace_manifest": run.trace_manifest,
        "failure_reason": run.failure_reason,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }
