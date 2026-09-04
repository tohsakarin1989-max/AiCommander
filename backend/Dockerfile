FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --upgrade pip==26.2.1 \
    && pip install -r requirements.txt

# 复制应用代码
COPY . .

RUN chmod 0755 /app/docker-entrypoint.sh \
    && groupadd --system --gid 10001 aicommander \
    && useradd --system --uid 10001 --gid aicommander --home-dir /app aicommander \
    && mkdir -p /app/data/chroma_db \
    && chown -R aicommander:aicommander /app

USER aicommander

# 暴露端口
EXPOSE 8000

# 启动命令
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
