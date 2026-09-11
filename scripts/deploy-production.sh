#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
VERSION_FILE="${VERSION_FILE:-$ROOT_DIR/VERSION}"

. "$ROOT_DIR/scripts/production-compose.sh"

COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" VERSION_FILE="$VERSION_FILE" \
    sh ./scripts/preflight-production.sh
deployment_image_mode="$(production_env_value DEPLOY_IMAGE_MODE)"
case "${deployment_image_mode:-build}" in
    build) compose build --pull ;;
    prebuilt)
        # Refuse missing images before migrations or service changes; no pulling.
        deployment_images="$(compose config --images)"
        [ -n "$deployment_images" ] || { echo '部署镜像清单为空，已停止' >&2; exit 1; }
        printf '%s\n' "$deployment_images" | while IFS= read -r deployment_image; do
            docker image inspect "$deployment_image" >/dev/null 2>&1 || {
                echo "缺少已导入镜像: $deployment_image，内网模式不会自动下载" >&2
                exit 1
            }
        done
        ;;
    *) echo 'DEPLOY_IMAGE_MODE 只能为 build 或 prebuilt' >&2; exit 1 ;;
esac
compose run --rm --no-deps backend \
    python -c "from app.config import settings; print('生产应用配置校验通过')"
compose up -d --wait --wait-timeout 120 postgres redis
COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" sh ./scripts/backup-production.sh
ALEMBIC_TARGET="$(sed -n 's/^ALEMBIC_TARGET=//p' "$ENV_FILE" | tail -1)"
compose run --rm backend alembic upgrade "$ALEMBIC_TARGET"
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
