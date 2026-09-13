#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

fail() {
    echo "v3.0 双域态势研判验收失败: $*" >&2
    exit 1
}

[ -x "$PYTHON" ] || fail "缺少 backend/venv，请先安装后端依赖"
[ -d "$FRONTEND_DIR/node_modules" ] || fail "缺少 frontend/node_modules，请先安装前端依赖"

echo "[1/5] 增量、热点、井点、链条与只读边界回归"
cd "$BACKEND_DIR"
"$PYTHON" -m pytest \
    tests/test_situation_analysis.py \
    tests/test_geo_analysis.py \
    tests/test_dual_domain_pilot.py \
    tests/test_evidence_graph.py \
    tests/test_chain_analysis.py \
    tests/test_release_version.py \
    tests/test_deployment_rehearsal.py \
    -q

echo "[2/5] 全新数据库迁移兼容检查"
VERIFY_DIR="$(mktemp -d /tmp/aicommander-situation-verify.XXXXXX)"
trap 'rm -rf "$VERIFY_DIR"' EXIT HUP INT TERM
VERIFY_DB="$VERIFY_DIR/verify.db"
SECRET_KEY=situation-verification-only \
DATABASE_URL="sqlite:///$VERIFY_DB" \
AUTH_REQUIRED=false \
AUTO_CREATE_TABLES=false \
"$PYTHON" -m alembic upgrade head

"$PYTHON" "$ROOT_DIR/scripts/verify-sqlite-schema.py" "$VERIFY_DB" \
    cases jurisdiction_assets chain_links knowledge_assets

echo "[3/5] 前端态势、证据和工作台呈现回归"
cd "$FRONTEND_DIR"
npm run test -- --run \
    src/pages/Situation/situationPresentation.test.ts \
    src/pages/Graphs/evidenceGraphPresentation.test.ts \
    src/pages/Workbench/workbenchPresentation.test.ts

echo "[4/5] 前端类型检查与生产构建"
npm run typecheck
npm run build

echo "[5/5] 生产编排、脚本和补丁静态检查"
cd "$ROOT_DIR"
docker compose --env-file .env.production.example -f docker-compose.production.yml config --quiet
sh -n scripts/verify-situation.sh
git diff --check

echo "v3.0 双域态势研判代码级验收通过；真实案件适用性、节时效果和业务签字仍需在测试部署现场完成。"
