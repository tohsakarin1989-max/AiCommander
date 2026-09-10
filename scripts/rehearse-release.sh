#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

REPOSITORY_VERSION="$(tr -d '\r\n' < VERSION)"
APP_VERSION="${REHEARSAL_APP_VERSION:-$REPOSITORY_VERSION}"
[ -n "$APP_VERSION" ] || {
    echo "VERSION 不能为空" >&2
    exit 1
}
case "$APP_VERSION" in
    *[!a-zA-Z0-9._-]*)
        echo "VERSION 含有不安全字符: $APP_VERSION" >&2
        exit 1
        ;;
esac

TMP_ROOT="${TMPDIR:-/tmp}"
WORK_DIR="$(mktemp -d "$TMP_ROOT/aicommander-release.XXXXXX")"
timestamp="$(date '+%Y%m%d-%H%M%S')"
EVIDENCE_DIR="${EVIDENCE_DIR:-$TMP_ROOT/aicommander-release-evidence-${timestamp}-$$}"
ENV_FILE="$WORK_DIR/.env.production"
VERSION_FILE="$WORK_DIR/VERSION"
SECRETS_DIR="$WORK_DIR/secrets"
BACKUP_DIR="$WORK_DIR/backups"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.production.yml}"
COMPOSE_PROJECT_NAME="aicommander_release_rehearsal_$$"
REHEARSAL_IMAGE_PREFIX="aicommander-release-rehearsal-$$"
REHEARSAL_PORT="${REHEARSAL_PORT:-33080}"
export COMPOSE_PROJECT_NAME

case "$APP_VERSION" in
    3.0.0-stable)
        ALEMBIC_TARGET="a7d9e1f2b304"
        POSTGIS_IMAGE=""
        REQUIRE_V36_MAP_BUNDLE="false"
        ;;
    *)
        ALEMBIC_TARGET="head"
        POSTGIS_IMAGE="${REHEARSAL_POSTGIS_IMAGE:-}"
        REQUIRE_V36_MAP_BUNDLE="true"
        [ -n "$POSTGIS_IMAGE" ] || {
            echo "候选版本隔离演练必须通过 REHEARSAL_POSTGIS_IMAGE 指定带摘要的 PostGIS 镜像" >&2
            exit 1
        }
        [ -n "${MAP_BUNDLE_FILE:-}" ] || {
            echo "候选版本隔离演练必须通过 MAP_BUNDLE_FILE 指定真实离线地图包" >&2
            exit 1
        }
        ;;
esac
database_timestamp="$(date '+%Y%m%d_%H%M%S')"
DB_NAME="aicommander_v36_verify_${database_timestamp}_$$"

case "$COMPOSE_PROJECT_NAME" in
    aicommander_release_rehearsal_[0-9]*) ;;
    *) echo "隔离演练项目名不安全，已停止" >&2; exit 1 ;;
esac
case "$REHEARSAL_IMAGE_PREFIX" in
    aicommander-release-rehearsal-[0-9]*) ;;
    *) echo "隔离演练镜像前缀不安全，已停止" >&2; exit 1 ;;
esac

umask 077
mkdir -p "$EVIDENCE_DIR" "$BACKUP_DIR"
printf '%s\n' "$APP_VERSION" > "$VERSION_FILE"

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

fail() {
    echo "隔离部署演练失败: $*" >&2
    exit 1
}

require_unpublished() {
    service="$1"
    container_id="$(compose ps -q "$service")"
    [ -n "$container_id" ] || fail "找不到 $service 容器"
    port_bindings="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")"
    [ "$port_bindings" = '{}' ] \
        || fail "$service 不应发布任何端口到宿主机"
}

