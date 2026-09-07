#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

fail() {
    echo "Agent Lab 验收失败: $*" >&2
    exit 1
}

[ -x "$PYTHON" ] || fail "缺少 backend/venv，请先安装后端依赖"
[ -d "$FRONTEND_DIR/node_modules" ] || fail "缺少 frontend/node_modules，请先安装前端依赖"
command -v docker >/dev/null 2>&1 || fail "缺少 Docker，无法验证生产编排"

echo "[1/6] 后端 Agent、权限、健康和生产配置回归"
cd "$BACKEND_DIR"
"$PYTHON" -m pytest \
    tests/test_agent_lab_config.py \
    tests/test_agent_lab_runtime.py \
    tests/test_agent_lab_eval.py \
    tests/test_map_steward_pilot.py \
    tests/test_api_contracts.py \
    tests/test_observability.py \
    tests/test_production_config.py \
    -q

echo "[2/6] 全新数据库迁移到 Agent Lab head"
VERIFY_DIR="$(mktemp -d /tmp/aicommander-agent-verify.XXXXXX)"
trap 'rm -rf "$VERIFY_DIR"' EXIT HUP INT TERM
VERIFY_DB="$VERIFY_DIR/verify.db"
SECRET_KEY=agent-lab-verification-only \
DATABASE_URL="sqlite:///$VERIFY_DB" \
AUTH_REQUIRED=false \
AUTO_CREATE_TABLES=false \
ENABLE_AGENT_LAB=false \
AGENT_MODE=off \
"$PYTHON" -m alembic upgrade head

VERIFY_DB="$VERIFY_DB" "$PYTHON" -c \
    "import os, sqlite3; c=sqlite3.connect(os.environ['VERIFY_DB']); t={r[0] for r in c.execute('select name from sqlite_master where type=\"table\"')}; required={'agent_runs','agent_events','agent_artifacts','agent_approvals'}; missing=required-t; c.close(); assert not missing, sorted(missing)"

echo "[3/6] 前端 Agent 展示和功能开关测试"
cd "$FRONTEND_DIR"
npm run test -- --run \
    src/config/features.test.ts \
    src/pages/Agents/agentPresentation.test.ts \
    src/pages/Agents/mapStewardPresentation.test.ts

echo "[4/6] 前端类型检查"
npm run typecheck

echo "[5/6] 前端生产构建"
npm run build

echo "[6/6] 生产编排与脚本静态校验"
cd "$ROOT_DIR"
docker compose -f docker-compose.production.yml --env-file .env.production.example config --quiet
sh -n scripts/preflight-production.sh
sh -n scripts/deploy-production.sh

echo "Agent Lab 代码级验收通过；目标服务器部署、备份恢复、脱敏业务评测和五次演示仍需现场完成。"
