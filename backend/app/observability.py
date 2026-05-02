import time
import uuid
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.logger import logger


REQUEST_ID_HEADER = "X-Request-Id"


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get(REQUEST_ID_HEADER) or ""


def _message_from_detail(status_code: int, detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def _error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    detail: Any,
) -> dict[str, Any]:
    # 保留 FastAPI 兼容的 detail 字段，前端旧逻辑仍可直接读取。
    return {
        "detail": detail,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": detail,
        },
    }


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 request id，并记录基础访问日志。"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        started_at = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s %s -> %s %.1fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = _get_request_id(request)
    message = _message_from_detail(exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        headers={REQUEST_ID_HEADER: request_id},
        content=_error_payload(
            code=f"http_{exc.status_code}",
            message=message,
            request_id=request_id,
            detail=exc.detail,
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = _get_request_id(request)
    return JSONResponse(
        status_code=422,
        headers={REQUEST_ID_HEADER: request_id},
        content=_error_payload(
            code="validation_error",
            message="请求参数校验失败",
            request_id=request_id,
            detail=exc.errors(),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = _get_request_id(request)
    logger.exception("%s unhandled request error: %s", request_id, exc)
    return JSONResponse(
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id},
        content=_error_payload(
            code="internal_server_error",
            message="服务器内部错误",
            request_id=request_id,
            detail="服务器内部错误",
        ),
    )


def install_observability(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
