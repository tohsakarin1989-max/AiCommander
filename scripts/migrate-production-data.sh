#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "用法: $0 <源 aicommander.db> <源系统 SECRET_KEY 文件>" >&2
    exit 2
fi

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SOURCE_DB="$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")"
SOURCE_SECRET="$(CDPATH= cd -- "$(dirname -- "$2")" && pwd)/$(basename -- "$2")"
REPORT_DIR="$ROOT_DIR/backups/migration"
REPORT_FILE="$REPORT_DIR/sqlite-to-postgres-report.json"

if [ ! -r "$SOURCE_DB" ]; then
    echo "无法读取源数据库: $SOURCE_DB" >&2
    exit 1
fi
if [ ! -r "$SOURCE_SECRET" ]; then
    echo "无法读取源系统密钥: $SOURCE_SECRET" >&2
    exit 1
fi
if [ ! -f "$ROOT_DIR/.env.production" ]; then
    echo "缺少 .env.production，请先执行 ./scripts/init-production.sh" >&2
    exit 1
fi

mkdir -p "$REPORT_DIR"
chmod 0700 "$ROOT_DIR/backups" "$REPORT_DIR"
cd "$ROOT_DIR"

ALEMBIC_TARGET="$(sed -n 's/^ALEMBIC_TARGET=//p' .env.production | tail -1)"
[ -n "$ALEMBIC_TARGET" ] || {
    echo "缺少 ALEMBIC_TARGET，禁止在迁移时隐式升级到未发布结构" >&2
    exit 1
}

docker compose --env-file .env.production -f docker-compose.production.yml build backend
docker compose --env-file .env.production -f docker-compose.production.yml up -d postgres redis
docker compose --env-file .env.production -f docker-compose.production.yml run --rm backend alembic upgrade "$ALEMBIC_TARGET"
docker compose --env-file .env.production -f docker-compose.production.yml run --rm \
    -v "$SOURCE_DB:/migration/source.db:ro" \
    -v "$SOURCE_SECRET:/migration/source_secret_key:ro" \
    -v "$REPORT_DIR:/migration/report" \
    backend python scripts/migrate_sqlite_to_postgres.py \
    --source /migration/source.db \
    --source-secret-key-file /migration/source_secret_key \
    --report /migration/report/sqlite-to-postgres-report.json

chmod 0600 "$REPORT_FILE"
echo "数据迁移完成，核验报告: $REPORT_FILE"