cleanup() {
    exit_status="$?"
    set +e
    compose ps --all > "$EVIDENCE_DIR/compose-ps-final.txt" 2>&1
    compose logs --no-color --tail=200 > "$EVIDENCE_DIR/container-logs-final.txt" 2>&1
    if [ "$exit_status" -eq 0 ]; then
        rehearsal_status=passed
    else
        rehearsal_status=failed
    fi
    printf '%s\n' \
        "finished_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "application_version=$APP_VERSION" \
        "source_revision=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
        "compose_project=$COMPOSE_PROJECT_NAME" \
        "agent_mode=off" \
        "rehearsal_status=$rehearsal_status" \
        > "$EVIDENCE_DIR/rehearsal.manifest"
    compose down -v --remove-orphans >/dev/null 2>&1
    docker image rm \
        "${REHEARSAL_IMAGE_PREFIX}-backend:${APP_VERSION}" \
        "${REHEARSAL_IMAGE_PREFIX}-frontend:${APP_VERSION}" \
        >/dev/null 2>&1 || true
    case "$WORK_DIR" in
        "$TMP_ROOT"/aicommander-release.*) rm -rf -- "$WORK_DIR" ;;
    esac
    echo "隔离演练证据目录: $EVIDENCE_DIR"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' \
    'APP_DOMAIN=aicommander-rehearsal.local' \
    "APP_PORT=$REHEARSAL_PORT" \
    "APP_VERSION=$APP_VERSION" \
    "ALEMBIC_TARGET=$ALEMBIC_TARGET" \
    "POSTGIS_IMAGE=$POSTGIS_IMAGE" \
    "DB_NAME=$DB_NAME" \
    "SECRETS_DIR=$SECRETS_DIR" \
    "BACKUP_DIR=$BACKUP_DIR" \
    "IMAGE_PREFIX=$REHEARSAL_IMAGE_PREFIX" \
    'ENABLE_BONUS_ACCOUNTING=false' \
    'ACCESS_TOKEN_EXPIRE_MINUTES=480' \
    'CELERY_CONCURRENCY=2' \
    'ENABLE_AGENT_LAB=false' \
    'AGENT_MODE=off' \
    'AGENT_MUTATIONS_ENABLED=false' \
    'AGENT_EXTERNAL_DATA_POLICY=redacted_only' \
    'AGENT_MAX_STEPS=8' \
    'AGENT_TIMEOUT_SECONDS=120' \
    'AGENT_REDIS_QUEUE=agent_lab' \
    'AGENT_PROVIDER=deterministic' \
    'AGENT_MODEL=' \
    'AGENT_MODEL_ID=' \
    'AGENT_MODEL_INPUT_COST_PER_MILLION_USD=0' \
    'AGENT_MODEL_OUTPUT_COST_PER_MILLION_USD=0' \
    'AGENT_USE_EXTERNAL_MODEL=false' \
    'AGENT_SDK_TRACING_ENABLED=false' \
    'AGENT_APPROVAL_TTL_HOURS=24' \
    'AGENT_MAP_PILOT_MAX_ASSETS=100' \
    'AGENT_CASE_PILOT_MAX_CASES=30' \
    'AGENT_DUAL_DOMAIN_PILOT_MAX_CASES=10' \
    'AGENT_DUAL_DOMAIN_PILOT_MAX_ASSETS=100' \
    > "$ENV_FILE"
chmod 0600 "$ENV_FILE"

ENV_FILE="$ENV_FILE" sh ./scripts/init-production.sh
COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" VERSION_FILE="$VERSION_FILE" \
    sh ./scripts/deploy-production.sh

require_unpublished backend
require_unpublished postgres
require_unpublished redis
frontend_id="$(compose ps -q frontend)"
[ -n "$frontend_id" ] || fail "找不到 frontend 容器"
frontend_bindings="$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$frontend_id")"
expected_frontend_bindings="{\"80/tcp\":[{\"HostIp\":\"127.0.0.1\",\"HostPort\":\"$REHEARSAL_PORT\"}]}"
[ "$frontend_bindings" = "$expected_frontend_bindings" ] \
    || fail "前端必须且只能绑定 127.0.0.1:${REHEARSAL_PORT}"
if compose ps --services --status running | grep -x 'agent-worker' >/dev/null; then
    fail "$APP_VERSION 稳定基线不应启动 Agent Worker"
