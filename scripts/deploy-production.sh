#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="docker-compose.production.yml"
ENV_FILE=".env.production"

if [ ! -f "$ENV_FILE" ]; then
    echo "缺少 $ENV_FILE，请先执行 ./scripts/init-production.sh" >&2
    exit 1
fi

configured_secrets_dir="$(sed -n 's/^SECRETS_DIR=//p' "$ENV_FILE" | tail -1)"
configured_secrets_dir="${configured_secrets_dir:-./secrets}"
case "$configured_secrets_dir" in
    /*) SECRETS_DIR="$configured_secrets_dir" ;;
    *) SECRETS_DIR="$ROOT_DIR/${configured_secrets_dir#./}" ;;
esac

for secret in db_password redis_password secret_key bootstrap_token; do
    if [ ! -s "$SECRETS_DIR/$secret" ]; then
        echo "缺少生产密钥 $SECRETS_DIR/$secret" >&2
        exit 1
    fi
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build --pull
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d postgres redis
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm backend alembic upgrade head
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

APP_PORT="$(sed -n 's/^APP_PORT=//p' "$ENV_FILE" | tail -1)"
APP_PORT="${APP_PORT:-3000}"
echo "等待健康检查..."
attempt=0
until curl -fsS "http://127.0.0.1:${APP_PORT}/health/ready" >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "服务未在预期时间内就绪，请检查 docker compose logs" >&2
        exit 1
    fi
    sleep 2
done

echo "AICommander v2.0.0 已启动，宿主机入口: http://127.0.0.1:${APP_PORT}"
