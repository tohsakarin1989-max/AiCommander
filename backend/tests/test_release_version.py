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
        "actions/checkout@v7.0.1",
        "actions/setup-python@v7.0.0",
        "actions/setup-node@v7.0.0",
        "python-version: '3.12'",
        "python -m pip install -r requirements-dev.txt",
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

    # 功能分支由 pull_request 触发，避免同一次更新重复跑 push 和 PR 两套任务。
    assert "      - codex/v2.0-production" not in workflow


def test_backend_ci_installs_real_map_style_validator_before_tests():
    import yaml

    workflow = yaml.safe_load((REPOSITORY_ROOT / '.github/workflows/release-quality.yml').read_text())
    steps = workflow['jobs']['backend']['steps']
    test_index = next(i for i, step in enumerate(steps) if step.get('run') == 'python -m pytest')
    prerequisites = steps[:test_index]
    assert any(step.get('uses', '').startswith('actions/setup-node@')
               and step.get('with', {}).get('node-version') == '24' for step in prerequisites)
    assert any(step.get('working-directory') == 'frontend'
               and 'npm ci --omit=dev --ignore-scripts' in step.get('run', '')
               for step in prerequisites)
    assert any(step.get('working-directory') == 'backend/document-renderer'
               and 'npm ci --omit=dev --ignore-scripts' in step.get('run', '')
               for step in prerequisites)


def test_static_deployment_ci_supplies_explicit_non_runtime_image_fixture():
    import yaml

    workflow = yaml.safe_load((REPOSITORY_ROOT / '.github/workflows/release-quality.yml').read_text())
    job = workflow['jobs']['deployment-static']
    assert job['env']['POSTGIS_IMAGE'] == 'aicommander-postgis-vector@sha256:' + '0' * 64
    checks = [step['run'] for step in job['steps'] if 'run' in step]
    assert all('config --quiet' in command for command in checks if command.startswith('docker compose'))
    assert any('sh -n scripts/check-postgres-image.sh' in command for command in checks)
