"""v3.6 统一版本、评测、追溯与部署方案对比 API。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.governance import EvaluationDataset, EvaluationRun, SpatialCoverageComparison
from app.models.map_foundation import OperationalArea
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.services.governance_service import GovernanceService
from app.services.spatial_coverage_service import compare_coverage, read_comparison, save_comparison
from app.services import coverage_road_jobs
from app.services import frozen_evaluation_service
from app.services import road_evaluation_jobs
from app.services import frozen_road_dataset
from app.services.evaluation_diagnostics import describe_run
from app.services.score_calibration import calibrate
from app.services.road_access_policy import VehicleAssumption


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


class FrozenCaseInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: int = Field(ge=1, strict=True)
    profile_id: str = Field(min_length=1, max_length=36)
    snapshot_id: str = Field(min_length=1, max_length=36)


class FrozenDatasetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    inputs: list[FrozenCaseInput] = Field(min_length=1, max_length=100)
    ground_truth: dict[int, list[GroundTruthLabel]] = Field(default_factory=dict)
    negative_case_ids: list[StrictInt] = Field(default_factory=list, max_length=100)


class FixedRunRequest(EvaluationRunRequest):
    scorer_policy: Literal['captured', 'current_candidate'] = 'captured'


class LabelRevisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)
    ground_truth: dict[int, list[GroundTruthLabel]]
    negative_case_ids: list[StrictInt] = Field(max_length=100)


class FixedComparisonRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baseline_run_id: str = Field(min_length=1, max_length=36)
    candidate_run_id: str = Field(min_length=1, max_length=36)


class RoadEvaluationRequest(EvaluationRunRequest):
    request_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')


class RoadDatasetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    artifact_ids: list[str] = Field(min_length=1, max_length=10)


class ResultArchiveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    result_id: str = Field(min_length=1, max_length=36)
    expected_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)


class DeploymentScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    coverage_factor: float = Field(default=1, ge=0, le=1)
    availability_factor: float = Field(default=1, ge=0, le=1)


class DeploymentSandboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_ids: list[str] = Field(min_length=1, max_length=20)
    scenarios: list[DeploymentScenario] = Field(min_length=1, max_length=5)


class CoverageMovement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    resource_id: int = Field(ge=1, strict=True)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SpatialCoverageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operational_area_id: int | None = Field(default=None, ge=1)
    disabled_resource_ids: list[StrictInt] = Field(default_factory=list, max_length=200)
    movements: list[CoverageMovement] = Field(default_factory=list, max_length=200)


class CoverageReferenceVehicle(VehicleAssumption):
    source: Literal['explicit_reference_assumption'] = 'explicit_reference_assumption'


class CoverageRoadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    vehicle: CoverageReferenceVehicle
    distance_budget_m: float = Field(gt=0, le=50000)


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


@router.post('/admin/evaluations/fixed-datasets', status_code=201)
def create_fixed_dataset(payload: FrozenDatasetRequest, request: Request, db: Session = Depends(get_db)):
    principal = _require_admin(request)
    try:
        dataset = frozen_evaluation_service.create_dataset(db, name=payload.name, version=payload.version,
            inputs=[item.model_dump() for item in payload.inputs],
            ground_truth={str(key): [label.model_dump() for label in labels] for key, labels in payload.ground_truth.items()},
            negative_case_ids=payload.negative_case_ids, created_by=_user_id(principal))
        return {'id': dataset.id, 'name': dataset.name, 'version': dataset.version,
                'classification': dataset.classification, 'checksum': dataset.checksum,
                'case_count': len(dataset.case_ids), 'frozen_input_exported': False}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='评测来源不存在或不在当前权限范围') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='评测输入、标签或版本冲突，请核对后重试') from exc


@router.post('/admin/evaluations/fixed-run', status_code=201)
def run_fixed_evaluation(payload: FixedRunRequest, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return _run_dict(frozen_evaluation_service.run_evaluation(db, payload.dataset_id, scorer_policy=payload.scorer_policy))
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='当前无权访问完整评测来源') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='固定评测集不存在或完整性校验失败') from exc


@router.post('/admin/evaluations/result-archives', status_code=201)
def archive_result_evaluation(payload: ResultArchiveRequest, request: Request, db: Session = Depends(get_db)):
    principal = _require_admin(request)
    try:
        dataset = frozen_evaluation_service.create_from_result(db, **payload.model_dump(), created_by=_user_id(principal))
        return {'id': dataset.id, 'name': dataset.name, 'version': dataset.version,
                'sample_count': len(dataset.manifest['entries']), 'frozen_input_exported': False}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='成果不存在或当前无权访问') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='成果已更新、缺少地图版本或归档版本冲突，请刷新后重试') from exc


@router.post('/admin/evaluations/fixed-compare')
def compare_fixed_evaluations(payload: FixedComparisonRequest, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return frozen_evaluation_service.compare_runs(db, payload.baseline_run_id, payload.candidate_run_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='当前无权访问完整评测来源') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='评测记录校验失败，或输入及标签不同，不能比较') from exc


@router.get('/admin/evaluations/runs/{run_id}/diagnostics')
def get_evaluation_diagnostics(run_id: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return describe_run(frozen_evaluation_service.read_run(db, run_id))
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='当前无权访问评测来源') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='固定评分评测不存在或结果校验失败') from exc


@router.get('/admin/evaluations/runs/{run_id}/calibration')
def get_score_calibration(run_id: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return calibrate(frozen_evaluation_service.read_run(db, run_id))
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='当前无权访问校准来源') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='固定评分评测不存在或校验失败') from exc


@router.get('/admin/evaluations/fixed-datasets/{dataset_id}/labels')
def get_fixed_labels(dataset_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        dataset = frozen_evaluation_service.read_dataset(db, dataset_id)
        cases = db.query(Case).filter(Case.id.in_(dataset.case_ids)).all()
        asset_ids = {value for labels in dataset.ground_truth.values() for label in labels for value in label['expected_asset_ids']}
        assets = db.query(JurisdictionAsset).filter(JurisdictionAsset.id.in_(asset_ids)).all()
        return {'dataset_id': dataset.id, 'name': dataset.name, 'version': dataset.version,
            'case_ids': dataset.case_ids, 'ground_truth': dataset.ground_truth,
            'cases': [{'id': row.id, 'case_number': row.case_number} for row in cases],
            'label_assets': [{'id': row.id, 'name': row.name} for row in assets],
            'negative_case_ids': dataset.manifest['negative_case_ids'], 'checksum': dataset.checksum,
            'boundary': '标签只用于离线评测，不修改案件事实；未标注不等于无候选。'}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='评测来源当前不可访问') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='固定评测集不存在或校验失败') from exc


@router.get('/admin/evaluations/fixed-datasets/{dataset_id}/label-assets')
def search_label_assets(dataset_id: int, request: Request, case_id: int = Query(ge=1),
                         q: str = Query(default='', max_length=100), db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        dataset = frozen_evaluation_service.read_dataset(db, dataset_id)
        if case_id not in dataset.case_ids:
            raise PermissionError('case_not_in_dataset')
        case = db.query(Case).filter_by(id=case_id).one()
        query = db.query(JurisdictionAsset).filter(JurisdictionAsset.operational_area_id == case.operational_area_id)
        if q.strip():
            query = query.filter(JurisdictionAsset.name.contains(q.strip(), autoescape=True))
        rows = query.order_by(JurisdictionAsset.name, JurisdictionAsset.id).limit(31).all()
        return {'items': [{'id': row.id, 'name': row.name, 'asset_type': row.asset_type} for row in rows[:30]],
                'has_more': len(rows) > 30}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='评测来源或样本不可访问') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='固定评测集校验失败') from exc


@router.post('/admin/evaluations/fixed-datasets/{dataset_id}/label-versions', status_code=201)
def revise_fixed_labels(dataset_id: int, payload: LabelRevisionRequest, request: Request, db: Session = Depends(get_db)):
    principal = _require_admin(request)
    try:
        dataset = frozen_evaluation_service.revise_labels(db, dataset_id,
            version=payload.version, reason=payload.reason, created_by=_user_id(principal),
            ground_truth={str(key): [label.model_dump() for label in labels] for key, labels in payload.ground_truth.items()},
            negative_case_ids=payload.negative_case_ids)
        return {'id': dataset.id, 'name': dataset.name, 'version': dataset.version, 'checksum': dataset.checksum,
                'frozen_input_exported': False}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='评测来源或标注对象当前不可访问') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='标签冲突、对象不在样本中或版本已被占用') from exc


@router.post('/admin/evaluations/road-jobs', status_code=202)
def create_road_evaluation(payload: RoadEvaluationRequest, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        result = road_evaluation_jobs.enqueue(db, payload.dataset_id, request_id=payload.request_id)
        db.commit()
        return result
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail='道路评测来源不可用或无权访问') from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='道路评测输入或请求编号冲突') from exc


@router.post('/admin/evaluations/road-datasets', status_code=201)
def create_road_dataset(payload: RoadDatasetRequest, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        # Freeze database references now; large graph hashing runs only in the worker.
        dataset = frozen_road_dataset.create_dataset(db, name=payload.name, version=payload.version,
            artifact_ids=payload.artifact_ids, artifact_root=Path(settings.MAP_PACKAGE_ROOT) / 'road-graphs',
            verify_files=False)
        db.commit()
        return {'id': dataset.id, 'name': dataset.name, 'version': dataset.version, 'checksum': dataset.checksum,
            'sample_count': len(dataset.manifest['entries']), 'classification': 'internal_sensitive',
            'frozen_input_exported': False, 'graph_verification': 'deferred_to_worker'}
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail='道路评测来源不可用或无权访问') from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='道路评测输入或版本冲突') from exc


@router.get('/admin/evaluations/road-jobs')
def list_road_evaluations(request: Request, page: int = Query(default=1, ge=1, le=100000),
                          page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return road_evaluation_jobs.list_jobs(db, page=page, page_size=page_size)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='道路任务目录不可访问') from exc


@router.get('/admin/evaluations/road-jobs/{event_id}')
def get_road_evaluation(event_id: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return road_evaluation_jobs.read_run(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='道路评测不存在或当前无权访问') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='道路评测来源或结果校验失败') from exc


@router.post('/admin/evaluations/road-jobs/{event_id}/cancel')
def cancel_road_evaluation(event_id: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    try:
        return road_evaluation_jobs.cancel(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='道路评测不存在或无权取消') from exc


def _evaluation_visible(db, run):
    if run.algorithm_manifest.get('evaluation_schema') == road_evaluation_jobs.SCHEMA:
        try:
            road_evaluation_jobs.read_run(db, run.id)
            return True
        except (PermissionError, ValueError):
            return False
    if run.algorithm_manifest.get('evaluation_schema') != frozen_evaluation_service.SCHEMA:
        return True
    try:
        frozen_evaluation_service.read_run(db, run.id)
        return True
    except (PermissionError, ValueError):
        return False


@router.get("/admin/evaluations/runs")
def list_evaluation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
    runs = db.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(limit).all()
    return [_run_dict(item) for item in runs if _evaluation_visible(db, item)]


@router.get('/admin/evaluations/fixed-datasets')
def list_fixed_datasets(request: Request, before_id: int | None = Query(default=None, ge=1),
                        db: Session = Depends(get_db)):
    _require_admin(request)
    query = db.query(EvaluationDataset).filter(EvaluationDataset.manifest['schema'].as_string().in_(
        (frozen_evaluation_service.SCHEMA, frozen_road_dataset.SCHEMA)))
    if before_id is not None:
        query = query.filter(EvaluationDataset.id < before_id)
    rows = query.order_by(EvaluationDataset.id.desc()).limit(51).all()
    items = []
    for row in rows[:50]:
        try:
            road = row.manifest.get('schema') == frozen_road_dataset.SCHEMA
            (frozen_road_dataset.read_dataset if road else frozen_evaluation_service.read_dataset)(db, row.id)
            items.append({'id': row.id, 'name': row.name, 'version': row.version,
                'kind': 'road' if road else 'case', 'checksum': row.checksum,
                'sample_count': len(row.manifest['entries']), 'created_at': row.created_at})
        except (PermissionError, ValueError):
            continue
    return {'items': items, 'next_before_id': rows[49].id if len(rows) > 50 else None,
            'frozen_input_exported': False}


@router.get("/admin/intelligence-runtime/overview")
def intelligence_runtime_overview(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    versions = GovernanceService.ensure_versions(db)
    latest_evaluation = db.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).first()
    if latest_evaluation is not None and not _evaluation_visible(db, latest_evaluation):
        latest_evaluation = None
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


@router.post("/deployment-sandbox/compare", deprecated=True,
             summary="历史系数模拟（不是空间覆盖计算）")
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


@router.post("/deployment-sandbox/spatial-compare")
def compare_spatial_coverage(
    payload: SpatialCoverageRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _principal(request)
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role not in {"admin", "analyst"}:
        raise HTTPException(status_code=403, detail="只读账号不能运行方案比较")
    if "authorized_area_ids" not in db.info:
        raise HTTPException(status_code=403, detail="未建立数据访问范围")
    allowed = db.info["authorized_area_ids"]
    area_id = payload.operational_area_id or db.info.get("default_operational_area_id")
    areas = db.query(OperationalArea).filter(OperationalArea.status == "active")
    if allowed is not None:
        areas = areas.filter(OperationalArea.id.in_(allowed))
    if area_id is not None:
        areas = areas.filter(OperationalArea.id == area_id)
    area = areas.order_by(OperationalArea.id).first()
    if area is None:
        raise HTTPException(status_code=404, detail="辖区不存在或无权访问")
    if len({item.resource_id for item in payload.movements}) != len(payload.movements):
        raise HTTPException(status_code=422, detail="同一资源不能重复设置方案位置")
    try:
        result = compare_coverage(db, area.id, as_of=datetime.now(timezone.utc),
            disabled_resource_ids=tuple(payload.disabled_resource_ids),
            movements={item.resource_id: (item.latitude, item.longitude) for item in payload.movements})
        return save_comparison(db, result, created_by=_user_id(principal))
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="资源不存在或无权访问") from exc
    except ValueError as exc:
        if str(exc) == "coverage_background_batch_required":
            raise HTTPException(status_code=422, detail="超出交互计算规模，尚需后台分批计算；未返回截断结果") from exc
        raise HTTPException(status_code=422, detail="方案位置或时间条件不正确") from exc


@router.get('/deployment-sandbox/spatial-comparisons')
def list_spatial_comparisons(request: Request, page: int = Query(1, ge=1, le=100000),
                             page_size: int = Query(20, ge=1, le=100),
                             db: Session = Depends(get_db)) -> dict[str, Any]:
    _principal(request)
    if 'authorized_area_ids' not in db.info:
        raise HTTPException(status_code=403, detail='未建立数据访问范围')
    allowed = db.info['authorized_area_ids']
    query = db.query(SpatialCoverageComparison).join(OperationalArea,
        OperationalArea.id == SpatialCoverageComparison.operational_area_id).filter(OperationalArea.status == 'active')
    if allowed is not None:
        query = query.filter(SpatialCoverageComparison.operational_area_id.in_(allowed))
    total = query.count()
    rows = query.with_entities(SpatialCoverageComparison.id, SpatialCoverageComparison.operational_area_id,
        SpatialCoverageComparison.created_at).order_by(SpatialCoverageComparison.created_at.desc(),
        SpatialCoverageComparison.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [{'id': row.id, 'operational_area_id': row.operational_area_id, 'created_at': row.created_at}
                      for row in rows], 'total': total, 'page': page, 'page_size': page_size,
            'boundary': '只列授权辖区的成果目录；打开时重新核对来源权限，目录不含覆盖结果。'}


@router.get("/deployment-sandbox/spatial-comparisons/{comparison_id}")
def get_spatial_comparison(
    comparison_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _principal(request)
    try:
        return read_comparison(db, comparison_id, now=datetime.now(timezone.utc))
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="方案不存在或当前无权读取其来源") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="历史方案校验失败，请重新计算") from exc


@router.post('/deployment-sandbox/spatial-comparisons/{comparison_id}/road-jobs', status_code=202)
def start_coverage_road_job(comparison_id: str, payload: CoverageRoadRequest, request: Request,
                           db: Session = Depends(get_db)) -> dict[str, Any]:
    _principal(request)
    try:
        result = coverage_road_jobs.enqueue(db, comparison_id, at=datetime.now(timezone.utc),
            vehicle=payload.vehicle, distance_budget_m=payload.distance_budget_m)
        db.commit()
        return {**result, 'execution_task_created': False, 'poll_after_seconds': 5}
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail='方案或适用路网不存在，或当前无权使用') from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail='方案来源或条件已变化，请重新计算覆盖方案') from exc


@router.get('/deployment-sandbox/road-jobs/{event_id}')
def get_coverage_road_job(event_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _principal(request)
    try:
        return coverage_road_jobs.read_job(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='道路方案不存在或当前无权读取') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='道路方案来源、条件或校验已失效，请重新计算') from exc


@router.get('/deployment-sandbox/spatial-comparisons/{comparison_id}/road-jobs')
def list_coverage_road_jobs(comparison_id: str, request: Request, page: int = Query(1, ge=1, le=100000),
                          page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> dict[str, Any]:
    _principal(request)
    try:
        return coverage_road_jobs.list_jobs(db, comparison_id, page=page, page_size=page_size)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='方案不存在或当前无权查看任务目录') from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail='方案来源校验失败') from exc


@router.post('/deployment-sandbox/road-jobs/{event_id}/cancel')
def cancel_coverage_road_job(event_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    _principal(request)
    try:
        return coverage_road_jobs.cancel_job(db, event_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail='任务不存在或无权取消') from exc


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
