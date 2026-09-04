#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"

compose() {
    if [ "$(sed -n 's/^ENABLE_AGENT_LAB=//p' "$ENV_FILE" | tail -1)" = "true" ]; then
        docker compose --profile agent-lab --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    else
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
}

COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" sh ./scripts/preflight-production.sh
compose build --pull
compose run --rm --no-deps backend \
    python -c "from app.config import settings; print('生产应用配置校验通过')"
compose up -d --wait --wait-timeout 120 postgres redis
COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" sh ./scripts/backup-production.sh
compose run --rm backend alembic upgrade head
compose up -d --remove-orphans --wait --wait-timeout 180
compose ps

APP_PORT="$(sed -n 's/^APP_PORT=//p' "$ENV_FILE" | tail -1)"
APP_PORT="${APP_PORT:-3000}"
APP_VERSION="$(sed -n 's/^APP_VERSION=//p' "$ENV_FILE" | tail -1)"
APP_VERSION="${APP_VERSION:-$(tr -d '\r\n' < VERSION)}"
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

echo "AICommander ${APP_VERSION} 已启动，宿主机入口: http://127.0.0.1:${APP_PORT}"
