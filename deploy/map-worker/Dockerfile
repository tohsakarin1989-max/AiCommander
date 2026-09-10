FROM node:24-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS syntax
WORKDIR /opt/aic/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund

FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /opt/aic/backend
COPY backend/requirements.txt /opt/aic/backend/requirements.txt
COPY scripts/map-build-requirements.txt /opt/aic/map-build-requirements.txt
RUN pip install --upgrade pip==26.2.1 \
    && pip install -r requirements.txt -r /opt/aic/map-build-requirements.txt
COPY --from=syntax /usr/local/bin/node /usr/local/bin/node
COPY --from=syntax /opt/aic/frontend/node_modules /opt/aic/frontend/node_modules
COPY frontend/scripts/validate-map-style.cjs /opt/aic/frontend/scripts/validate-map-style.cjs
COPY backend/app /opt/aic/backend/app
COPY backend/docker-entrypoint.sh /opt/aic/backend/docker-entrypoint.sh
RUN chmod 0755 docker-entrypoint.sh \
    && chmod -R a+rX /opt/aic/backend/app /opt/aic/frontend/scripts \
    && groupadd --system --gid 10001 aicommander \
    && useradd --system --uid 10001 --gid aicommander --home-dir /opt/aic/backend aicommander \
    && mkdir -p /var/lib/aicommander/maps \
    && chown aicommander:aicommander /var/lib/aicommander/maps
USER 10001:10001
RUN node --version \
    && python -c "from app.services.map_style_syntax import validate_style_syntax; validate_style_syntax(b'{\"version\":8,\"sources\":{},\"layers\":[]}')"
ENTRYPOINT ["/opt/aic/backend/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=1", "--queues=map_build", "--prefetch-multiplier=1", "--max-tasks-per-child=1"]
