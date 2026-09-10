#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

[ -f "$ENV_FILE" ] || {
    echo "缺少 ${ENV_FILE}，无法执行 PostGIS 发布验收" >&2
    exit 1
}

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

fail() {
    echo "PostGIS 发布验收失败: $*" >&2
    exit 1
}

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

postgis_image="$(read_env POSTGIS_IMAGE)"
case "$postgis_image" in
    *postgis*@sha256:????????????????????????????????????????????????????????????????) ;;
    *) fail "POSTGIS_IMAGE 必须是带 SHA-256 摘要的 PostGIS 镜像" ;;
esac

timestamp="$(date '+%Y%m%d_%H%M%S')"
VERIFY_DATABASE="aicommander_v36_verify_${timestamp}_$$"
case "$VERIFY_DATABASE" in
    aicommander_v36_verify_[0-9_]*) ;;
    *) fail "一次性验证数据库名称不安全" ;;
esac

TMP_ROOT="${TMPDIR:-/tmp}"
WORK_DIR="$(mktemp -d "$TMP_ROOT/aicommander-postgis-check.XXXXXX")"
EVIDENCE_FILE="${EVIDENCE_FILE:-$ROOT_DIR/outputs/release-evidence/postgis-v36-${timestamp}.json}"
database_created=false

cleanup() {
    set +e
    if [ "$database_created" = "true" ]; then
        compose exec -T postgres sh -c \
            'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec dropdb -h 127.0.0.1 -U aicommander --if-exists --force "$1"' \
            sh "$VERIFY_DATABASE" >/dev/null 2>&1
    fi
    case "$WORK_DIR" in
        "$TMP_ROOT"/aicommander-postgis-check.*) rm -rf -- "$WORK_DIR" ;;
    esac
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

compose up -d postgres
compose exec -T postgres sh -c \
    'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec createdb -h 127.0.0.1 -U aicommander "$1"' \
    sh "$VERIFY_DATABASE"
database_created=true

compose run --rm --no-deps -e DB_NAME="$VERIFY_DATABASE" backend alembic upgrade head
compose run --rm --no-deps -e DB_NAME="$VERIFY_DATABASE" backend \
    python -m app.release_checks.postgis_v36 > "$WORK_DIR/result.json"

mkdir -p "$(dirname -- "$EVIDENCE_FILE")"
umask 077
{
    printf '{\n'
    printf '  "verified_at": "%s",\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '  "migration_status": "passed",\n'
    printf '  "concurrency_status": "passed",\n'
    printf '  "result": '
    cat "$WORK_DIR/result.json"
    printf '}\n'
} > "$EVIDENCE_FILE"
chmod 0600 "$EVIDENCE_FILE"

cleanup
database_created=false
trap - EXIT HUP INT TERM

echo "PostGIS v3.6 临时库迁移与并发验收通过，证据文件: $EVIDENCE_FILE"
