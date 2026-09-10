FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65 AS core

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
    && mkdir -p /app/data/chroma_db /var/lib/aicommander/maps \
    && chown -R aicommander:aicommander /app /var/lib/aicommander/maps

USER aicommander

# 暴露端口
EXPOSE 8000

# 启动命令
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

# Optional export-capable API image. Build in the connected packaging zone;
# runtime requests never install packages or download browsers/fonts.
FROM node:24-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS document-dependencies
WORKDIR /renderer
COPY document-renderer/package.json document-renderer/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund

FROM core AS document-renderer
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/aic-browsers
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer fontconfig fonts-noto-cjk fonts-noto-core fonts-noto-color-emoji \
    && pip install -r /app/requirements-renderer.txt \
    && python -m playwright install --with-deps --only-shell chromium \
    && fc-cache -f \
    && mkdir -p /usr/share/aicommander \
    && dpkg-query -W > /usr/share/aicommander/export-packages.tsv \
    && apt-get clean
COPY --from=document-dependencies /usr/local/bin/node /usr/local/bin/node
COPY --from=document-dependencies /renderer/node_modules /app/document-renderer/node_modules
RUN chmod -R a+rX /opt/aic-browsers /app/document-renderer
USER 10001:10001
RUN node --version && soffice --version && python -c "import playwright.sync_api"

# Keep the existing lightweight default; explicitly select document-renderer
# only for the API instance that provides full Word/PDF export.
FROM core AS runtime
