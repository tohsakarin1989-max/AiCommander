import pytest
from pydantic import ValidationError
from pathlib import Path

from app.config import Settings


def production_settings(**overrides):
    values = {
        "SECRET_KEY": "s" * 64,
        "ENVIRONMENT": "production",
        "AUTH_REQUIRED": True,
        "SESSION_COOKIE_SECURE": True,
        "AUTO_CREATE_TABLES": False,
        "ENABLE_API_DOCS": False,
        "DATABASE_URL": "postgresql://aicommander:password@postgres:5432/aicommander",
        "REDIS_URL": "redis://:password@redis:6379/0",
        "FRONTEND_URL": "https://aicommander.example.org",
        "CORS_ORIGINS": "https://aicommander.example.org",
        "ALLOWED_HOSTS": "aicommander.example.org,backend,frontend",
        "BOOTSTRAP_TOKEN": "b" * 64,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_settings_accept_secure_deployment_configuration():
    settings = production_settings()

    assert settings.ENVIRONMENT == "production"
    assert settings.DATABASE_URL.startswith("postgresql://")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DATABASE_URL", "sqlite:///./aicommander.db"),
        ("DATABASE_URL", "postgresql://aicommander@postgres:5432/aicommander"),
        ("REDIS_URL", "redis://redis:6379/0"),
        ("FRONTEND_URL", "http://aicommander.example.org"),
        ("CORS_ORIGINS", "http://aicommander.example.org"),
        ("ALLOWED_HOSTS", "*"),
        ("ENABLE_API_DOCS", True),
        ("BOOTSTRAP_TOKEN", "short-token"),
    ],
)
def test_production_settings_reject_unsafe_configuration(field, value):
    with pytest.raises(ValidationError):
        production_settings(**{field: value})


def test_production_agent_lab_is_opt_in_and_uses_a_dedicated_worker_profile():
    project_root = Path(__file__).resolve().parents[2]
    compose = (project_root / "docker-compose.production.yml").read_text(encoding="utf-8")
    env_example = (project_root / ".env.production.example").read_text(encoding="utf-8")
    frontend_dockerfile = (project_root / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert "ENABLE_AGENT_LAB: \"${ENABLE_AGENT_LAB:-false}\"" in compose
    assert "AGENT_MODE: \"${AGENT_MODE:-off}\"" in compose
    assert "AGENT_MUTATIONS_ENABLED: \"${AGENT_MUTATIONS_ENABLED:-false}\"" in compose
    assert "agent-worker:" in compose
    assert 'profiles: ["agent-lab"]' in compose
    assert '--queues=${AGENT_REDIS_QUEUE:-agent_lab}' in compose
    assert '"--beat"' in compose
    assert "ENABLE_AGENT_LAB=false" in env_example
    assert "AGENT_MODE=off" in env_example
    assert "AGENT_MUTATIONS_ENABLED=false" in env_example
    assert "ARG VITE_ENABLE_AGENT_LAB=false" in frontend_dockerfile

    task_source = (project_root / "backend/app/tasks/agent_tasks.py").read_text(encoding="utf-8")
    assert "acks_late=True" in task_source
    assert "reject_on_worker_lost=True" in task_source
