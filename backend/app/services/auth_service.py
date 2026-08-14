import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import AuditLog, User, UserSession


class AuthenticationError(Exception):
    pass


class AccountLockedError(AuthenticationError):
    pass


class AuthorizationError(Exception):
    pass


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: int
    username: str
    display_name: str
    role: str
    session_id: str


class AuthService:
    USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
    ROLES = {"admin", "analyst", "viewer"}

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def to_epoch(value: datetime) -> int:
        return int(value.replace(tzinfo=timezone.utc).timestamp())

    @staticmethod
    def normalize_username(username: str) -> str:
        normalized = (username or "").strip().lower()
        if not AuthService.USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("用户名只能包含字母、数字、点、下划线和短横线，长度 3-64 位")
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if not 12 <= len(password or "") <= 128:
            raise ValueError("密码长度必须为 12-128 位")
        character_classes = sum(
            (
                any(char.islower() for char in password),
                any(char.isupper() for char in password),
                any(char.isdigit() for char in password),
                any(not char.isalnum() for char in password),
            )
        )
        if character_classes < 3:
            raise ValueError("密码至少包含大小写字母、数字、特殊字符中的三类")

    @staticmethod
    def hash_password(password: str) -> str:
        AuthService.validate_password(password)
        salt = os.urandom(16)
        iterations = max(settings.PASSWORD_HASH_ITERATIONS, 210_000)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return "pbkdf2_sha256${}${}${}".format(
            iterations,
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            expected = base64.urlsafe_b64decode(digest_raw.encode())
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                base64.urlsafe_b64decode(salt_raw.encode()),
                int(iterations_raw),
            )
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def create_user(
        db: Session,
        *,
        username: str,
        display_name: Optional[str],
        password: str,
        role: str,
    ) -> User:
        normalized = AuthService.normalize_username(username)
        if role not in AuthService.ROLES:
            raise ValueError("不支持的用户角色")
        if db.query(User).filter(User.username == normalized).first():
            raise ValueError("用户名已存在")
        user = User(
            username=normalized,
            display_name=(display_name or normalized).strip()[:100],
            password_hash=AuthService.hash_password(password),
            role=role,
            is_active=True,
            password_changed_at=AuthService.now(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def bootstrap_admin(
        db: Session,
        *,
        username: str,
        display_name: Optional[str],
        password: str,
        client_ip: Optional[str],
        request_id: Optional[str],
    ) -> User:
        if db.query(User.id).first():
            raise AuthorizationError("系统已经完成初始化")
        user = AuthService.create_user(
            db,
            username=username,
            display_name=display_name,
            password=password,
            role="admin",
        )
        AuthService.record_audit(
            db,
            action="auth.bootstrap",
            user=user,
            method="POST",
            path="/api/auth/bootstrap",
            status_code=201,
            client_ip=client_ip,
            request_id=request_id,
        )
        return user

    @staticmethod
    def authenticate_credentials(db: Session, username: str, password: str) -> User:
        try:
            normalized = AuthService.normalize_username(username)
        except ValueError as exc:
            raise AuthenticationError("用户名或密码错误") from exc
        user = db.query(User).filter(User.username == normalized).first()
        now = AuthService.now()
        if user and user.locked_until and user.locked_until > now:
            raise AccountLockedError("登录失败次数过多，请稍后再试")
        if not user or not user.is_active or not AuthService.verify_password(password, user.password_hash):
            if user and user.is_active:
                user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
                if user.failed_login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                db.commit()
            raise AuthenticationError("用户名或密码错误")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def create_session(
        db: Session,
        user: User,
        *,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> tuple[str, datetime]:
        now = AuthService.now()
        expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        session_id = str(uuid.uuid4())
        session = UserSession(
            id=session_id,
            user_id=user.id,
            expires_at=expires_at,
            last_seen_at=now,
            client_ip=client_ip,
            user_agent=(user_agent or "")[:512],
        )
        db.add(session)
        db.commit()
        token = AuthService._encode_token(
            {
                "sub": str(user.id),
                "usr": user.username,
                "role": user.role,
                "jti": session_id,
                "ver": user.session_version,
                "iss": settings.AUTH_ISSUER,
                "iat": AuthService.to_epoch(now),
                "exp": AuthService.to_epoch(expires_at),
            }
        )
        return token, expires_at

    @staticmethod
    def _base64url_encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _base64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode())

    @staticmethod
    def _encode_token(payload: dict) -> str:
        if settings.ALGORITHM != "HS256":
            raise ValueError("当前仅支持 HS256 会话签名算法")
        header = AuthService._base64url_encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        body = AuthService._base64url_encode(
            json.dumps(payload, separators=(",", ":")).encode()
        )
        signing_input = f"{header}.{body}".encode()
        signature = hmac.new(settings.SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
        return f"{header}.{body}.{AuthService._base64url_encode(signature)}"

    @staticmethod
    def _decode_token(token: str) -> dict:
        try:
            header_raw, payload_raw, signature_raw = token.split(".", 2)
            header = json.loads(AuthService._base64url_decode(header_raw))
            payload = json.loads(AuthService._base64url_decode(payload_raw))
            signature = AuthService._base64url_decode(signature_raw)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("登录状态无效或已过期") from exc
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise AuthenticationError("登录状态无效或已过期")
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            f"{header_raw}.{payload_raw}".encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationError("登录状态无效或已过期")
        if payload.get("iss") != settings.AUTH_ISSUER or int(payload.get("exp", 0)) <= int(time.time()):
            raise AuthenticationError("登录状态无效或已过期")
        return payload

    @staticmethod
    def authenticate_token(db: Session, token: str) -> AuthPrincipal:
        try:
            payload = AuthService._decode_token(token)
            user_id = int(payload["sub"])
            session_id = str(payload["jti"])
            session_version = int(payload["ver"])
        except AuthenticationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("登录状态无效或已过期") from exc

        now = AuthService.now()
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if (
            not session
            or session.revoked_at is not None
            or session.expires_at <= now
            or not user
            or not user.is_active
            or user.session_version != session_version
        ):
            raise AuthenticationError("登录状态无效或已过期")
        if (now - session.last_seen_at) > timedelta(minutes=5):
            session.last_seen_at = now
            db.commit()
        return AuthPrincipal(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            session_id=session.id,
        )

    @staticmethod
    def revoke_session(db: Session, session_id: str) -> None:
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session and session.revoked_at is None:
            session.revoked_at = AuthService.now()
            db.commit()

    @staticmethod
    def revoke_user_sessions(db: Session, user_id: int) -> None:
        db.query(UserSession).filter(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        ).update({UserSession.revoked_at: AuthService.now()}, synchronize_session=False)
        db.commit()

    @staticmethod
    def record_audit(
        db: Session,
        *,
        action: str,
        user: Optional[User] = None,
        principal: Optional[AuthPrincipal] = None,
        method: Optional[str] = None,
        path: Optional[str] = None,
        status_code: Optional[int] = None,
        client_ip: Optional[str] = None,
        request_id: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> None:
        log = AuditLog(
            user_id=user.id if user else principal.user_id if principal else None,
            username=user.username if user else principal.username if principal else None,
            action=action,
            method=method,
            path=path,
            status_code=status_code,
            client_ip=client_ip,
            request_id=request_id,
            detail=detail,
        )
        db.add(log)
        db.commit()
