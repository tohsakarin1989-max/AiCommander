"""Admin-only bounded schema-2 transport, separate from legacy ZIP import."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.offline_maps import _require_admin, _user_id
from app.database import get_db
from app.services import map_package_import_service as service
from app.services.map_package_set import MAX_CHUNK_BYTES, MAX_MANIFEST_BYTES
from app.services.map_package_registration import register_display_bundle


router = APIRouter(prefix='/map-package-imports')


async def _body(request: Request, limit: int) -> bytes:
    content = bytearray()
    async for block in request.stream():
        if len(content) + len(block) > limit:
            raise HTTPException(413, detail='地图上传内容超出大小限制')
        content.extend(block)
    return bytes(content)


def _call(db, operation, *args, **kwargs):
    try:
        return operation(db, *args, **kwargs)
    except ValueError as exc:
        db.rollback()
        code = str(exc)
        status = 404 if code == 'map_import_not_found' else (
            409 if code in {'map_import_incomplete', 'map_import_not_receiving',
                           'map_import_not_validated', 'bundle_id_exists'} else 422)
        raise HTTPException(status, detail={'code': code, 'message': '地图导入请求或任务状态不符合要求'}) from exc
    except (OSError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(503, detail={'code': 'map_import_unavailable',
            'message': '地图导入存储暂不可用，可稍后重试'}, headers={'Retry-After': '5'}) from exc


@router.post('', status_code=201)
async def create(request: Request, response: Response, db: Session = Depends(get_db)):
    principal = _require_admin(request)
    content = await _body(request, MAX_MANIFEST_BYTES)
    def operation(db):
        row = service.create_import(db, content, user_id=_user_id(principal))
        return service.get_import(db, row.id)
    result = await run_in_threadpool(_call, db, operation)
    response.headers['Location'] = f"/api/map-package-imports/{result['id']}"
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.get('/{run_id}')
def status(run_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_admin(request)
    response.headers['Cache-Control'] = 'no-store'
    return _call(db, service.get_import, str(run_id))


@router.put('/{run_id}/chunks/{name}')
async def upload(run_id: UUID, name: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    content = await _body(request, MAX_CHUNK_BYTES)
    return await run_in_threadpool(_call, db, service.put_chunk, str(run_id), name, content)


@router.post('/{run_id}/submit', status_code=202)
def submit(run_id: UUID, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    return _call(db, service.submit_import, str(run_id))


@router.post('/{run_id}/register')
async def register(run_id: UUID, request: Request, response: Response,
                   db: Session = Depends(get_db)):
    principal = _require_admin(request)
    response.headers['Cache-Control'] = 'no-store'
    return await run_in_threadpool(_call, db, register_display_bundle, str(run_id),
                                  user_id=_user_id(principal))
