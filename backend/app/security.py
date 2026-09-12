import logging
import re
from typing import Iterable, Optional

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings
from app.services.auth_service import AuthenticationError, AuthService


logger = logging.getLogger(__name__)

PUBLIC_API_PATHS = {
    "/api/auth/bootstrap-status",
    "/api/auth/bootstrap",
    "/api/auth/bootstrap-local",
    "/api/auth/login",
}
ADMIN_PATH_PREFIXES = (
    "/api/auth/users",
    "/api/system-config",
    "/api/models",
    "/api/deployment/",
    "/api/operational-areas",
    "/api/map-sources",
    "/api/map-import-templates",
    "/api/map-ingest-runs",
    "/api/map-conflicts",
    "/api/map-bundles",
    "/api/map-snapshots",
    "/api/admin/case-profiles",
    "/api/admin/situation",
    "/api/admin/evaluations",
    "/api/admin/intelligence-runtime",
    "/api/tech-defense/import-summary",
    "/api/agent-runs",
    "/api/agent-map-steward",
    "/api/agent-case-steward",
    "/api/agent-dual-domain",
    "/api/agents",
    "/api/conclusions/draft",  # 历史重新分析预览；日常预览读取冻结 workspace。
    "/api/jurisdiction/assets/import",
    "/api/jurisdiction/assets/sync-public-map",
    # 旧巡逻、人员和重点部位表不属于 v3.x 生产树干；生产环境不挂载，
    # 开发兼容模式下仍只允许管理员访问。
    "/api/patrols",
    "/api/key-locations",
    "/api/personnel",
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ADMIN_MUTATION_PATH_PREFIXES = (
    "/api/jurisdiction/assets",
    "/api/ws/broadcast",
    "/api/ws/meeting",
)
MANUAL_CASE_MAINTENANCE = re.compile(
    r"^/api/cases/(?:[0-9]+/preprocess|preprocess/batch|batch-review)$"
)


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:64]
    return request.client.host[:64] if request.client else None


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        session_factory,
        auth_required: Optional[bool] = None,
        bootstrap_token: Optional[str] = None,
        secure_cookie: Optional[bool] = None,
        allowed_origins: Optional[Iterable[str]] = None,
    ):
        super().__init__(app)
        self.session_factory = session_factory
        self.auth_required = settings.AUTH_REQUIRED if auth_required is None else auth_required
        self.bootstrap_token = settings.BOOTSTRAP_TOKEN if bootstrap_token is None else bootstrap_token
        self.secure_cookie = settings.SESSION_COOKIE_SECURE if secure_cookie is None else secure_cookie
        configured_origins = allowed_origins or (
            settings.FRONTEND_URL,
            *[item.strip() for item in settings.CORS_ORIGINS.split(",") if item.strip()],
        )
        self.allowed_origins = {origin.rstrip("/") for origin in configured_origins if origin}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.app.state.auth_bootstrap_token = self.bootstrap_token
        request.app.state.auth_secure_cookie = self.secure_cookie
        request.app.state.auth_session_factory = self.session_factory

        path = request.url.path.rstrip("/") or "/"
        if request.method == "OPTIONS" or not path.startswith("/api"):
            return await call_next(request)
        if not self.auth_required or path in PUBLIC_API_PATHS:
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        cookie_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
        token = bearer_token or cookie_token
        if not token:
            return JSONResponse(status_code=401, content={"detail": "请先登录"})

        db = self.session_factory()
        try:
            principal = AuthService.authenticate_token(db, token)
        except AuthenticationError as exc:
            response = JSONResponse(status_code=401, content={"detail": str(exc)})
            response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
            return response
        finally:
            db.close()

        if path.startswith(ADMIN_PATH_PREFIXES) and principal.role != "admin":
            return JSONResponse(status_code=403, content={"detail": "当前账号无权访问该功能"})
        if (request.method not in SAFE_METHODS
                and MANUAL_CASE_MAINTENANCE.fullmatch(path)
                and principal.role != "admin"):
            return JSONResponse(status_code=403, content={"detail": "手动重建和批量预处理仅供管理员维护，正常录入后系统自动处理"})
        if (
            request.method not in SAFE_METHODS
            and path.startswith(ADMIN_MUTATION_PATH_PREFIXES)
            and principal.role != "admin"
        ):
            return JSONResponse(status_code=403, content={"detail": "当前账号无权修改地图或广播数据"})
        is_logout = request.method == "POST" and path == "/api/auth/logout"
        if principal.role == "viewer" and request.method not in SAFE_METHODS and not is_logout:
            return JSONResponse(status_code=403, content={"detail": "只读账号不能执行写操作"})

        if cookie_token and request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in self.allowed_origins:
                return JSONResponse(status_code=403, content={"detail": "请求来源不受信任"})

        request.state.principal = principal
        response = await call_next(request)

        if request.method not in SAFE_METHODS:
            audit_db = self.session_factory()
            try:
                AuthService.record_audit(
                    audit_db,
                    action="api.mutation",
                    principal=principal,
                    method=request.method,
                    path=path,
                    status_code=response.status_code,
                    client_ip=_client_ip(request),
                    request_id=request.headers.get("x-request-id"),
                )
            except Exception:
                audit_db.rollback()
                logger.exception("写入审计日志失败")
            finally:
                audit_db.close()
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api") else "no-cache")
        if settings.ENVIRONMENT == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def authenticate_websocket(websocket: WebSocket) -> bool:
    """校验浏览器随 WebSocket 握手发送的 HttpOnly 会话 Cookie。"""
    if not settings.AUTH_REQUIRED:
        return True
    token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return False
    db = websocket.app.state.auth_session_factory()
    try:
        principal = AuthService.authenticate_token(db, token)
        websocket.state.principal = principal
        return True
    except AuthenticationError:
        return False
    finally:
        db.close()
