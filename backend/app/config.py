from pydantic_settings import BaseSettings
from typing import Optional

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
    ENABLE_VECTOR_DB: bool = True
    ENABLE_BONUS_ACCOUNTING: bool = False
    AUTO_CREATE_TABLES: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
