#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

[ -f "$ENV_FILE" ] || {
    echo "缺少 ${ENV_FILE}，无法验证备份恢复" >&2
    exit 1
}

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

fail() {
    echo "备份恢复验证失败: $*" >&2
    exit 1
}

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

checksum_value() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | sed 's/[[:space:]].*$//'
    else
        shasum -a 256 "$1" | sed 's/[[:space:]].*$//'
    fi
}

configured_backup_dir="$(read_env BACKUP_DIR)"
configured_backup_dir="${configured_backup_dir:-./backups/postgres}"
case "$configured_backup_dir" in
    /*) BACKUP_DIR="$configured_backup_dir" ;;
    *) BACKUP_DIR="$ROOT_DIR/${configured_backup_dir#./}" ;;
esac

if [ -z "${BACKUP_FILE:-}" ]; then
    BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/aicommander-*.dump 2>/dev/null | head -1 || true)"
fi
[ -n "$BACKUP_FILE" ] || fail "没有找到可验证的数据库备份"
[ -s "$BACKUP_FILE" ] || fail "备份文件不存在或为空: $BACKUP_FILE"

CHECKSUM_FILE="${BACKUP_FILE}.sha256"
[ -s "$CHECKSUM_FILE" ] || fail "缺少校验文件: $CHECKSUM_FILE"
expected_checksum="$(sed -n '1s/[[:space:]].*$//p' "$CHECKSUM_FILE")"
actual_checksum="$(checksum_value "$BACKUP_FILE")"
[ "$expected_checksum" = "$actual_checksum" ] || fail "备份文件 SHA-256 校验失败"

MANIFEST_FILE="${BACKUP_FILE}.manifest"
[ -s "$MANIFEST_FILE" ] || fail "缺少备份清单: $MANIFEST_FILE"
manifest_format="$(sed -n 's/^format=//p' "$MANIFEST_FILE")"
[ "$manifest_format" = "postgres-custom" ] || fail "备份清单格式不是 postgres-custom"
expected_database_revision="$(sed -n 's/^database_revision=//p' "$MANIFEST_FILE")"
case "$expected_database_revision" in
    ''|untracked|unknown|*[!a-zA-Z0-9_]*)
        fail "备份清单缺少已登记的迁移版本；首次迁移前备份不能作为恢复通过证据"
        ;;
esac

timestamp="$(date '+%Y%m%d_%H%M%S')"
RESTORE_DATABASE="aicommander_restore_check_${timestamp}_$$"
case "$RESTORE_DATABASE" in
    aicommander_restore_check_[0-9_]*) ;;
    *) fail "临时恢复数据库名称不安全" ;;
esac

database_created=false
cleanup() {
    if [ "$database_created" = "true" ]; then
        compose exec -T postgres sh -c \
            'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec dropdb -h 127.0.0.1 -U aicommander --if-exists --force "$1"' \
            sh "$RESTORE_DATABASE" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

database_created=true
compose exec -T postgres sh -c \
    'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec createdb -h 127.0.0.1 -U aicommander "$1"' \
    sh "$RESTORE_DATABASE"

compose exec -T postgres sh -c \
    'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec pg_restore -h 127.0.0.1 -U aicommander -d "$1" --exit-on-error --no-owner --no-privileges' \
    sh "$RESTORE_DATABASE" < "$BACKUP_FILE"

restored_table_count="$(
    compose exec -T postgres sh -c \
        'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec psql -h 127.0.0.1 -U aicommander -d "$1" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = '\''public'\'' AND table_type = '\''BASE TABLE'\''"' \
        sh "$RESTORE_DATABASE"
)"
case "$restored_table_count" in
    ''|*[!0-9]*) fail "无法读取恢复后的表数量" ;;
esac
[ "$restored_table_count" -gt 0 ] || fail "恢复后的 public schema 没有业务表"

if ! database_revision="$(
    compose exec -T postgres sh -c \
        'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec psql -h 127.0.0.1 -U aicommander -d "$1" -v ON_ERROR_STOP=1 -Atc "SELECT version_num FROM alembic_version"' \
        sh "$RESTORE_DATABASE"
)"; then
    fail "读取恢复后的 Alembic 版本失败"
fi
[ "$database_revision" = "$expected_database_revision" ] \
    || fail "恢复后的 Alembic 版本与备份清单不一致"

EVIDENCE_FILE="${EVIDENCE_FILE:-${BACKUP_FILE}.restore-verified}"
umask 077
printf '%s\n' \
    "verified_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    "backup_file=$(basename "$BACKUP_FILE")" \
    "sha256=$actual_checksum" \
    "restored_table_count=$restored_table_count" \
    "database_revision=$database_revision" \
    "expected_database_revision=$expected_database_revision" \
    "restore_status=passed" \
    > "$EVIDENCE_FILE"

cleanup
database_created=false
trap - EXIT HUP INT TERM

echo "备份已在临时数据库完成恢复验证，证据文件: $EVIDENCE_FILE"
