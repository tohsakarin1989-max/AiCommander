"""Bounded, authenticated reference calculations over published road graphs."""
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from threading import BoundedSemaphore, Event
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import get_db, bind_principal_scope
from app.services import road_calculation_service as calculations
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_contracts import RoadNetworkUnavailable
from app.services.vehicle_router import RoadCalculationError, RoadLocation

router = APIRouter()
# Per API process; deployment worker count must also be bounded. This is not a
# distributed queue or a claim that global admission control is implemented.
_slots = BoundedSemaphore(2)


class ReferenceVehicle(VehicleAssumption):
    # Client-supplied dimensions are assumptions, not verified case facts.
    source: Literal['explicit_reference_assumption'] = 'explicit_reference_assumption'


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    vehicle: ReferenceVehicle


class ServerCaseCalculation(BaseModel):
    """Internal only: vehicle provenance comes from an authorized frozen result."""
    analysis_at: AwareDatetime
    vehicle: VehicleAssumption


def _case_calculation(db, result_id, at):
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_vehicle import frozen_road_vehicle
    try:
        source = CaseResultService.read(db, result_id)
        vehicle = frozen_road_vehicle(source['content'])
    except PermissionError:
        raise HTTPException(404, '成果不存在或当前不可访问', headers={'Cache-Control': 'no-store'}) from None
    except ValueError:
        raise HTTPException(409, '成果引用校验未通过，请重新查询', headers={'Cache-Control': 'no-store'}) from None
    except SQLAlchemyError:
        raise HTTPException(503, '成果暂时无法读取', headers={'Cache-Control': 'no-store'}) from None
    if vehicle is None:
        raise HTTPException(422, '车辆类型或通行参数不足，未按小客车替代计算', headers={'Cache-Control': 'no-store'})
    return ServerCaseCalculation(analysis_at=at, vehicle=vehicle)


class RouteRequest(CalculationRequest):
    start: RoadLocation
    end: RoadLocation


class MatrixRequest(CalculationRequest):
    sources: list[RoadLocation] = Field(min_length=1, max_length=10)
    targets: list[RoadLocation] = Field(min_length=1, max_length=10)


class DistanceReachabilityRequest(CalculationRequest):
    metric: Literal['distance']
    origin: RoadLocation
    distance_m: float = Field(gt=0, le=50000, strict=True, allow_inf_nan=False)


class TimeReachabilityRequest(CalculationRequest):
    metric: Literal['time']
    origin: RoadLocation
    seconds: float = Field(gt=0, le=7200, strict=True, allow_inf_nan=False)


ReachabilityRequest = Annotated[DistanceReachabilityRequest | TimeReachabilityRequest, Field(discriminator='metric')]


class ResultRouteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_at: AwareDatetime
    network_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    graph_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResultDistanceBudget(ResultRouteRequest):
    metric: Literal['distance']
    distance_m: float = Field(gt=0, le=50000, strict=True, allow_inf_nan=False)


class ResultTimeBudget(ResultRouteRequest):
    metric: Literal['time']
    seconds: float = Field(gt=0, le=7200, strict=True, allow_inf_nan=False)


ResultReachabilityRequest = Annotated[ResultDistanceBudget | ResultTimeBudget, Field(discriminator='metric')]


def read_session(request: Request, db: Session = Depends(get_db)):
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录', headers={'Cache-Control': 'no-store'})
    if principal.role not in ('admin', 'analyst'):
        raise HTTPException(403, '缺少研判权限', headers={'Cache-Control': 'no-store'})
    # These POSTs calculate read-only results. Do not require source-editing
    # permission just because complex query parameters use a JSON body.
    bind_principal_scope(db, principal, method='GET')
    return db


def _failure(status, code, message):
    return JSONResponse(status_code=status, content={'detail': {'code': code, 'message': message}},
                        headers={'Cache-Control': 'no-store'})


def _is_preview_admin(db):
    return _current_analysis_role(db) == 'admin'


def _current_analysis_role(db):
    from sqlalchemy import select
    from app.models.user import User
    role = db.execute(select(User.role).where(User.id == db.info['principal_user_id'],
                                             User.is_active.is_(True))).scalar_one_or_none()
    return role


def reachability_session(request: Request, db: Session = Depends(read_session)):
    # Incomplete expansion is an administrator validation capability, not a
    # generally available analytical conclusion. Recheck the current DB role.
    if request.state.principal.role != 'admin' or not _is_preview_admin(db):
        raise HTTPException(403, '可达范围验收接口仅限管理员', headers={'Cache-Control': 'no-store'})
    return db


def _retain_case_calculation(db, result, cancel_event):
    if result.get('schema_version') not in ('case-road-comparison-4.2.0-1', 'case-road-route-4.2.0-1'):
        return result
    if not isinstance(result.get('matrix', result.get('route')), dict):
        return result  # An information-gap response is not a successful road calculation.
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_artifact_requires_clean_session')
    from app.services.case_road_artifact_service import freeze_road_artifact
    try:
        saved = freeze_road_artifact(db, result)
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result, 'artifact': saved}


