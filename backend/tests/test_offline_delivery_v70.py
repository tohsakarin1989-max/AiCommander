"""Transport, selected-capability and non-mutating deployment regressions."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("delivery_checker", ROOT / "scripts/verify-offline-delivery.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
VERSION = "7.0.0-stable"
IMAGE_ID = "sha256:" + "a" * 64


def artifact(root, role, value=b"synthetic resource only"):
    path = root / role
    path.write_bytes(value)
    return {"role": role, "path": path.name, "version": "synthetic-1",
            "sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}


@pytest.fixture
def delivery(tmp_path):
    return {"schema_version": 1, "purpose": "delivery", "application_version": VERSION,
            "platform": "linux/amd64", "capabilities": ["core"],
            "artifacts": [artifact(tmp_path, role) for role in checker.DELIVERY_ROLES["core"]],
            "images": [{"service": service, "reference": f"synthetic/{service}:test",
                        "version": VERSION, "platform": "linux/amd64", "image_id": IMAGE_ID}
                       for service in checker.BASE_SERVICES]}


def verify(data, root, **kwargs):
    return checker.verify(data, root, version=VERSION, **kwargs)


def test_file_inventory_does_not_claim_runtime_or_restoration(delivery, tmp_path, monkeypatch):
    monkeypatch.setattr(checker, "docker", lambda _: pytest.fail("file check must not start Docker"))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = verify(delivery, tmp_path)
    assert result["status"] == "inventory_verified"
    assert not result["restore_exercised"] and not result["target_deployment_verified"]
    assert not result["local_images_checked"] and not result["runtime_dependencies_probed"]
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


@pytest.mark.parametrize("change", ["missing", "hash", "length", "escape", "symlink", "version", "architecture"])
def test_invalid_delivery_is_rejected(delivery, tmp_path, change):
    first = delivery["artifacts"][0]
    if change == "missing":
        (tmp_path / first["path"]).unlink()
    elif change == "hash":
        first["sha256"] = "b" * 64
    elif change == "length":
        first["bytes"] += 1
    elif change == "escape":
        first["path"] = "../outside"
    elif change == "symlink":
        (tmp_path / "link").symlink_to(tmp_path / first["path"])
        first["path"] = "link"
    elif change == "version":
        delivery["application_version"] = "6.5.0-stable"
    else:
        delivery["images"][0]["platform"] = "linux/arm64"
    with pytest.raises(checker.Invalid):
        verify(delivery, tmp_path)


def test_maps_missing_fonts_and_index_cannot_pass(delivery, tmp_path):
    delivery["capabilities"].append("maps")
    with pytest.raises(checker.Invalid, match="map_fonts.*place_index"):
        verify(delivery, tmp_path)
    for role in checker.DELIVERY_ROLES["maps"]:
        delivery["artifacts"].append(artifact(tmp_path, role))
    assert verify(delivery, tmp_path)["artifacts_verified"] == 9


def test_only_selected_worker_images_are_required(delivery, tmp_path):
    assert verify(delivery, tmp_path)
    delivery["capabilities"].append("map_build")
    with pytest.raises(checker.Invalid, match="Worker"):
        verify(delivery, tmp_path)


def test_compose_cannot_substitute_unapproved_images(delivery, tmp_path):
    with pytest.raises(checker.Invalid, match="Compose"):
        verify(delivery, tmp_path, compose_config={"services": {"backend": {"image": "unapproved:tag"}}})
    with pytest.raises(checker.Invalid, match="选择的能力"):
        verify(delivery, tmp_path, required_capabilities=["documents"])


def test_local_image_mismatch_and_runtime_probe_boundary(delivery, tmp_path, monkeypatch):
    calls = []

    def docker(arguments):
        calls.append(arguments)
        return json.dumps([{"Id": IMAGE_ID, "Os": "linux", "Architecture": "amd64"}])

    monkeypatch.setattr(checker, "docker", docker)
    delivery["capabilities"].append("documents")
    result = verify(delivery, tmp_path, check_local=True, probe_runtime=True)
    assert result["runtime_dependencies_probed"] is True
    run = next(args for args in calls if args[0] == "run")
    assert "--pull=never" in run and "--read-only" in run
    assert run[run.index("--network") + 1] == "none"
    assert "--volume" not in run and "-v" not in run
    assert "soffice" in run[-1] and "headless_shell" in run[-1]
    monkeypatch.setattr(checker, "docker", lambda _: json.dumps([{"Id": "different", "Os": "linux", "Architecture": "amd64"}]))
    with pytest.raises(checker.Invalid, match="ID"):
        verify(delivery, tmp_path, check_local=True)


@pytest.fixture
def recovery(tmp_path):
    db_meta = f"format=postgres-custom\napplication_version={VERSION}\ndatabase_revision=v70test\n".encode()
    return {"schema_version": 1, "purpose": "recovery", "application_version": VERSION,
            "platform": "linux/amd64", "capabilities": ["core"], "database_revision": "v70test",
            "capture": {"writers_paused": True, "checkpoint_id": "synthetic-window"},
            "configuration_encrypted": True,
            "secret_escrow": {"separate": True, "receipt_id": "vault-receipt-not-secret",
                              "last_verified_at": "2026-09-30T00:00:00Z"},
            "artifacts": [artifact(tmp_path, "database_dump", b"PGDMPsynthetic-not-real-dump"),
                          artifact(tmp_path, "database_manifest", db_meta),
                          artifact(tmp_path, "configuration_archive", b"synthetic-ciphertext"),
                          artifact(tmp_path, "originals_inventory", json.dumps({
                              "database_storage": "evidence_objects.content", "external_status": "none_recorded"
                          }).encode())]}


def test_database_only_is_not_a_complete_recovery(recovery, tmp_path):
    recovery["artifacts"] = recovery["artifacts"][:2]
    with pytest.raises(checker.Invalid, match="configuration_archive.*originals_inventory"):
        verify(recovery, tmp_path)


def test_recovery_inventory_is_not_deployment_acceptance(recovery, tmp_path):
    assert verify(recovery, tmp_path)["restore_exercised"] is False
    with pytest.raises(checker.Invalid, match="不能替代"):
        verify(recovery, tmp_path, check_local=True)


@pytest.mark.parametrize("field", ["capture", "secret_escrow", "configuration_encrypted", "database_revision"])
def test_recovery_needs_consistent_checkpoint_and_separate_secrets(recovery, tmp_path, field):
    recovery.pop(field)
    with pytest.raises(checker.Invalid):
        verify(recovery, tmp_path)


def test_recovery_maps_need_safe_archive_not_database_only(recovery, tmp_path):
    recovery["capabilities"].append("maps")
    with pytest.raises(checker.Invalid, match="map_files"):
        verify(recovery, tmp_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        item = tarfile.TarInfo("../unsafe")
        item.size = 1
        archive.addfile(item, io.BytesIO(b"x"))
    recovery["artifacts"] += [artifact(tmp_path, "map_files", buffer.getvalue()), artifact(tmp_path, "map_inventory")]
    with pytest.raises(checker.Invalid, match="越界"):
        verify(recovery, tmp_path)
    assert not (tmp_path.parent / "unsafe").exists()


def test_record_is_candidate_inventory_not_validation(delivery, tmp_path):
    for item in delivery["artifacts"]:
        item.update(sha256="", bytes=0)
    manifest = tmp_path / "input.json"
    manifest.write_text(json.dumps(delivery))
    result = subprocess.run(["python3", str(ROOT / "scripts/verify-offline-delivery.py"), str(manifest),
                             "--root", str(tmp_path), "--version", VERSION, "--record"],
                            capture_output=True, text=True, check=True)
    candidate = json.loads(result.stdout)
    assert candidate["artifacts"][0]["bytes"] > 0
    assert "status" not in candidate and "inventory_verified" not in result.stdout
    assert manifest.read_text() == json.dumps(delivery)


@pytest.mark.parametrize("major", [5, 6, 7, 10])
def test_every_new_major_requires_both_database_extensions(tmp_path, major):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    fake = fake_bin / "docker"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                    'if [ "$1" = run ]; then exit 1; fi\nexit 0\n')
    fake.chmod(0o700)
    version = f"{major}.0.0-stable"
    version_file = tmp_path / "VERSION"
    version_file.write_text(version)
    config = tmp_path / "env"
    config.write_text(f"APP_DOMAIN=synthetic.internal\nAPP_PORT=3000\nAPP_VERSION={version}\n"
                      f"ALEMBIC_TARGET=head\nPOSTGIS_IMAGE={IMAGE_ID}\nDEPLOY_IMAGE_MODE=build\n")
    config.chmod(0o600)
    result = subprocess.run(["sh", str(ROOT / "scripts/preflight-production.sh")],
                            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                                 "ENV_FILE": str(config), "VERSION_FILE": str(version_file),
                                 "COMMAND_LOG": str(calls)}, capture_output=True, text=True)
    assert result.returncode != 0
    assert "不满足离线迁移条件" in result.stderr
    assert "vector.control" in calls.read_text()


def test_prebuilt_wrappers_never_pull_or_build_and_documents_are_selected(tmp_path):
    config = tmp_path / "env"
    config.write_text("DEPLOY_IMAGE_MODE=prebuilt\nENABLE_DOCUMENT_EXPORT=true\nENABLE_MAP_BUILD=false\n")
    shell = '. "$ROOT_DIR/scripts/production-compose.sh"; docker() { printf "%s\\n" "$@"; }; '
    env = {**os.environ, "ROOT_DIR": str(ROOT), "ENV_FILE": str(config), "COMPOSE_FILE": "base.yml"}
    for command in ("compose_run --rm --no-deps backend true", "compose_start -d --wait"):
        result = subprocess.run(["sh", "-c", shell + command], env=env, capture_output=True, text=True, check=True)
        args = result.stdout.splitlines()
        assert str(ROOT / "docker-compose.document-renderer.yml") in args
        assert args[args.index("--pull") + 1] == "never"
        if "up" in args:
            assert "--no-build" in args
    services = subprocess.run(["sh", "-c", shell + "production_services"], env=env,
                              capture_output=True, text=True, check=True).stdout.splitlines()
    assert set(services) == checker.BASE_SERVICES


@pytest.mark.parametrize("with_manifest,matching", [(False, True), (True, False), (True, True)])
def test_v7_prebuilt_preflight_checks_approved_manifest_before_business_changes(
        delivery, tmp_path, with_manifest, matching):
    """Execute the real preflight, only Docker is an isolated command recorder."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    fake = fake_bin / "docker"
    fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['COMMAND_LOG']).open('a') as out:
    out.write(' '.join(args) + '\\n')
