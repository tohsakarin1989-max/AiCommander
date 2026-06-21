#!/bin/bash

echo "=== AI案件分析系统 - 本地开发环境设置 ==="
echo ""

generate_secret() {
    python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
}

ensure_local_secrets() {
    export DB_PASSWORD="${DB_PASSWORD:-$(generate_secret)}"
    export SECRET_KEY="${SECRET_KEY:-$(generate_secret)}"
}

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi
echo "✅ Python3: $(python3 --version)"

# 检查Node.js
if ! command -v node &> /dev/null; then
    echo "⚠️  Node.js 未安装，前端无法运行"
    echo "   安装方法: brew install node"
    NODE_AVAILABLE=false
else
    echo "✅ Node.js: $(node --version)"
    NODE_AVAILABLE=true
fi

# 检查Docker
if docker info &> /dev/null; then
    echo "✅ Docker 正在运行"
    DOCKER_AVAILABLE=true
else
    echo "⚠️  Docker 未运行"
    echo "   启动方法: 打开Docker Desktop 或运行: colima start"
    DOCKER_AVAILABLE=false
fi

echo ""
echo "=== 选择启动方式 ==="
echo "1. 使用Docker启动所有服务（需要Docker运行）"
echo "2. 仅使用Docker运行数据库和Redis，本地运行后端和前端"
echo "3. 完全本地运行（需要PostgreSQL和Redis）"
echo ""

read -p "请选择 (1-3): " choice

case $choice in
    1)
        if [ "$DOCKER_AVAILABLE" = false ]; then
            echo "❌ Docker未运行，无法使用此方式"
            exit 1
        fi
        ensure_local_secrets
        echo "启动Docker服务..."
        docker-compose up -d
        echo "✅ 服务已启动"
        echo "前端: http://localhost:3000"
        echo "后端: http://localhost:8000"
        ;;
    2)
        if [ "$DOCKER_AVAILABLE" = false ]; then
            echo "❌ Docker未运行，无法使用此方式"
            exit 1
        fi
        ensure_local_secrets
        echo "启动数据库和Redis..."
        docker-compose up -d postgres redis
        sleep 5
        
        echo "设置后端环境..."
        cd backend
        
        if [ ! -d "venv" ]; then
            echo "创建虚拟环境..."
            python3 -m venv venv
        fi
        
        echo "激活虚拟环境并安装依赖..."
        source venv/bin/activate
        pip install -q -r requirements.txt
        
        echo "初始化数据库..."
        export DATABASE_URL="postgresql://aicommander:${DB_PASSWORD}@localhost:5432/aicommander"
        export REDIS_URL=redis://localhost:6379/0
        python init_db.py
        
        echo ""
        echo "✅ 后端环境已设置"
        echo "请在新终端运行以下命令启动后端:"
        echo "  cd backend"
        echo "  source venv/bin/activate"
        echo "  export DB_PASSWORD='<本次生成或自定义的数据库密码>'"
        echo "  export DATABASE_URL=\"postgresql://aicommander:\${DB_PASSWORD}@localhost:5432/aicommander\""
        echo "  export REDIS_URL=redis://localhost:6379/0"
        echo "  export SECRET_KEY='<本次生成或自定义的本机密钥>'"
        echo "  uvicorn app.main:app --reload"
        echo ""
        
        if [ "$NODE_AVAILABLE" = true ]; then
            echo "启动前端..."
            cd ../frontend
            if [ ! -d "node_modules" ]; then
                npm install
            fi
            echo "✅ 前端依赖已安装"
            echo "请在新终端运行以下命令启动前端:"
            echo "  cd frontend"
            echo "  npm run dev"
        else
            echo "⚠️  Node.js未安装，无法启动前端"
        fi
        ;;
    3)
        echo "⚠️  完全本地运行需要安装PostgreSQL和Redis"
        echo "安装方法:"
        echo "  brew install postgresql@14 redis"
        echo "  brew services start postgresql@14"
        echo "  brew services start redis"
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac
