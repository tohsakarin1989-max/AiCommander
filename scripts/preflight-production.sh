#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
VERSION_FILE="${VERSION_FILE:-$ROOT_DIR/VERSION}"

fail() {
    echo "生产部署预检失败: $*" >&2
    exit 1
}

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

file_mode() {
    if stat -c '%a' "$1" >/dev/null 2>&1; then
        stat -c '%a' "$1"
    else
        stat -f '%Lp' "$1"
    fi
}

command -v docker >/dev/null 2>&1 || fail "未安装 Docker"
command -v curl >/dev/null 2>&1 || fail "未安装 curl"
docker compose version >/dev/null 2>&1 || fail "Docker Compose 不可用"

[ -f "$ENV_FILE" ] || fail "缺少 ${ENV_FILE}，请先执行 ./scripts/init-production.sh"
[ -f "$VERSION_FILE" ] || fail "缺少版本文件 $VERSION_FILE"
case "$(file_mode "$ENV_FILE")" in
    400|600) ;;
    *) fail "$ENV_FILE 权限必须为 400 或 600" ;;
esac

APP_DOMAIN="$(read_env APP_DOMAIN)"
APP_PORT="$(read_env APP_PORT)"
APP_VERSION="$(read_env APP_VERSION)"
ALEMBIC_TARGET="$(read_env ALEMBIC_TARGET)"
POSTGIS_IMAGE="$(read_env POSTGIS_IMAGE)"
configured_secrets_dir="$(read_env SECRETS_DIR)"
agent_enabled="$(read_env ENABLE_AGENT_LAB)"
agent_mode="$(read_env AGENT_MODE)"
agent_mutations="$(read_env AGENT_MUTATIONS_ENABLED)"
agent_external_policy="$(read_env AGENT_EXTERNAL_DATA_POLICY)"
agent_provider="$(read_env AGENT_PROVIDER)"
agent_model="$(read_env AGENT_MODEL)"
agent_model_id="$(read_env AGENT_MODEL_ID)"
agent_use_external_model="$(read_env AGENT_USE_EXTERNAL_MODEL)"

agent_enabled="${agent_enabled:-false}"
agent_mode="${agent_mode:-off}"
agent_mutations="${agent_mutations:-false}"
agent_external_policy="${agent_external_policy:-redacted_only}"
agent_provider="${agent_provider:-deterministic}"
agent_use_external_model="${agent_use_external_model:-false}"

case "$agent_enabled" in true|false) ;; *) fail "ENABLE_AGENT_LAB 只能为 true 或 false" ;; esac
case "$agent_mode" in off|shadow|assist) ;; *) fail "AGENT_MODE 只能为 off、shadow 或 assist" ;; esac
case "$agent_mutations" in true|false) ;; *) fail "AGENT_MUTATIONS_ENABLED 只能为 true 或 false" ;; esac
case "$agent_external_policy" in redacted_only|local_only) ;; *) fail "AGENT_EXTERNAL_DATA_POLICY 配置无效" ;; esac
case "$agent_provider" in deterministic|openai_agents|model_registry) ;; *) fail "AGENT_PROVIDER 配置无效" ;; esac
case "$agent_use_external_model" in true|false) ;; *) fail "AGENT_USE_EXTERNAL_MODEL 只能为 true 或 false" ;; esac
if [ "$agent_enabled" = "false" ] && [ "$agent_mode" != "off" ]; then
    fail "Agent Lab 未开启时 AGENT_MODE 必须为 off"
fi
if [ "$agent_mutations" = "true" ] && { [ "$agent_enabled" != "true" ] || [ "$agent_mode" != "assist" ]; }; then
    fail "Agent 正式数据写入只允许在已启用的 assist 模式开启"
