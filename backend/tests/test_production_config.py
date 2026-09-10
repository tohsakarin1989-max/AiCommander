import pytest
from pydantic import ValidationError
from pathlib import Path

from app.config import Settings


def production_settings(**overrides):
    values = {
        "SECRET_KEY": "s" * 64,
        "APP_VERSION": "3.0.0-stable",
        "ALEMBIC_TARGET": "a7d9e1f2b304",
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
        "ENABLE_LEGACY_PUBLIC_MAP_SYNC": False,
        "ENABLE_LEGACY_EXTERNAL_GEO": False,
        "ENABLE_LEGACY_PATROL_MATERIALIZATION": False,
        "ENABLE_LEGACY_OPERATIONS_MODULES": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_settings_accept_secure_deployment_configuration():
    settings = production_settings()

    assert settings.ENVIRONMENT == "production"
    assert settings.DATABASE_URL.startswith("postgresql://")
    assert settings.ENABLE_LEGACY_OPERATIONS_MODULES is False


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
        ("ENABLE_LEGACY_PUBLIC_MAP_SYNC", True),
        ("ENABLE_LEGACY_EXTERNAL_GEO", True),
        ("ENABLE_LEGACY_PATROL_MATERIALIZATION", True),
        ("ENABLE_LEGACY_OPERATIONS_MODULES", True),
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
    frontend_nginx = (project_root / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    production_requirements = (
        project_root / "backend" / "requirements.txt"
    ).read_text(encoding="utf-8")
    optional_openai_requirements = (
        project_root / "backend" / "requirements-agent-openai.txt"
    ).read_text(encoding="utf-8")

    assert "ENABLE_AGENT_LAB: \"${ENABLE_AGENT_LAB:-false}\"" in compose
    assert "AGENT_MODE: \"${AGENT_MODE:-off}\"" in compose
    assert "AGENT_MUTATIONS_ENABLED: \"${AGENT_MUTATIONS_ENABLED:-false}\"" in compose
    assert "AGENT_PROVIDER: \"${AGENT_PROVIDER:-deterministic}\"" in compose
    assert "AGENT_MODEL: \"${AGENT_MODEL:-}\"" in compose
    assert "AGENT_MODEL_ID: \"${AGENT_MODEL_ID:-}\"" in compose
    assert "AGENT_MODEL_INPUT_COST_PER_MILLION_USD: \"${AGENT_MODEL_INPUT_COST_PER_MILLION_USD:-0}\"" in compose
    assert "AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD: \"${AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD:-0}\"" in compose
    assert "AGENT_MAP_PILOT_MAX_ASSETS: \"${AGENT_MAP_PILOT_MAX_ASSETS:-100}\"" in compose
    assert "AGENT_CASE_PILOT_MAX_CASES: \"${AGENT_CASE_PILOT_MAX_CASES:-30}\"" in compose
    assert "AGENT_DUAL_DOMAIN_PILOT_MAX_CASES: \"${AGENT_DUAL_DOMAIN_PILOT_MAX_CASES:-10}\"" in compose
    assert "AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS: \"${AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS:-100}\"" in compose
    assert "agent-worker:" in compose
    assert 'profiles: ["agent-lab"]' in compose
    assert '--queues=${AGENT_REDIS_QUEUE:-agent_lab}' in compose
    assert "celery-beat:" in compose
    assert '"beat", "--loglevel=info"' in compose
    assert "ENABLE_AGENT_LAB=false" in env_example
    assert "AGENT_MODE=off" in env_example
    assert "ENABLE_LEGACY_OPERATIONS_MODULES=false" in env_example
    assert 'ENABLE_LEGACY_OPERATIONS_MODULES: "false"' in compose
    assert "ENABLE_LEGACY_PUBLIC_MAP_SYNC=false" in env_example
    assert "ENABLE_LEGACY_EXTERNAL_GEO=false" in env_example
    assert "ENABLE_LEGACY_PATROL_MATERIALIZATION=false" in env_example
    assert 'ENABLE_LEGACY_PUBLIC_MAP_SYNC: "false"' in compose
    assert 'ENABLE_LEGACY_EXTERNAL_GEO: "false"' in compose
    assert 'ENABLE_LEGACY_PATROL_MATERIALIZATION: "false"' in compose
    assert "ALEMBIC_TARGET=head" in env_example
    assert "POSTGIS_IMAGE=postgis/postgis:16-3.4-alpine@sha256:" in env_example

    deploy_script = (project_root / "scripts" / "deploy-production.sh").read_text(
        encoding="utf-8"
    )
    assert 'alembic upgrade "$ALEMBIC_TARGET"' in deploy_script
    assert "alembic upgrade head" not in deploy_script
    assert "AGENT_MUTATIONS_ENABLED=false" in env_example
    assert "AGENT_PROVIDER=deterministic" in env_example
    assert "AGENT_MODEL=" in env_example
    assert "AGENT_MODEL_ID=" in env_example
    assert "AGENT_MODEL_INPUT_COST_PER_MILLION_USD=0" in env_example
    assert "AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD=0" in env_example
    assert "AGENT_MAP_PILOT_MAX_ASSETS=100" in env_example
    assert "AGENT_CASE_PILOT_MAX_CASES=30" in env_example
    assert "AGENT_DUAL_DOMAIN_PILOT_MAX_CASES=10" in env_example
    assert "AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS=100" in env_example
    assert "ARG VITE_ENABLE_AGENT_LAB=false" in frontend_dockerfile
    assert "client_max_body_size 256m;" in frontend_nginx
    assert "openai-agents==" not in production_requirements
    assert "openai-agents==0.19.1" in optional_openai_requirements

    task_source = (project_root / "backend/app/tasks/agent_tasks.py").read_text(encoding="utf-8")
    assert "acks_late=True" in task_source
    assert "reject_on_worker_lost=True" in task_source


def test_model_registry_requires_an_explicit_model_and_non_negative_prices():
    unset = production_settings(AGENT_MODEL_ID="")
    assert unset.AGENT_MODEL_ID is None

    with pytest.raises(ValidationError):
        production_settings(
            ENABLE_AGENT_LAB=True,
            AGENT_MODE="shadow",
            AGENT_USE_EXTERNAL_MODEL=True,
            AGENT_PROVIDER="model_registry",
            AGENT_MODEL_ID=None,
        )

    configured = production_settings(
        ENABLE_AGENT_LAB=True,
        AGENT_MODE="shadow",
        AGENT_USE_EXTERNAL_MODEL=True,
        AGENT_PROVIDER="model_registry",
        AGENT_MODEL_ID=12,
    )
    assert configured.AGENT_MODEL_ID == 12

    with pytest.raises(ValidationError):
        production_settings(AGENT_MODEL_INPUT_COST_PER_MILLION_USD=-0.01)