def _calculate(function, db, payload, *, cancel_event=None, **points):
    if not _slots.acquire(blocking=False):
        return JSONResponse(status_code=429, content={'detail': {'code': 'road_calculation_busy',
            'message': '道路计算繁忙，请稍后重试'}}, headers={'Cache-Control': 'no-store', 'Retry-After': '5'})
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        result = function(db, analysis_at=payload.analysis_at, vehicle=payload.vehicle,
            artifact_root=Path(settings.MAP_PACKAGE_ROOT) / 'road-graphs', cancel_event=cancel_event, **points)
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        result = _retain_case_calculation(db, result, cancel_event)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except RoadNetworkUnavailable as error:
        if error.code == 'road_network_unavailable':
            return _failure(403, 'road_network_unavailable', '没有可访问的路网，请核对通行授权')
        return _failure(503, 'road_network_not_available', '所需路网尚不可用或来源已变化，请联系管理员')
    except RoadCalculationError as error:
        code = str(error)
        if code == 'road_calculation_cancelled':
            return _failure(409, code, '道路计算已取消，未生成结果')
        if code == 'road_vehicle_dimensions_missing':
            return _failure(422, code, '货车计算需要明确的参考高度和总重')
        if code in ('road_location_connection_unverified', 'road_route_connection_unverified'):
            return _failure(422, code, '位置与道路的连接待核验，不能自动推定入口')
        if code == 'road_calculation_timeout':
            return _failure(504, code, '道路计算超时，未据此判断是否可达')
        if code == 'road_calculation_capacity_exceeded':
            return _failure(422, code, '所选范围超过当前交互计算容量，未返回截断结果；可缩小预算后重试')
        if code == 'road_engine_completion_required':
            return _failure(503, code, '当前道路引擎不能确认计算完成，请联系管理员更新；未返回不完整范围')
        return _failure(503, 'road_calculation_unavailable', '道路计算未完成，未据此判断是否可达')
    except PermissionError:
        return _failure(403, 'road_network_unavailable', '没有可访问的路网，请核对通行授权')
    except OSError:
        return _failure(503, 'road_graph_unavailable', '路网文件暂不可用')
    except ValueError:
        return _failure(503, 'road_network_not_available', '路网来源或条件待核验')
    except SQLAlchemyError:
        return _failure(503, 'road_artifact_storage_unavailable', '道路成果未能完成留存，请稍后重试；案件记录不受影响')
    finally:
        _slots.release()


async def _request_calculation(request, function, db, payload, **points):
    cancel_event = Event()
    done = anyio.Event()
    response = None

    async def calculate():
        nonlocal response
        try:
            # Do not abandon this thread on cancellation: the request's database
            # dependency must remain alive until the worker has stopped using it.
            response = await anyio.to_thread.run_sync(partial(
                _calculate, function, db, payload, cancel_event=cancel_event, **points),
                abandon_on_cancel=False)
        finally:
            done.set()

    async with anyio.create_task_group() as group:
        group.start_soon(calculate)
        try:
            while not done.is_set():
                with anyio.move_on_after(.1):
                    await done.wait()
                if not done.is_set() and await request.is_disconnected():
                    cancel_event.set()
                    await done.wait()
                    break
        finally:
            # Handles ASGI cancellation and unexpected disconnect-reader errors
            # too. Task-group exit waits for the shielded worker to finish.
            cancel_event.set()
    return response


@router.post('/routes')
async def reference_route(payload: RouteRequest, request: Request, db: Session = Depends(read_session)):
    return await _request_calculation(request, calculations.calculate_reference_route,
                                      db, payload, start=payload.start, end=payload.end)


@router.post('/distance-matrices')
async def distance_matrix(payload: MatrixRequest, request: Request, db: Session = Depends(read_session)):
    return await _request_calculation(request, calculations.calculate_distance_matrix, db, payload,
                                      sources=payload.sources, targets=payload.targets)


@router.post('/reachability-previews', summary='管理员可达范围验收（不代表完整覆盖）')
async def reachability_preview(payload: ReachabilityRequest, request: Request,
                               db: Session = Depends(reachability_session)):
    distance = isinstance(payload, DistanceReachabilityRequest)
    calculate = calculations.calculate_distance_reachability if distance else calculations.calculate_time_reachability

    def authorized_preview(session, **kwargs):
        if not _is_preview_admin(session):
            raise PermissionError('preview_admin_required')
        result = calculate(session, **kwargs)
        if not _is_preview_admin(session):
            raise PermissionError('preview_admin_required')
        return result

    budget = {'distance_m': payload.distance_m} if distance else {'seconds': payload.seconds}
    return await _request_calculation(request, authorized_preview, db, payload, origin=payload.origin, **budget)


