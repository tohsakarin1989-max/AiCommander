from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_version_is_exposed_consistently():
    from app.config import settings
    from app.main import app

    repository_version = (REPOSITORY_ROOT / "VERSION").read_text().strip()
    env_example = (REPOSITORY_ROOT / ".env.production.example").read_text()
    compose = (REPOSITORY_ROOT / "docker-compose.production.yml").read_text()
    layout = (
        REPOSITORY_ROOT / "frontend/src/components/Layout.tsx"
    ).read_text()

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?", repository_version)
    assert settings.APP_VERSION == repository_version
    assert app.version == repository_version
    assert f"APP_VERSION={repository_version}" in env_example
    assert f"${{APP_VERSION:-{repository_version}}}" in compose
    assert f"runtime?.version || '{repository_version}'" in layout


def test_github_quality_gate_covers_release_checks():
    workflow = (
        REPOSITORY_ROOT / ".github/workflows/release-quality.yml"
    ).read_text()

    required_steps = (
        "python-version: '3.12'",
        "npm ci",
        "python -m pytest",
        "npm run test -- --run",
        "npm run typecheck",
        "npm run build",
        "docker compose",
        "git diff --check",
    )
    for required_step in required_steps:
        assert required_step in workflow
