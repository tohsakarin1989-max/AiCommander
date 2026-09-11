from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_VERSION: str = "4.5.0-stable"
    ALEMBIC_TARGET: str = "head"
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
    ENABLE_VECTOR_DB: bool = False
    ENABLE_BONUS_ACCOUNTING: bool = False
    AUTO_CREATE_TABLES: bool = True
    ENABLE_AGENT_LAB: bool = False
    ENABLE_SHOWCASE: bool = False
    AGENT_MODE: Literal["off", "shadow", "assist"] = "off"
    AGENT_MUTATIONS_ENABLED: bool = False
    AGENT_EXTERNAL_DATA_POLICY: Literal["redacted_only", "local_only"] = "redacted_only"
    AGENT_MAX_STEPS: int = 8
    AGENT_TIMEOUT_SECONDS: int = 120
    AGENT_REDIS_QUEUE: str = "agent_lab"
    AGENT_PROVIDER: Literal["deterministic", "openai_agents", "model_registry"] = "deterministic"
    AGENT_MODEL: str = ""
    AGENT_MODEL_ID: Optional[int] = None
    AGENT_MODEL_INPUT_COST_PER_MILLION_USD: float = 0
    AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD: float = 0
    AGENT_USE_EXTERNAL_MODEL: bool = False
    AGENT_SDK_TRACING_ENABLED: bool = False
    AGENT_APPROVAL_TTL_HOURS: int = 24
    AGENT_MAP_PILOT_MAX_ASSETS: int = 100
    AGENT_CASE_PILOT_MAX_CASES: int = 30
    AGENT_DUAL_DOMAIN_PILOT_MAX_CASES: int = 10
    AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS: int = 100
    MAP_PACKAGE_ROOT: str = "./data/map-packages"
    MAP_AUTO_PUBLISH_AREA_IDS: str = ""
    ENABLE_LEGACY_PUBLIC_MAP_SYNC: bool = False
    ENABLE_LEGACY_EXTERNAL_GEO: bool = False
    ENABLE_LEGACY_PATROL_MATERIALIZATION: bool = False
    ENABLE_LEGACY_OPERATIONS_MODULES: bool = True
    MODEL_DATA_EGRESS_POLICY: Literal["local_only", "external_redacted_only"] = "local_only"
    TRUSTED_LOCAL_MODEL_HOSTS: str = "localhost,127.0.0.1,::1"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    @field_validator("AGENT_MODEL_ID", mode="before")
    @classmethod
    def empty_agent_model_id_is_unset(cls, value):
        return None if value == "" else value

    @field_validator('MAP_AUTO_PUBLISH_AREA_IDS')
    @classmethod
    def validate_map_publish_areas(cls, value):
        if not value.strip():
            return ''
        parts = value.split(',')
        if (len(parts) > 16 or any(not p.strip().isdigit() or not 0 < int(p) < 2**31 for p in parts)
                or len({int(p) for p in parts}) != len(parts)):
            raise ValueError('地图自动发布厂区必须为最多16个不重复的正整数ID')
        return ','.join(str(int(p)) for p in parts)

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.AGENT_MUTATIONS_ENABLED and (
            not self.ENABLE_AGENT_LAB or self.AGENT_MODE != "assist"
        ):
            raise ValueError("Agent 正式数据写入仅允许在已启用的 assist 模式开启")
        if self.AGENT_MODE != "off" and not self.ENABLE_AGENT_LAB:
            raise ValueError("启用 Agent 运行模式前必须先开启 ENABLE_AGENT_LAB")
        if self.AGENT_USE_EXTERNAL_MODEL and self.AGENT_EXTERNAL_DATA_POLICY == "local_only":
            raise ValueError("local_only 数据策略不允许调用外部 Agent 模型")
        if self.AGENT_USE_EXTERNAL_MODEL:
            if self.AGENT_PROVIDER == "deterministic":
                raise ValueError("启用外部模型时必须显式选择外部 Agent 适配器")
            if self.AGENT_PROVIDER == "openai_agents" and not (
                self.OPENAI_API_KEY and self.OPENAI_API_KEY.strip()
            ):
                raise ValueError("OpenAI Agents 适配器需要 OPENAI_API_KEY")
            if self.AGENT_PROVIDER == "openai_agents" and not self.AGENT_MODEL.strip():
                raise ValueError("启用外部模型时 AGENT_MODEL 不能为空")
            if self.AGENT_PROVIDER == "model_registry" and not (
                self.AGENT_MODEL_ID and self.AGENT_MODEL_ID > 0
            ):
                raise ValueError("模型注册表适配器需要有效的 AGENT_MODEL_ID")
        if (
            self.AGENT_MODEL_INPUT_COST_PER_MILLION_USD < 0
            or self.AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD < 0
        ):
            raise ValueError("Agent 模型价格配置不能为负数")
        if not 1 <= self.AGENT_MAX_STEPS <= 32:
            raise ValueError("AGENT_MAX_STEPS 必须在 1-32 之间")
        if not 10 <= self.AGENT_TIMEOUT_SECONDS <= 1800:
            raise ValueError("AGENT_TIMEOUT_SECONDS 必须在 10-1800 秒之间")
        if not self.AGENT_REDIS_QUEUE.strip():
            raise ValueError("AGENT_REDIS_QUEUE 不能为空")
        if not 1 <= self.AGENT_MAP_PILOT_MAX_ASSETS <= 500:
            raise ValueError("AGENT_MAP_PILOT_MAX_ASSETS 必须在 1-500 之间")
        if not 1 <= self.AGENT_CASE_PILOT_MAX_CASES <= 30:
            raise ValueError("AGENT_CASE_PILOT_MAX_CASES 必须在 1-30 之间")
        if not 1 <= self.AGENT_DUAL_DOMAIN_PILOT_MAX_CASES <= 30:
            raise ValueError("AGENT_DUAL_DOMAIN_PILOT_MAX_CASES 必须在 1-30 之间")
        if not 1 <= self.AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS <= 500:
            raise ValueError("AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS 必须在 1-500 之间")

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
        if self.ENABLE_LEGACY_OPERATIONS_MODULES:
            raise ValueError("生产环境必须关闭未纳入厂区隔离的旧巡逻、人员和重点部位模块")
        if (
            self.ENABLE_LEGACY_PUBLIC_MAP_SYNC
            or self.ENABLE_LEGACY_EXTERNAL_GEO
            or self.ENABLE_LEGACY_PATROL_MATERIALIZATION
        ):
            raise ValueError("生产环境必须关闭旧公网地图、外部地理和巡逻物化能力")
        if self.APP_VERSION == "3.0.0-stable" and self.ALEMBIC_TARGET != "a7d9e1f2b304":
            raise ValueError("v3.0.0-stable 必须绑定已发布的数据库迁移目标")
        if self.APP_VERSION != "3.0.0-stable" and self.ALEMBIC_TARGET != "head":
            raise ValueError("v3.1 及以上候选版本必须完成全部候选迁移")
        database_url = urlparse(self.DATABASE_URL)
        if (
            database_url.scheme
            not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
            or not database_url.hostname
            or not database_url.username
            or not database_url.password
            or database_url.path in {"", "/"}
        ):
            raise ValueError("生产环境 DATABASE_URL 必须使用带认证的 PostgreSQL 地址")

        redis_url = urlparse(self.REDIS_URL)
        if (
            redis_url.scheme not in {"redis", "rediss"}
            or not redis_url.hostname
            or not redis_url.password
        ):
            raise ValueError("生产环境 REDIS_URL 必须使用带密码的 Redis 地址")

        frontend_url = urlparse(self.FRONTEND_URL)
        if frontend_url.scheme != "https" or not frontend_url.hostname:
            raise ValueError("生产环境 FRONTEND_URL 必须是完整的 HTTPS 地址")

        cors_origins = [
            item.strip()
            for item in self.CORS_ORIGINS.split(",")
            if item.strip()
        ]
        for origin in cors_origins:
            parsed_origin = urlparse(origin)
            if parsed_origin.scheme != "https" or not parsed_origin.hostname:
                raise ValueError("生产环境 CORS_ORIGINS 只允许完整的 HTTPS 地址")

        allowed_hosts = [
            item.strip()
            for item in self.ALLOWED_HOSTS.split(",")
            if item.strip()
        ]
        if not allowed_hosts or "*" in allowed_hosts:
            raise ValueError("生产环境 ALLOWED_HOSTS 不允许为空或使用通配符")
        if self.ENABLE_API_DOCS:
            raise ValueError("生产环境必须关闭接口文档")
        if not self.BOOTSTRAP_TOKEN or len(self.BOOTSTRAP_TOKEN) < 32:
            raise ValueError("生产环境 BOOTSTRAP_TOKEN 必须是至少 32 位的随机值")
        return self

settings = Settings()
