import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def test_deployment_scripts_support_isolated_configuration():
    deploy = _read("scripts/deploy-production.sh")
    init = _read("scripts/init-production.sh")
    compose = _read("docker-compose.production.yml")

    assert 'COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"' in deploy
    assert 'ENV_FILE="${ENV_FILE:-.env.production}"' in deploy
    assert 'COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" sh ./scripts/' in deploy
    assert 'ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"' in init
    assert "$ENV_FILE，" not in init
    assert 'APP_VERSION: "${APP_VERSION:-2.3.0-stable}"' in compose
    assert '${IMAGE_PREFIX:-aicommander}-backend:' in compose
    assert '${IMAGE_PREFIX:-aicommander}-frontend:' in compose
    assert "AICommander v2.0.0" not in deploy


def test_release_rehearsal_has_smoke_restore_and_cleanup_guardrails():
    rehearsal = _read("scripts/rehearse-release.sh")
    smoke = _read("scripts/verify-test-deployment.sh")
    restore = _read("scripts/verify-backup-restore.sh")

    assert "aicommander_release_rehearsal_" in rehearsal
    assert 'COMPOSE_PROJECT_NAME' in rehearsal
    assert 'REHEARSAL_IMAGE_PREFIX' in rehearsal
    assert 'ENABLE_AGENT_LAB=false' in rehearsal
    assert 'AGENT_MODE=off' in rehearsal
    assert 'AGENT_MUTATIONS_ENABLED=false' in rehearsal
    assert 'AGENT_PROVIDER=deterministic' in rehearsal
    assert "'AGENT_MODEL='" in rehearsal
    assert "'AGENT_MAP_PILOT_MAX_ASSETS=100'" in rehearsal
    assert "'AGENT_CASE_PILOT_MAX_CASES=30'" in rehearsal
    assert 'verify-test-deployment.sh' in rehearsal
    assert 'verify-backup-restore.sh' in rehearsal
    assert 'down -v --remove-orphans' in rehearsal
    assert 'network-exposure.manifest' in rehearsal
    assert 'agent_worker=absent' in rehearsal
    assert '.HostConfig.PortBindings' in rehearsal

    for endpoint in (
        "/health/live",
        "/health/ready",
        "/health/agents",
        "/api/cases",
        "/docs",
        "/redoc",
        "/openapi.json",
    ):
        assert endpoint in smoke
    assert "overall=passed" in smoke
    assert "AGENT_MODE" in smoke

    assert "aicommander_restore_check_" in restore
    assert "sha256" in restore
    assert "pg_restore" in restore
    assert "dropdb" in restore
    assert "restore_status=passed" in restore


def test_release_quality_gate_checks_rehearsal_scripts():
    workflow = _read(".github/workflows/release-quality.yml")

    assert "python -m pip_audit -r requirements.txt" in workflow
    assert "npm ci --audit=false" in workflow
    assert "npm audit --offline --omit=dev --audit-level=high" in workflow
    assert "npm audit --omit=dev --audit-level=high" in workflow
    assert "timeout-minutes: 2" in workflow
    assert "continue-on-error: true" in workflow
    assert "sh -n scripts/verify-test-deployment.sh" in workflow
    assert "sh -n scripts/verify-backup-restore.sh" in workflow
    assert "sh -n scripts/rehearse-release.sh" in workflow


def test_smoke_verifier_records_evidence_without_credentials(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env python3
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

args = sys.argv[1:]
headers_file = Path(args[args.index('-D') + 1])
body_file = Path(args[args.index('-o') + 1])
path = urlparse(args[-1]).path
payloads = {
    '/health/live': {'status': 'alive', 'version': '2.3.0-stable', 'dependencies': {}},
    '/health/ready': {
        'status': 'ready',
        'version': '2.3.0-stable',
        'dependencies': {
            'database': {'status': 'ok'},
            'schema': {'status': 'ok'},
            'redis': {'status': 'ok'},
        },
    },
    '/health/agents': {
        'status': 'off',
        'version': '2.3.0-stable',
        'mode': 'off',
        'affects_core_readiness': False,
    },
}
if path == '/':
    status, body = 200, '<html>ok</html>'
elif path in payloads:
    status, body = 200, json.dumps(payloads[path], separators=(',', ':'))
elif path == '/api/cases':
    status, body = 401, '{"detail":"unauthorized"}'
else:
    status, body = 404, '{"detail":"not found"}'
headers_file.write_text(
    f'HTTP/1.1 {status} test\\n'
    'X-Content-Type-Options: nosniff\\n'
    'X-Frame-Options: DENY\\n'
    'Referrer-Policy: no-referrer\\n'
    'Permissions-Policy: camera=(), microphone=(), geolocation=()\\n'
    'Strict-Transport-Security: max-age=31536000; includeSubDomains\\n'
    "Content-Security-Policy: default-src 'self'; object-src 'none'\\n",
    encoding='utf-8',
)
body_file.write_text(body, encoding='utf-8')
sys.stdout.write(str(status))
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o700)
    env_file = tmp_path / ".env.production"
    env_file.write_text(
        "\n".join(
            (
                "APP_PORT=3000",
                "APP_VERSION=2.3.0-stable",
                "ENABLE_AGENT_LAB=false",
                "AGENT_MODE=off",
                "AGENT_MUTATIONS_ENABLED=false",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_dir = tmp_path / "evidence"
    env = os.environ.copy()
    env.update(
        {
            "ENV_FILE": str(env_file),
            "BASE_URL": "http://127.0.0.1:39876",
            "EVIDENCE_DIR": str(evidence_dir),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["sh", str(REPOSITORY_ROOT / "scripts/verify-test-deployment.sh")],
        cwd=REPOSITORY_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    manifest = (evidence_dir / "verification.manifest").read_text(encoding="utf-8")
    assert "application_version=2.3.0-stable" in manifest
    assert "agent_mode=off" in manifest
    assert "overall=passed" in manifest
