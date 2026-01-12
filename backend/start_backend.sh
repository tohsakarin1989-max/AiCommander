#!/bin/bash

# 后端启动脚本

cd "$(dirname "$0")"

# 激活虚拟环境
source venv/bin/activate

# 设置环境变量
export DATABASE_URL=postgresql://aicommander:aicommander123@localhost:5432/aicommander
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=your-secret-key-change-in-production
export OPENAI_API_KEY=${OPENAI_API_KEY:-}
export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
export CELERY_BROKER_URL=redis://localhost:6379/0
export CELERY_RESULT_BACKEND=redis://localhost:6379/0
export FRONTEND_URL=http://localhost:3000

# 检查数据库连接
echo "检查数据库连接..."
python -c "
import sys
try:
    from sqlalchemy import create_engine
    engine = create_engine('${DATABASE_URL}')
    with engine.connect() as conn:
        print('✅ 数据库连接成功')
except Exception as e:
    print(f'⚠️  数据库连接失败: {e}')
    print('请确保PostgreSQL已启动')
    sys.exit(1)
" || exit 1

# 初始化数据库（如果表不存在）
echo "初始化数据库..."
python init_db.py

# 启动服务
echo "启动后端服务..."
echo "访问地址: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo "按 Ctrl+C 停止服务"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

