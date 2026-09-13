#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

fail() {
    echo "v2.9 证据图谱验收失败: $*" >&2
    exit 1
}

[ -x "$PYTHON" ] || fail "缺少 backend/venv，请先安装后端依赖"
[ -d "$FRONTEND_DIR/node_modules" ] || fail "缺少 frontend/node_modules，请先安装前端依赖"

echo "[1/5] 证据图谱、链条边界与版本契约回归"
cd "$BACKEND_DIR"
"$PYTHON" -m pytest \
    tests/test_evidence_graph.py \
    tests/test_chain_analysis.py \
    tests/test_release_version.py \
    tests/test_deployment_rehearsal.py \
    -q

echo "[2/5] 全新数据库迁移兼容检查"
VERIFY_DIR="$(mktemp -d /tmp/aicommander-evidence-graph-verify.XXXXXX)"
trap 'rm -rf "$VERIFY_DIR"' EXIT HUP INT TERM
VERIFY_DB="$VERIFY_DIR/verify.db"
SECRET_KEY=evidence-graph-verification-only \
DATABASE_URL="sqlite:///$VERIFY_DB" \
AUTH_REQUIRED=false \
AUTO_CREATE_TABLES=false \
"$PYTHON" -m alembic upgrade head

"$PYTHON" "$ROOT_DIR/scripts/verify-sqlite-schema.py" "$VERIFY_DB" \
    cases case_evidence chain_links jurisdiction_assets agent_runs agent_artifacts knowledge_assets

echo "[3/5] 前端证据分层与工作台入口回归"
cd "$FRONTEND_DIR"
npm run test -- --run \
    src/pages/Graphs/evidenceGraphPresentation.test.ts \
    src/pages/Workbench/workbenchPresentation.test.ts

echo "[4/5] 前端类型检查与生产构建"
npm run typecheck
npm run build

echo "[5/5] 生产编排、脚本和补丁静态检查"
cd "$ROOT_DIR"
docker compose -f docker-compose.production.yml --env-file .env.production.example config --quiet
sh -n scripts/verify-evidence-graph.sh
git diff --check

echo "v2.9 证据图谱代码级验收通过；真实案件证据适用性与人员签字仍需在测试部署现场完成。"
