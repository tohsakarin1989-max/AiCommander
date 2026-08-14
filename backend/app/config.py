from typing import Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 默认使用本地 SQLite，避免对 PostgreSQL/Docker 的强依赖
    # 如需使用 PostgreSQL，可通过环境变量 DATABASE_URL 覆盖此值
    DATABASE_URL: str = "sqlite:///./aicommander.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    AUTH_REQUIRED: bool = True
    AUTH_ISSUER: str = "aicommander"
    BOOTSTRAP_TOKEN: Optional[str] = None
    SESSION_COOKIE_NAME: str = "aicommander_session"
    SESSION_COOKIE_SECURE: bool = True
    PASSWORD_HASH_ITERATIONS: int = 600_000
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    ALLOWED_HOSTS: str = "localhost,127.0.0.1,testserver"
    ENABLE_API_DOCS: bool = False
    ENABLE_VECTOR_DB: bool = True
    ENABLE_BONUS_ACCOUNTING: bool = False
    AUTO_CREATE_TABLES: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.ENVIRONMENT != "production":
            return self

        weak_secrets = {
            "your-secret-key-change-in-production",
            "change-me",
            "secret",
        }
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY.lower() in weak_secrets:
            raise ValueError("生产环境 SECRET_KEY 必须是至少 32 位的随机值")
        if not self.AUTH_REQUIRED:
            raise ValueError("生产环境不允许关闭 AUTH_REQUIRED")
        if not self.SESSION_COOKIE_SECURE:
            raise ValueError("生产环境必须启用安全会话 Cookie")
        if self.AUTO_CREATE_TABLES:
            raise ValueError("生产环境必须关闭 AUTO_CREATE_TABLES 并使用 Alembic")
        return self

settings = Settings()
