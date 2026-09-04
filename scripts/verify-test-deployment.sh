#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || {
    echo "缺少 ${ENV_FILE}，无法执行测试部署验收" >&2
    exit 1
}

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

fail() {
    echo "测试部署验收失败: $*" >&2
    exit 1
}

command -v curl >/dev/null 2>&1 || fail "缺少 curl"

APP_VERSION="$(read_env APP_VERSION)"
APP_VERSION="${APP_VERSION:-$(tr -d '\r\n' < VERSION)}"
APP_PORT="$(read_env APP_PORT)"
APP_PORT="${APP_PORT:-3000}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${APP_PORT}}"
BASE_URL="${BASE_URL%/}"
ENABLE_AGENT_LAB="$(read_env ENABLE_AGENT_LAB)"
ENABLE_AGENT_LAB="${ENABLE_AGENT_LAB:-false}"
AGENT_MODE="$(read_env AGENT_MODE)"
AGENT_MODE="${AGENT_MODE:-off}"
AGENT_MUTATIONS_ENABLED="$(read_env AGENT_MUTATIONS_ENABLED)"
AGENT_MUTATIONS_ENABLED="${AGENT_MUTATIONS_ENABLED:-false}"

[ "$ENABLE_AGENT_LAB" = "false" ] \
    || fail "v2.0.1-test 验收要求 ENABLE_AGENT_LAB=false"
[ "$AGENT_MODE" = "off" ] \
    || fail "v2.0.1-test 验收要求 AGENT_MODE=off"
[ "$AGENT_MUTATIONS_ENABLED" = "false" ] \
    || fail "v2.0.1-test 验收要求 AGENT_MUTATIONS_ENABLED=false"

timestamp="$(date '+%Y%m%d-%H%M%S')"
EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT_DIR/backups/deployment-evidence/$timestamp}"
umask 077
mkdir -p "$EVIDENCE_DIR"

fetch() {
    name="$1"
    path="$2"
    expected_status="$3"
    BODY_FILE="$EVIDENCE_DIR/${name}.body"
    HEADERS_FILE="$EVIDENCE_DIR/${name}.headers"
    actual_status="$(curl -sS --connect-timeout 5 --max-time 30 \
        -D "$HEADERS_FILE" -o "$BODY_FILE" -w '%{http_code}' \
        "$BASE_URL$path")" \
        || fail "$path 无法访问"
    [ "$actual_status" = "$expected_status" ] \
        || fail "$path 返回 ${actual_status}，期望 $expected_status"
}

body_contains() {
    pattern="$1"
    label="$2"
    grep -F "$pattern" "$BODY_FILE" >/dev/null \
        || fail "$label 响应不符合预期"
}

fetch frontend / 200
grep -i '^x-content-type-options:[[:space:]]*nosniff' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 X-Content-Type-Options 安全头"
grep -i '^x-frame-options:[[:space:]]*DENY' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 X-Frame-Options 安全头"
grep -i '^referrer-policy:[[:space:]]*no-referrer' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 Referrer-Policy 安全头"
grep -i '^permissions-policy:' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 Permissions-Policy 安全头"
grep -i '^strict-transport-security:[[:space:]]*max-age=' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 HSTS 安全头"
grep -i '^content-security-policy:' "$HEADERS_FILE" >/dev/null \
    || fail "前端缺少 Content-Security-Policy 安全头"

fetch health-live /health/live 200
body_contains '"status":"alive"' "存活检查"
body_contains "\"version\":\"$APP_VERSION\"" "运行版本"

fetch health-ready /health/ready 200
body_contains '"status":"ready"' "就绪检查"
body_contains "\"version\":\"$APP_VERSION\"" "就绪版本"
body_contains '"database":{"status":"ok"' "数据库依赖"
body_contains '"schema":{"status":"ok"' "数据库迁移"
body_contains '"redis":{"status":"ok"' "Redis 依赖"

fetch health-agents /health/agents 200
body_contains '"status":"off"' "Agent 状态"
body_contains '"mode":"off"' "Agent 模式"
body_contains '"affects_core_readiness":false' "Agent 核心隔离"
body_contains "\"version\":\"$APP_VERSION\"" "Agent 健康版本"

fetch anonymous-cases /api/cases 401
fetch docs-disabled /docs 404
fetch redoc-disabled /redoc 404
fetch openapi-disabled /openapi.json 404

source_revision="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
checked_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf '%s\n' \
    "checked_at=$checked_at" \
    "application_version=$APP_VERSION" \
    "source_revision=$source_revision" \
    "base_url=$BASE_URL" \
    "agent_lab_enabled=$ENABLE_AGENT_LAB" \
    "agent_mode=$AGENT_MODE" \
    "agent_mutations_enabled=$AGENT_MUTATIONS_ENABLED" \
    "overall=passed" \
    > "$EVIDENCE_DIR/verification.manifest"

echo "测试部署自动验收通过，证据目录: $EVIDENCE_DIR"
