"""统一案件成果：兼容生成入口及不可变历史读取。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import AreaWriteAccessError, get_db, require_area_write_access
from app.models.case import Case
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from app.services.case_result_export import CaseResultExportError, export_case_result_docx
from app.services.case_result_pdf import export_case_result_pdf

router = APIRouter()


def _principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "请先登录")
    return principal


def _unavailable():
    return HTTPException(404, "成果尚未生成、不可访问或引用已失效", headers={"Cache-Control": "no-store"})


@router.get("/case-results")
def result_catalog(request: Request, response: Response, q: str = Query("", max_length=100),
                   limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
                   db: Session = Depends(get_db)):
    _principal(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseResultService.catalog(db, query=q, limit=limit, offset=offset)
    except CaseResultAccessError:
        raise _unavailable() from None


@router.post("/cases/{case_id}/results")
def create_result(case_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    principal = _principal(request)
    if principal.role not in {"admin", "analyst"}:
        raise HTTPException(403, "只读账号不能生成成果")
    if "authorized_area_ids" not in db.info:
        raise _unavailable()
    area_id = db.scalar(select(Case.operational_area_id).where(Case.id == case_id))
    if area_id is None:
        raise _unavailable()
    try:
        require_area_write_access(db, area_id)
        result, created = CaseResultService.create_current(db, case_id)
        db.commit()
    except AreaWriteAccessError:
        raise HTTPException(403, "没有目标辖区写权限") from None
    except CaseResultAccessError:
        db.rollback()
        raise _unavailable() from None
    except ValueError:
        db.rollback()
        raise HTTPException(409, "当前画像或候选内容不完整，暂不能形成成果") from None
    response.status_code = 201 if created else 200
    response.headers["Location"] = f"/api/case-results/{result['id']}"
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/cases/{case_id}/results/history")
def result_history(case_id: int, request: Request, response: Response,
                   limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
                   db: Session = Depends(get_db)):
    _principal(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseResultService.history(db, case_id, limit, offset)
    except CaseResultAccessError:
        raise _unavailable() from None


@router.get("/cases/{case_id}/results/latest")
def latest_result(case_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    _principal(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseResultService.latest(db, case_id)
    except CaseResultAccessError:
        raise _unavailable() from None


@router.get("/case-results/{result_id}")
def read_result(result_id: str, request: Request, response: Response, db: Session = Depends(get_db)):
    _principal(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseResultService.read(db, result_id)
    except CaseResultAccessError:
        raise _unavailable() from None


@router.get("/case-results/{result_id}/document.docx")
def download_result_docx(result_id: str, request: Request, db: Session = Depends(get_db),
                         road_artifact_id: str | None = Query(None, min_length=36, max_length=36, pattern=r"^[a-f0-9-]+$")):
    return _download_result(result_id, request, db, "docx", road_artifact_id)


@router.get("/case-results/{result_id}/document.pdf")
def download_result_pdf(result_id: str, request: Request, db: Session = Depends(get_db),
                        road_artifact_id: str | None = Query(None, min_length=36, max_length=36, pattern=r"^[a-f0-9-]+$")):
    return _download_result(result_id, request, db, "pdf", road_artifact_id)


def _download_result(result_id: str, request: Request, db: Session, format: str, road_artifact_id: str | None = None):
    _principal(request)
    try:
        exporter = export_case_result_pdf if format == "pdf" else export_case_result_docx
        document, data = (exporter(db, result_id, road_artifact_id=road_artifact_id)
                          if road_artifact_id else exporter(db, result_id))
    except (CaseResultAccessError, PermissionError):
        raise _unavailable() from None
    except SQLAlchemyError:
        raise HTTPException(503, "成果存储暂不可用", headers={"Cache-Control": "no-store"}) from None
    except CaseResultExportError as error:
        if error.code in {"document_too_large", "pdf_output_too_large"}:
            raise HTTPException(413, "成果过大，暂不能交互式导出", headers={"Cache-Control": "no-store"}) from None
        message = "本地文件渲染暂不可用，请稍后重试或联系管理员"
        if error.code == "map_rendering_not_ready":
            message = "该成果包含地图，地图文件渲染尚未就绪，未生成省略地图的报告"
        raise HTTPException(503, message, headers={"Cache-Control": "no-store", "Retry-After": "30"}) from None
    except ValueError:
        raise HTTPException(409, "成果格式不完整或版本暂不支持导出", headers={"Cache-Control": "no-store"}) from None
    media_type = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    road_headers = ({"X-Road-Artifact-ID": document.road_artifact_id,
                     "X-Road-Artifact-SHA256": document.road_artifact_sha256} if document.road_artifact_id else {})
    suffix = f'-road-{document.road_artifact_sha256[:16]}' if document.road_artifact_sha256 else ''
    return Response(data, media_type=media_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": f'attachment; filename="case-result-{document.content_sha256[:16]}{suffix}.{format}"',
                             "X-Result-Content-SHA256": document.content_sha256, **road_headers})