fi
printf '%s\n' \
    "frontend_binding=127.0.0.1:$REHEARSAL_PORT" \
    'backend_port=unpublished' \
    'postgres_port=unpublished' \
    'redis_port=unpublished' \
    'agent_worker=absent' \
    > "$EVIDENCE_DIR/network-exposure.manifest"

if [ "$ALEMBIC_TARGET" = "head" ]; then
    COMPOSE_FILE="$COMPOSE_FILE" \
        ENV_FILE="$ENV_FILE" \
        EVIDENCE_FILE="$EVIDENCE_DIR/postgis-v36.json" \
        sh ./scripts/verify-v36-postgis.sh
fi

if [ "$REQUIRE_V36_MAP_BUNDLE" = "true" ]; then
    COMPOSE_FILE="$COMPOSE_FILE" \
        ENV_FILE="$ENV_FILE" \
        MAP_BUNDLE_FILE="$MAP_BUNDLE_FILE" \
        EVIDENCE_FILE="$EVIDENCE_DIR/offline-map-v36.json" \
        sh ./scripts/verify-v36-offline-map.sh
fi

BASE_URL="http://127.0.0.1:$REHEARSAL_PORT" \
    ENV_FILE="$ENV_FILE" \
    EVIDENCE_DIR="$EVIDENCE_DIR/smoke" \
    REQUIRE_OFFLINE_MAP_READY="$REQUIRE_V36_MAP_BUNDLE" \
    sh ./scripts/verify-test-deployment.sh

# 在隔离编排中真实停止 Redis，确认核心存活/就绪接口保持可用且只报告降级；
# 随后恢复 Redis，避免把“独立 Worker 会话恢复”误写成 Redis 故障演练。
redis_fault_body="$EVIDENCE_DIR/redis-outage-ready.body"
compose stop redis >/dev/null
redis_fault_status="$(curl -sS --connect-timeout 5 --max-time 30 \
    -o "$redis_fault_body" -w '%{http_code}' \
    "http://127.0.0.1:$REHEARSAL_PORT/health/ready")" \
    || fail "Redis 停止后核心就绪接口无法访问"
[ "$redis_fault_status" = "200" ] \
    || fail "Redis 停止后核心就绪接口返回 $redis_fault_status"
grep -F '"status":"degraded"' "$redis_fault_body" >/dev/null \
    || fail "Redis 停止后未报告 degraded"
grep -F '"redis":{"status":"down"' "$redis_fault_body" >/dev/null \
    || fail "Redis 停止后未报告 Redis down"
compose start redis >/dev/null
redis_recovered=false
attempt=0
while [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    if curl -fsS --connect-timeout 2 --max-time 5 \
        "http://127.0.0.1:$REHEARSAL_PORT/health/ready" \
        > "$EVIDENCE_DIR/redis-recovered-ready.body" 2>/dev/null \
        && grep -F '"status":"ready"' "$EVIDENCE_DIR/redis-recovered-ready.body" >/dev/null \
        && grep -F '"redis":{"status":"ok"' "$EVIDENCE_DIR/redis-recovered-ready.body" >/dev/null; then
        redis_recovered=true
        break
    fi
    sleep 1
done
[ "$redis_recovered" = "true" ] || fail "Redis 恢复后核心健康状态未恢复"
printf '%s\n' \
    'redis_outage_core_http_status=200' \
    'redis_outage_core_status=degraded' \
    'redis_recovery_status=ready' \
    'overall=passed' \
    > "$EVIDENCE_DIR/redis-fault-injection.manifest"

COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" sh ./scripts/backup-production.sh
BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/aicommander-*.dump | head -1)"
COMPOSE_FILE="$COMPOSE_FILE" \
    ENV_FILE="$ENV_FILE" \
    BACKUP_FILE="$BACKUP_FILE" \
    EVIDENCE_FILE="$EVIDENCE_DIR/backup-restore.manifest" \
    sh ./scripts/verify-backup-restore.sh

compose ps > "$EVIDENCE_DIR/compose-ps-passed.txt"
cp "${BACKUP_FILE}.manifest" "$EVIDENCE_DIR/database-backup.manifest"

echo "$APP_VERSION 隔离部署、自动冒烟和备份恢复验证全部通过"