@router.post('/reachable-roads', summary='预算内道路段参考（不是区域覆盖或不可达判定）')
async def reachable_roads(payload: ReachabilityRequest, request: Request,
                          db: Session = Depends(read_session)):
    distance = isinstance(payload, DistanceReachabilityRequest)
    calculate = calculations.calculate_distance_reachability if distance else calculations.calculate_time_reachability

    def authorized_roads(session, **kwargs):
        if _current_analysis_role(session) not in ('admin', 'analyst'):
            raise PermissionError('analysis_role_required')
        # The shared calculation service selects the current permitted graph
        # and rechecks its scope/conditions after the isolated native process.
        result = calculate(session, **kwargs)
        if _current_analysis_role(session) not in ('admin', 'analyst'):
            raise PermissionError('analysis_role_required')
        if result.get('native_completion_contract') != 'completed-v1':
            raise RoadCalculationError('road_engine_completion_required')
        return {**result, 'interpretation': 'budgeted_road_segments_only',
                'boundary': '仅展示已知道路和参考车辆条件下计算所得的预算内道路段。'
                            '不代表完整区域覆盖；未显示道路不等于不可达，亦不确认设施入口或案发时通行状态。'}

    budget = {'distance_m': payload.distance_m} if distance else {'seconds': payload.seconds}
    return await _request_calculation(request, authorized_roads, db, payload, origin=payload.origin, **budget)


@router.post('/case-results/{result_id}/comparison')
async def case_road_comparison(result_id: str, request: Request, db: Session = Depends(read_session)):
    from app.services.case_road_comparison import compare_result_roads
    # Use the same frozen vehicle as background jobs, without manual selection.
    payload = _case_calculation(db, result_id, datetime.now(timezone.utc))
    return await _request_calculation(request, compare_result_roads, db, payload, result_id=result_id)


@router.post('/case-results/{result_id}/routes/{asset_id}')
async def case_target_route(result_id: str, asset_id: int, payload: ResultRouteRequest,
                            request: Request, db: Session = Depends(read_session)):
    from app.services.case_road_comparison import route_result_target
    reference = _case_calculation(db, result_id, payload.analysis_at)
    return await _request_calculation(request, route_result_target, db, reference,
        result_id=result_id, asset_id=asset_id, network_id=payload.network_id,
        graph_sha256=payload.graph_sha256, content_sha256=payload.content_sha256)


@router.post('/case-results/{result_id}/reachable-roads')
async def case_reachable_roads(result_id: str, payload: ResultReachabilityRequest,
                               request: Request, db: Session = Depends(read_session)):
    from app.services.case_road_comparison import reachable_result_roads
    reference = _case_calculation(db, result_id, payload.analysis_at)

    def authorized_case_roads(session, **kwargs):
        if _current_analysis_role(session) not in ('admin', 'analyst'):
            raise PermissionError('analysis_role_required')
        result = reachable_result_roads(session, **kwargs)
        if _current_analysis_role(session) not in ('admin', 'analyst'):
            raise PermissionError('analysis_role_required')
        return result

    return await _request_calculation(request, authorized_case_roads, db, reference,
        result_id=result_id, network_id=payload.network_id, graph_sha256=payload.graph_sha256,
        content_sha256=payload.content_sha256, metric=payload.metric,
        budget=payload.distance_m if isinstance(payload, ResultDistanceBudget) else payload.seconds)


def _artifact_read(function, db, *args, **kwargs):
    try:
        return JSONResponse(jsonable_encoder(function(db, *args, **kwargs)), headers={'Cache-Control': 'no-store'})
    except PermissionError:
        return _failure(404, 'road_artifact_not_available', '道路成果不存在或当前不可访问')
    except ValueError:
        return _failure(409, 'road_artifact_reference_invalid', '道路成果引用已变化或校验未通过，请重新查询')
    except SQLAlchemyError:
        return _failure(503, 'road_artifact_storage_unavailable', '道路成果暂时无法读取')


@router.get('/artifacts/{artifact_id}')
def road_artifact(artifact_id: str, db: Session = Depends(read_session)):
    from app.services.case_road_artifact_service import read_road_artifact
    return _artifact_read(read_road_artifact, db, artifact_id)


@router.get('/case-results/{result_id}/artifacts')
def road_history(result_id: str, limit: int = Query(10, ge=1, le=20),
                 before_id: str | None = Query(None, min_length=1, max_length=36), db: Session = Depends(read_session)):
    from app.services.case_road_artifact_service import road_artifact_history
    return _artifact_read(road_artifact_history, db, result_id, limit=limit, before_id=before_id)


@router.get('/case-results/{result_id}/automatic-comparison')
def automatic_comparison(result_id: str, db: Session = Depends(read_session)):
    from app.services.case_road_status import automatic_comparison_status
    return _artifact_read(automatic_comparison_status, db, result_id)
