#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

fail() {
    echo "v2.8 工作台验收失败: $*" >&2
    exit 1
}

[ -x "$PYTHON" ] || fail "缺少 backend/venv，请先安装后端依赖"
[ -d "$FRONTEND_DIR/node_modules" ] || fail "缺少 frontend/node_modules，请先安装前端依赖"

echo "[1/5] 工作台分流、权限、幂等和效率口径回归"
cd "$BACKEND_DIR"
"$PYTHON" -m pytest tests/test_workbench.py tests/test_release_version.py -q

echo "[2/5] 全新数据库迁移与工作台表检查"
VERIFY_DIR="$(mktemp -d /tmp/aicommander-workbench-verify.XXXXXX)"
trap 'rm -rf "$VERIFY_DIR"' EXIT HUP INT TERM
VERIFY_DB="$VERIFY_DIR/verify.db"
SECRET_KEY=workbench-verification-only \
DATABASE_URL="sqlite:///$VERIFY_DB" \
AUTH_REQUIRED=false \
AUTO_CREATE_TABLES=false \
"$PYTHON" -m alembic upgrade head

VERIFY_DB="$VERIFY_DB" "$PYTHON" -c \
    "import os, sqlite3; c=sqlite3.connect(os.environ['VERIFY_DB']); t={r[0] for r in c.execute('select name from sqlite_master where type=\"table\"')}; v=c.execute('select version_num from alembic_version').fetchone()[0]; c.close(); assert 'workbench_task_sessions' in t; assert v == 'a7d9e1f2b304', v"

echo "[3/5] 工作台前端规则测试"
cd "$FRONTEND_DIR"
npm run test -- --run src/pages/Workbench/workbenchPresentation.test.ts

echo "[4/5] 前端类型检查与生产构建"
npm run typecheck
npm run build

echo "[5/5] 版本、编排和脚本静态检查"
cd "$ROOT_DIR"
docker compose -f docker-compose.production.yml --env-file .env.production.example config --quiet
sh -n scripts/verify-workbench.sh
git diff --check

echo "v2.8 工作台代码级验收通过；真实业务节时和采纳情况仍需指定用户在测试环境积累至少 20 次会话。"