if args[0] == 'version':
    print('linux/amd64')
elif args[:2] == ['image', 'inspect']:
    print(json.dumps([{'Id': os.environ['TEST_IMAGE_ID'], 'Os': 'linux', 'Architecture': 'amd64'}]))
elif '--format' in args and 'json' in args:
    print(json.dumps({'services': {s: {'image': 'synthetic/' + s + ':test'}
        for s in ['postgres','redis','backend','celery','celery-beat','frontend']}}))
''')
    fake.chmod(0o700)
    secrets = tmp_path / "synthetic-secrets"
    secrets.mkdir(mode=0o700)
    for index, name in enumerate(("db_password", "redis_password", "secret_key", "bootstrap_token")):
        secret = secrets / name
        secret.write_text(str(index) * 64)
        secret.chmod(0o600)
    version_file = tmp_path / "VERSION"
    version_file.write_text(VERSION)
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps(delivery))
    config = tmp_path / "env"
    config.write_text(f"APP_DOMAIN=synthetic.internal\nAPP_PORT=3000\nAPP_VERSION={VERSION}\n"
                      f"ALEMBIC_TARGET=head\nPOSTGIS_IMAGE={IMAGE_ID}\nDEPLOY_IMAGE_MODE=prebuilt\n"
                      f"SECRETS_DIR={secrets}\n" +
                      (f"OFFLINE_DELIVERY_MANIFEST={approved}\nOFFLINE_DELIVERY_ROOT={tmp_path}\n"
                       if with_manifest else ""))
    config.chmod(0o600)
    result = subprocess.run(["sh", str(ROOT / "scripts/preflight-production.sh")],
                            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                                 "ENV_FILE": str(config), "VERSION_FILE": str(version_file),
                                 "TEST_IMAGE_ID": IMAGE_ID if matching else "sha256:" + "b" * 64,
                                 "COMMAND_LOG": str(calls)}, capture_output=True, text=True)
    assert (result.returncode == 0) == (with_manifest and matching), result.stderr
    commands = calls.read_text()
    assert "alembic" not in commands and " up " not in commands and "pg_dump" not in commands
    assert "pull " not in commands and "build " not in commands
    assert str(0) * 64 not in result.stdout + result.stderr
    if with_manifest:
        assert "config --format json postgres redis backend celery celery-beat frontend" in commands
    else:
        assert "OFFLINE_DELIVERY_MANIFEST" in result.stderr


def test_road_build_does_not_pin_an_obsolete_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    for name in ("Dockerfile", "Dockerfile.cached"):
        body = (ROOT / "deploy/road-api" / name).read_text()
        assert "get_current_head() ==" not in body
        assert "len(migrations.get_heads()) == 1" in body
    configuration = Config(str(ROOT / "backend/alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    migrations = ScriptDirectory.from_config(configuration)
    assert len(migrations.get_heads()) == 1
    assert migrations.get_revision("b508c42fd75b") is not None
    assert migrations.get_revision("v65r01") is not None


@pytest.mark.parametrize("documents,roads,map_build", [(False, False, False), (True, False, False), (True, True, True)])
@pytest.mark.parametrize("stale_exports", [False, True])
def test_real_compose_parser_selects_exact_runtime_without_daemon(tmp_path, documents, roads, map_build, stale_exports):
    """Uses the installed Compose parser only: no pull, run, database or secrets."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI not installed; parser evidence unavailable")
    config = tmp_path / "synthetic.env"
    config.write_text(f"APP_DOMAIN=synthetic.internal\nAPP_VERSION={VERSION}\nPOSTGIS_IMAGE={IMAGE_ID}\n"
                      f"ENABLE_DOCUMENT_EXPORT={str(documents).lower()}\n"
                      f"ENABLE_ROAD_ANALYSIS={str(roads).lower()}\n"
                      "CASE_DRAFT_RETENTION_DAYS=14\n"
                      f"ENABLE_MAP_BUILD={str(map_build).lower()}\n")
    environment = {"PATH": os.environ["PATH"], "ROOT_DIR": str(ROOT),
                   "ENV_FILE": str(config), "COMPOSE_FILE": str(ROOT / "docker-compose.production.yml")}
    prefix = "aicommander"
    if stale_exports:
        prefix = "approved-local-prefix"
        environment.update(APP_VERSION="5.2.0-stable", POSTGIS_IMAGE="old/unapproved:tag",
                           IMAGE_PREFIX=prefix)
    result = subprocess.run(["sh", "-c", '. "$ROOT_DIR/scripts/production-compose.sh"; '
                              'services="$(production_services)"; compose config --format json $services'],
                            env=environment,
                            capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    services = data["services"]
    expected = checker.BASE_SERVICES | ({"road-worker"} if roads else set()) | ({"map-worker"} if map_build else set())
    assert services.keys() == expected
    suffix = "-roads" if roads else "-documents" if documents else ""
    assert services["backend"]["image"] == f"{prefix}-backend{suffix}:{VERSION}"
    assert services["celery"]["image"] == f"{prefix}-backend{'-roads' if roads else ''}:{VERSION}"
    assert services["frontend"]["image"] == f"{prefix}-frontend:{VERSION}"
    for service in services.keys() - {"postgres", "redis", "frontend"}:
        assert services[service]["environment"]["APP_VERSION"] == VERSION
        assert services[service]["environment"]["CASE_DRAFT_RETENTION_DAYS"] == "14"
    assert services["postgres"]["image"] == IMAGE_ID
    if documents and not roads:
        assert services["backend"]["build"]["target"] == "document-renderer"
        assert services["celery"]["build"]["target"] == "runtime"
        assert services["celery"]["build"]["context"] == str(ROOT / "backend")
        assert services["celery-beat"]["image"] == services["celery"]["image"]
        assert "build" not in services["celery-beat"]
    elif roads:
        assert services["backend"]["build"]["target"] == "road-api"
        assert "build" not in services["celery"]


def test_real_compose_capabilities_ignore_conflicting_exports_and_preserve_omitted_defaults(tmp_path):
    """Profile, API/Worker flags and frontend build flag use the same source."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI not installed; parser evidence unavailable")
    flag_names = ("ENABLE_ROAD_ANALYSIS", "ENABLE_AGENT_LAB", "ENABLE_INTELLIGENT_QUERY")
    for values in (("false", "false", "false"), ("true", "false", "true"),
                   ("false", "true", "false"), (None, None, None)):
        config = tmp_path / "capabilities.env"
        config.write_text(f"APP_DOMAIN=synthetic.internal\nAPP_VERSION={VERSION}\nPOSTGIS_IMAGE={IMAGE_ID}\n" +
                          "".join(f"{name}={value}\n" for name, value in zip(flag_names, values)
                                  if value is not None))
        environment = {"PATH": os.environ["PATH"], "ROOT_DIR": str(ROOT), "ENV_FILE": str(config),
                       "COMPOSE_FILE": str(ROOT / "docker-compose.production.yml"),
                       **{name: "false" if value == "true" else "true"
                          for name, value in zip(flag_names, values)}}
        result = subprocess.run(["sh", "-c", '. "$ROOT_DIR/scripts/production-compose.sh"; '
                                  'services="$(production_services)"; compose config --format json $services'],
                                env=environment, capture_output=True, text=True, check=True)
        services = json.loads(result.stdout)["services"]
        roads, agents, queries = values
        expected = checker.BASE_SERVICES | ({"road-worker"} if roads == "true" else set())
        expected |= {"agent-worker"} if agents == "true" or queries == "true" else set()
        assert services.keys() == expected
        assert services["backend"]["image"] == f"aicommander-backend{'-roads' if roads == 'true' else ''}:{VERSION}"
        for service in expected - {"postgres", "redis", "frontend"}:
            assert services[service]["environment"]["ENABLE_AGENT_LAB"] == (agents or "false")
            assert services[service]["environment"]["ENABLE_INTELLIGENT_QUERY"] == (queries or "")
        assert services["frontend"]["build"]["args"]["VITE_ENABLE_AGENT_LAB"] == (agents or "false")


def test_deployment_uses_same_configured_release_after_preflight_with_stale_exports(delivery, tmp_path):
    """Real deployment scripts; only Docker/curl are synthetic recorders."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.jsonl"
    fake = fake_bin / "docker"
    fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['COMMAND_LOG']).open('a') as out:
    out.write(json.dumps({'args': args, 'version': os.environ.get('APP_VERSION'),
                         'database_image': os.environ.get('POSTGIS_IMAGE')}) + '\\n')
services = ['postgres', 'redis', 'backend', 'celery', 'celery-beat', 'frontend']
images = {s: ('synthetic/' + s + ':' + os.environ.get('APP_VERSION', 'missing')) for s in services}
images['postgres'] = os.environ.get('POSTGIS_IMAGE', 'missing')
if args[0] == 'version':
    print('linux/amd64')
elif args[:2] == ['image', 'inspect']:
    print(json.dumps([{'Id': os.environ['TEST_IMAGE_ID'], 'Os': 'linux', 'Architecture': 'amd64'}]))
elif '--format' in args and 'json' in args:
    print(json.dumps({'services': {s: {'image': images[s]} for s in services}}))
elif '--images' in args:
    print('\\n'.join(images.values()))
elif any('pg_dump' in item for item in args):
    print('PGDMPsynthetic-command-recorder-only')
elif any('SELECT version_num' in item for item in args):
    print('v70s01')
''')
    fake.chmod(0o700)
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    curl.chmod(0o700)
    secrets = tmp_path / "synthetic-secrets"
    secrets.mkdir(mode=0o700)
    for index, name in enumerate(("db_password", "redis_password", "secret_key", "bootstrap_token")):
        secret = secrets / name
        secret.write_text(str(index) * 64)
        secret.chmod(0o600)
    for item in delivery["images"]:
        item["reference"] = (IMAGE_ID if item["service"] == "postgres"
                             else f"synthetic/{item['service']}:{VERSION}")
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps(delivery))
    version_file = tmp_path / "VERSION"
    version_file.write_text(VERSION)
    config = tmp_path / "synthetic.env"
    config.write_text(f"APP_DOMAIN=synthetic.internal\nAPP_PORT=3000\nAPP_VERSION={VERSION}\n"
                      f"ALEMBIC_TARGET=head\nPOSTGIS_IMAGE={IMAGE_ID}\nDEPLOY_IMAGE_MODE=prebuilt\n"
                      f"SECRETS_DIR={secrets}\nBACKUP_DIR={tmp_path / 'backups'}\n"
                      f"OFFLINE_DELIVERY_MANIFEST={approved}\nOFFLINE_DELIVERY_ROOT={tmp_path}\n")
    config.chmod(0o600)
    result = subprocess.run(["sh", str(ROOT / "scripts/deploy-production.sh")],
                            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
                                 "ENV_FILE": str(config), "VERSION_FILE": str(version_file),
                                 "COMMAND_LOG": str(calls), "TEST_IMAGE_ID": IMAGE_ID,
                                 "APP_VERSION": "5.2.0-stable", "POSTGIS_IMAGE": "old/unapproved:tag"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    compose_calls = [row for row in commands if row['args'][0] == 'compose' and '--env-file' in row['args']]
    assert compose_calls and all(row['version'] == VERSION and row['database_image'] == IMAGE_ID
                                 for row in compose_calls)
    assert any('alembic' in row['args'] for row in compose_calls)
    assert any(any('pg_dump' in argument for argument in row['args']) for row in compose_calls)
    assert any('up' in row['args'] for row in compose_calls)
    for row in compose_calls:
        assert 'build' not in row['args']
        if 'up' in row['args'] or 'run' in row['args']:
            assert row['args'][row['args'].index('--pull') + 1] == 'never'
    assert str(0) * 64 not in result.stdout + result.stderr
