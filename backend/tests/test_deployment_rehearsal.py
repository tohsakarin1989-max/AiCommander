import hashlib
import os
import subprocess
from pathlib import Path

import pytest


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
    version = _read("VERSION").strip()
    assert f'APP_VERSION: "${{APP_VERSION:-{version}}}"' in compose
    assert '${IMAGE_PREFIX:-aicommander}-backend:' in compose
    assert '${IMAGE_PREFIX:-aicommander}-frontend:' in compose
    assert "      - edge" in compose
    assert "  edge:\n    driver: bridge" in compose
    assert "AICommander v2.0.0" not in deploy


def test_release_rehearsal_has_smoke_restore_and_cleanup_guardrails():
    rehearsal = _read("scripts/rehearse-release.sh")
    smoke = _read("scripts/verify-test-deployment.sh")
    backup = _read("scripts/backup-production.sh")
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
    assert "'AGENT_DUAL_DOMAIN_PILOT_MAX_CASES=10'" in rehearsal
    assert "'AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS=100'" in rehearsal
    assert 'verify-test-deployment.sh' in rehearsal
    assert 'verify-backup-restore.sh' in rehearsal
    assert 'down -v --remove-orphans' in rehearsal
    assert 'network-exposure.manifest' in rehearsal
    assert 'agent_worker=absent' in rehearsal
    assert '.HostConfig.PortBindings' in rehearsal
    assert 'DATABASE_NAME="$(read_env DB_NAME)"' in backup
    assert 'sh "$DATABASE_NAME"' in backup
    assert "-d aicommander" not in backup

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
    assert "sh -n scripts/verify-v36-postgis.sh" in workflow
    assert "sh -n scripts/verify-v36-offline-map.sh" in workflow
    assert "sh -n scripts/rehearse-release.sh" in workflow
    assert "sh -n scripts/verify-evidence-graph.sh" in workflow
    assert "sh -n scripts/verify-situation.sh" in workflow

    agent_gate = _read("scripts/verify-agent-lab.sh")
    assert "tests/test_dual_domain_pilot.py" in agent_gate
    assert "src/pages/Agents/dualDomainPresentation.test.ts" in agent_gate

    workbench_gate = _read("scripts/verify-workbench.sh")
    assert "tests/test_workbench.py" in workbench_gate
    assert "src/pages/Workbench/workbenchPresentation.test.ts" in workbench_gate
    required_tables = {
        "knowledge-assets": {"knowledge_assets", "knowledge_reuse_records", "workbench_task_sessions"},
        "workbench": {"workbench_task_sessions"},
        "evidence-graph": {"cases", "case_evidence", "chain_links", "jurisdiction_assets",
                           "agent_runs", "agent_artifacts", "knowledge_assets"},
        "situation": {"cases", "jurisdiction_assets", "chain_links", "knowledge_assets"},
    }
    for module, tables in required_tables.items():
        gate = _read(f"scripts/verify-{module}.sh")
        invocation = '"$PYTHON" "$ROOT_DIR/scripts/verify-sqlite-schema.py" "$VERIFY_DB" \\\n'
        assert invocation in gate
        assert set(gate.split(invocation, 1)[1].splitlines()[0].split()) == tables
        assert "a7d9e1f2b304" not in gate


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
    '/health/live': {'status': 'alive', 'version': '3.0.0-stable', 'dependencies': {}},
    '/health/ready': {
        'status': 'ready',
        'version': '3.0.0-stable',
        'dependencies': {
            'database': {'status': 'ok'},
            'schema': {'status': 'ok'},
            'redis': {'status': 'ok'},
        },
    },
    '/health/agents': {
        'status': 'off',
        'version': '3.0.0-stable',
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
                "APP_VERSION=3.0.0-stable",
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
    assert "application_version=3.0.0-stable" in manifest
    assert "agent_mode=off" in manifest
    assert "overall=passed" in manifest


def _run_restore_verifier(tmp_path, *, manifest_revision="revision_test", restored_revision="revision_test",
                          table_count="42", revision_query_exit="0", with_manifest=True):
    """Run the real shell verifier against an isolated, non-networked Docker stub."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path
args = ' '.join(sys.argv[1:])
with Path(os.environ['RESTORE_COMMAND_LOG']).open('a') as log:
    log.write(args + '\\n')
if 'information_schema.tables' in args:
    print(os.environ['RESTORED_TABLE_COUNT'])
elif 'SELECT version_num FROM alembic_version' in args:
    print(os.environ['RESTORED_REVISION'])
    sys.exit(int(os.environ['REVISION_QUERY_EXIT']))
elif 'pg_restore ' in args:
    sys.stdin.buffer.read()
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    backup = tmp_path / "aicommander-test.dump"
    backup.write_bytes(b"isolated restore verification fixture")
    backup.with_suffix(".dump.sha256").write_text(
        hashlib.sha256(backup.read_bytes()).hexdigest() + f"  {backup.name}\n"
    )
    if with_manifest:
        backup.with_suffix(".dump.manifest").write_text(
            f"database_name=aicommander\ndatabase_revision={manifest_revision}\nformat=postgres-custom\n",
            encoding="utf-8",
        )
    env_file = tmp_path / ".env.production"
    env_file.write_text(f"BACKUP_DIR={tmp_path}\n", encoding="utf-8")
    command_log = tmp_path / "docker-commands.log"
    evidence = tmp_path / "restore-verified"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "ENV_FILE": str(env_file), "BACKUP_FILE": str(backup), "EVIDENCE_FILE": str(evidence),
        "RESTORE_COMMAND_LOG": str(command_log), "RESTORED_TABLE_COUNT": table_count,
        "RESTORED_REVISION": restored_revision, "REVISION_QUERY_EXIT": revision_query_exit,
    }
    result = subprocess.run(
        ["sh", str(REPOSITORY_ROOT / "scripts/verify-backup-restore.sh")],
        cwd=REPOSITORY_ROOT, env=env, capture_output=True, text=True, check=False,
    )
    return result, evidence, command_log


@pytest.mark.parametrize("overrides", [
    {"with_manifest": False},
    {"table_count": "0"},
    {"revision_query_exit": "1"},
    {"restored_revision": ""},
    {"manifest_revision": "untracked", "restored_revision": "untracked"},
    {"restored_revision": "other_revision"},
])
def test_restore_verifier_rejects_incomplete_or_unmatched_backups(tmp_path, overrides):
    result, evidence, commands = _run_restore_verifier(tmp_path, **overrides)
    assert result.returncode != 0, "incomplete restoration must never be marked passed"
    assert not evidence.exists()
    if commands.exists() and "createdb" in commands.read_text():
        assert "dropdb" in commands.read_text(), "temporary restore database must be cleaned up on failure"


def test_restore_verifier_requires_manifest_revision_and_records_verified_result(tmp_path):
    result, evidence, commands = _run_restore_verifier(tmp_path)
    assert result.returncode == 0, result.stderr
    text = evidence.read_text()
    assert "restored_table_count=42" in text
    assert "database_revision=revision_test" in text
    assert "expected_database_revision=revision_test" in text
    assert "restore_status=passed" in text
    assert "dropdb" in commands.read_text()


def test_disaster_recovery_stops_all_application_writers():
    runbook = _read("docs/server-deployment-runbook.zh-CN.md")
    recovery = runbook.split("### 17.3 灾难恢复", 1)[1].split("## 18.", 1)[0]
    assert "stop frontend backend celery celery-beat agent-worker road-worker map-worker" in recovery
