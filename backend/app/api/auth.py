import hmac
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.auth_service import (
    AccountLockedError,
    AuthenticationError,
    AuthPrincipal,
    AuthService,
    AuthorizationError,
)


router = APIRouter()


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BootstrapStatusResponse(BaseModel):
    initialized: bool
    bootstrap_available: bool


class BootstrapRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


class UserCreateRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: Literal["admin", "analyst", "viewer"] = "viewer"


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[Literal["admin", "analyst", "viewer"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def _principal(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "principal", None)
    if not principal:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:64]
    return request.client.host[:64] if request.client else None


def _set_session_cookie(response: Response, token: str, expires_at: datetime, request: Request) -> None:
    secure = getattr(request.app.state, "auth_secure_cookie", settings.SESSION_COOKIE_SECURE)
    max_age = max(0, int((expires_at - AuthService.now()).total_seconds()))
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(request: Request, db: Session = Depends(get_db)):
    token = getattr(request.app.state, "auth_bootstrap_token", settings.BOOTSTRAP_TOKEN)
    return BootstrapStatusResponse(
        initialized=db.query(User.id).first() is not None,
        bootstrap_available=bool(token),
    )


@router.post("/bootstrap", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def bootstrap(
    payload: BootstrapRequest,
    request: Request,
    response: Response,
    x_bootstrap_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    expected = getattr(request.app.state, "auth_bootstrap_token", settings.BOOTSTRAP_TOKEN)
    if not expected:
        raise HTTPException(status_code=503, detail="服务器未启用首次管理员初始化")
    if not x_bootstrap_token or not hmac.compare_digest(x_bootstrap_token, expected):
        raise HTTPException(status_code=403, detail="初始化凭据无效")
    try:
        user = AuthService.bootstrap_admin(
            db,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            client_ip=_client_ip(request),
            request_id=request.headers.get("x-request-id"),
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token, expires_at = AuthService.create_session(
        db,
        user,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, token, expires_at, request)
    return SessionResponse(user=UserResponse.model_validate(user), expires_at=expires_at)


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user = AuthService.authenticate_credentials(db, payload.username, payload.password)
    except AccountLockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    token, expires_at = AuthService.create_session(
        db,
        user,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    AuthService.record_audit(
        db,
        action="auth.login",
        user=user,
        method="POST",
        path="/api/auth/login",
        status_code=200,
        client_ip=_client_ip(request),
        request_id=request.headers.get("x-request-id"),
    )
    _set_session_cookie(response, token, expires_at, request)
    return SessionResponse(user=UserResponse.model_validate(user), expires_at=expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    principal = _principal(request)
    AuthService.revoke_session(db, principal.session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/me", response_model=UserResponse)
def me(request: Request, db: Session = Depends(get_db)):
    principal = _principal(request)
    user = db.query(User).filter(User.id == principal.user_id).one()
    return user


@router.get("/users", response_model=list[UserResponse])
def list_users(_: AuthPrincipal = Depends(_principal), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.asc()).all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    _: AuthPrincipal = Depends(_principal),
    db: Session = Depends(get_db),
):
    try:
        return AuthService.create_user(
            db,
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    principal: AuthPrincipal = Depends(_principal),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    removes_admin = user.role == "admin" and (
        payload.role not in (None, "admin") or payload.is_active is False
    )
    if removes_admin and db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count() <= 1:
        raise HTTPException(status_code=409, detail="不能停用或降级最后一个管理员")
    if user.id == principal.user_id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="不能停用当前登录账号")
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()[:100] or user.username
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        try:
            user.password_hash = AuthService.hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        user.password_changed_at = AuthService.now()
        user.session_version += 1
        AuthService.revoke_user_sessions(db, user.id)
    db.commit()
    db.refresh(user)
    return user
