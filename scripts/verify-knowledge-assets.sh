#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON="$BACKEND_DIR/venv/bin/python"

fail() {
    echo "知识资产验收失败: $*" >&2
    exit 1
}

[ -x "$PYTHON" ] || fail "缺少 backend/venv，请先安装后端依赖"
[ -d "$FRONTEND_DIR/node_modules" ] || fail "缺少 frontend/node_modules，请先安装前端依赖"

echo "[1/5] 后端知识资产生命周期与既有案件研判回归"
cd "$BACKEND_DIR"
"$PYTHON" -m pytest \
    tests/test_knowledge_asset_lifecycle.py \
    tests/test_case_ai_foundation.py \
    tests/test_experience_cards.py \
    tests/test_case_intelligence.py \
    tests/test_suggestions.py \
    tests/test_batch_review.py \
    -q

echo "[2/5] 全新数据库迁移与知识资产表检查"
VERIFY_DIR="$(mktemp -d /tmp/aicommander-knowledge-verify.XXXXXX)"
trap 'rm -rf "$VERIFY_DIR"' EXIT HUP INT TERM
VERIFY_DB="$VERIFY_DIR/verify.db"
SECRET_KEY=knowledge-asset-verification-only \
DATABASE_URL="sqlite:///$VERIFY_DB" \
AUTH_REQUIRED=false \
AUTO_CREATE_TABLES=false \
"$PYTHON" -m alembic upgrade head

"$PYTHON" "$ROOT_DIR/scripts/verify-sqlite-schema.py" "$VERIFY_DB" \
    knowledge_assets knowledge_reuse_records workbench_task_sessions

echo "[3/5] 前端知识资产呈现测试"
cd "$FRONTEND_DIR"
npm run test -- --run src/pages/CaseIntelligence/caseIntelligencePresentation.test.ts

echo "[4/5] 前端类型检查与生产构建"
npm run typecheck
npm run build

echo "[5/5] 生产编排与版本一致性检查"
cd "$ROOT_DIR"
docker compose -f docker-compose.production.yml --env-file .env.production.example config --quiet
cd "$BACKEND_DIR"
"$PYTHON" -m pytest tests/test_release_version.py tests/test_deployment_rehearsal.py -q
cd "$ROOT_DIR"
git diff --check

echo "v2.8 知识资产代码级验收通过；真实业务案例采纳率与报告可用性仍需指定人员现场复核。"
