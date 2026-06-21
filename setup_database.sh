#!/bin/bash

# 数据库设置脚本

echo "=== 设置数据库和Redis ==="
echo ""

generate_secret() {
    python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
}

export DB_PASSWORD="${DB_PASSWORD:-$(generate_secret)}"

# 检查docker-compose
if command -v docker-compose &> /dev/null; then
    echo "使用 docker-compose 启动服务..."
    cd "$(dirname "$0")"
    docker-compose up -d postgres redis
    echo "等待服务启动..."
    sleep 5
    docker-compose ps
elif docker ps &> /dev/null; then
    echo "使用 docker 命令启动服务..."
    
    # 检查容器是否已存在
    if docker ps -a | grep -q postgres-aicommander; then
        echo "启动现有PostgreSQL容器..."
        docker start postgres-aicommander
    else
        echo "创建PostgreSQL容器..."
        docker run -d --name postgres-aicommander \
            -e POSTGRES_DB=aicommander \
            -e POSTGRES_USER=aicommander \
            -e POSTGRES_PASSWORD="$DB_PASSWORD" \
            -p 5432:5432 \
            postgres:14 || echo "⚠️  PostgreSQL启动失败，请检查网络或手动启动"
    fi
    
    if docker ps -a | grep -q redis-aicommander; then
        echo "启动现有Redis容器..."
        docker start redis-aicommander
    else
        echo "创建Redis容器..."
        docker run -d --name redis-aicommander \
            -p 6379:6379 \
            redis:7-alpine || echo "⚠️  Redis启动失败，请检查网络或手动启动"
    fi
    
    sleep 3
    docker ps | grep -E "(postgres|redis)"
else
    echo "❌ Docker未运行"
    echo "请先启动Docker Desktop或运行: colima start"
    exit 1
fi

echo ""
echo "✅ 数据库服务已启动"
echo "PostgreSQL: localhost:5432"
echo "Redis: localhost:6379"
