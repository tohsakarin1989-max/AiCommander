#!/bin/bash

echo "启动AI案件分析系统..."

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo "错误: Docker未运行，请先启动Docker"
    exit 1
fi

# 启动服务
docker-compose up -d

echo "等待服务启动..."
sleep 10

# 检查服务状态
docker-compose ps

echo ""
echo "服务已启动！"
echo "前端: http://localhost:3000"
echo "后端API: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"