fi
if [ "$agent_use_external_model" = "true" ]; then
    [ "$agent_external_policy" = "redacted_only" ] \
        || fail "外部模型只允许使用 redacted_only 数据策略"
    [ "$agent_provider" != "deterministic" ] \
        || fail "启用外部模型时必须选择外部模型适配器"
    if [ "$agent_provider" = "openai_agents" ]; then
        [ -n "$agent_model" ] || fail "OpenAI Agents 适配器必须配置 AGENT_MODEL"
    fi
    if [ "$agent_provider" = "model_registry" ]; then
        case "$agent_model_id" in
            ""|*[!0-9]*|0) fail "模型注册表适配器必须配置正整数 AGENT_MODEL_ID" ;;
        esac
    fi
fi

case "$APP_DOMAIN" in
    ""|aicommander.example.org|*://*|*/*|*" "*)
        fail "APP_DOMAIN 必须填写真实域名，且不能包含协议或路径"
        ;;
esac
case "$APP_PORT" in
    ""|*[!0-9]*) fail "APP_PORT 必须是 1-65535 的整数" ;;
esac
[ "$APP_PORT" -ge 1 ] && [ "$APP_PORT" -le 65535 ] \
    || fail "APP_PORT 必须是 1-65535 的整数"

repository_version="$(tr -d '\r\n' < "$VERSION_FILE")"
[ "$APP_VERSION" = "$repository_version" ] \
    || fail "APP_VERSION=$APP_VERSION 与 VERSION=$repository_version 不一致"
case "$APP_VERSION" in
    3.0.0-stable)
        [ "$ALEMBIC_TARGET" = "a7d9e1f2b304" ] \
            || fail "v3.0.0-stable 必须使用 ALEMBIC_TARGET=a7d9e1f2b304，禁止提前应用候选迁移"
        ;;
    *)
        [ "$ALEMBIC_TARGET" = "head" ] \
            || fail "v3.1 及以上候选部署必须使用 ALEMBIC_TARGET=head"
        case "$POSTGIS_IMAGE" in
            *postgis*@sha256:????????????????????????????????????????????????????????????????) ;;
            *) fail "v3.1 及以上必须配置带 sha256 摘要的 PostGIS 镜像 POSTGIS_IMAGE" ;;
        esac
        ;;
esac

configured_secrets_dir="${configured_secrets_dir:-./secrets}"
case "$configured_secrets_dir" in
    /*) SECRETS_DIR="$configured_secrets_dir" ;;
    *) SECRETS_DIR="$ROOT_DIR/${configured_secrets_dir#./}" ;;
esac

[ -d "$SECRETS_DIR" ] || fail "缺少生产密钥目录 $SECRETS_DIR"
case "$(file_mode "$SECRETS_DIR")" in
    700) ;;
    *) fail "$SECRETS_DIR 权限必须为 700" ;;
esac

check_secret() {
    name="$1"
    minimum_length="$2"
    path="$SECRETS_DIR/$name"
    [ -s "$path" ] || fail "缺少生产密钥 $path"
    case "$(file_mode "$path")" in
        400|600) ;;
        *) fail "$path 权限必须为 400 或 600" ;;
    esac
    value="$(tr -d '\r\n' < "$path")"
    [ "${#value}" -ge "$minimum_length" ] \
        || fail "$path 长度不足，必须至少 $minimum_length 位"
}

check_secret db_password 48
check_secret redis_password 48
check_secret secret_key 64
check_secret bootstrap_token 64

db_value="$(tr -d '\r\n' < "$SECRETS_DIR/db_password")"
redis_value="$(tr -d '\r\n' < "$SECRETS_DIR/redis_password")"
secret_value="$(tr -d '\r\n' < "$SECRETS_DIR/secret_key")"
bootstrap_value="$(tr -d '\r\n' < "$SECRETS_DIR/bootstrap_token")"
[ "$db_value" != "$redis_value" ] || fail "数据库和 Redis 不能复用同一密钥"
[ "$secret_value" != "$bootstrap_value" ] || fail "会话密钥和初始化令牌不能复用"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null \
    || fail "Docker Compose 生产配置无效"

echo "生产部署预检通过: 域名 ${APP_DOMAIN}，版本 ${APP_VERSION}，端口 ${APP_PORT}"
