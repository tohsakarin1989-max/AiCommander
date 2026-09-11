#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
. "$ROOT_DIR/scripts/production-compose.sh"

[ -f "$ENV_FILE" ] || {
    echo "缺少 ${ENV_FILE}，无法备份生产数据库" >&2
    exit 1
}

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1"
    else
        shasum -a 256 "$1"
    fi
}

configured_backup_dir="$(read_env BACKUP_DIR)"
configured_backup_dir="${configured_backup_dir:-./backups/postgres}"
DATABASE_NAME="$(read_env DB_NAME)"
DATABASE_NAME="${DATABASE_NAME:-aicommander}"
case "$DATABASE_NAME" in
    ""|*[!a-zA-Z0-9_]*)
        echo "数据库名称仅允许字母、数字和下划线" >&2
        exit 1
        ;;
esac
case "$configured_backup_dir" in
    /*) BACKUP_DIR="$configured_backup_dir" ;;
    *) BACKUP_DIR="$ROOT_DIR/${configured_backup_dir#./}" ;;
esac

umask 077
mkdir -p "$BACKUP_DIR"

timestamp="$(date '+%Y%m%d-%H%M%S')"
backup_name="aicommander-${timestamp}.dump"
backup_path="$BACKUP_DIR/$backup_name"
temporary_path="$backup_path.tmp"
manifest_path="$backup_path.manifest"
checksum_path="$backup_path.sha256"

cleanup() {
    rm -f "$temporary_path"
}
trap cleanup EXIT HUP INT TERM

echo "正在创建数据库升级前备份..."
compose exec -T postgres \
    sh -c 'export PGPASSWORD="$(cat /run/secrets/db_password)"; exec pg_dump -h 127.0.0.1 -U aicommander -d "$1" --format=custom --compress=9' \
    sh "$DATABASE_NAME" \
    > "$temporary_path"

[ -s "$temporary_path" ] || {
    echo "数据库备份为空，已停止部署" >&2
    exit 1
}
mv "$temporary_path" "$backup_path"

database_revision="$(
    compose exec -T postgres \
        sh -c 'export PGPASSWORD="$(cat /run/secrets/db_password)"; psql -h 127.0.0.1 -U aicommander -d "$1" -Atc "SELECT version_num FROM alembic_version"' \
        sh "$DATABASE_NAME" \
        2>/dev/null || true
)"
database_revision="${database_revision:-untracked}"
application_version="$(read_env APP_VERSION)"
source_revision="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

printf '%s\n' \
    "created_at=$timestamp" \
    "application_version=${application_version:-unknown}" \
    "source_revision=$source_revision" \
    "database_name=$DATABASE_NAME" \
    "database_revision=$database_revision" \
    "format=postgres-custom" \
    > "$manifest_path"

(
    cd "$BACKUP_DIR"
    checksum "$backup_name"
) > "$checksum_path"

echo "数据库备份完成: $backup_path"
echo "校验文件: $checksum_path"
