# The native image must be built and accepted on the target CPU architecture.
# Keep its runtime libraries together: do not copy a host wheel across libc/OS.
ARG ROAD_ENGINE_IMAGE=aicommander-road-engine:3.8.3-completion-candidate
FROM ${ROAD_ENGINE_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /opt/aic/backend
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY backend/app ./app
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod 0755 docker-entrypoint.sh \
    && chmod -R a+rX /opt/aic/backend/app \
    && groupadd --system --gid 10001 aicommander \
    && useradd --system --uid 10001 --gid aicommander --home-dir /opt/aic/backend aicommander
USER 10001:10001
RUN python -c "import importlib.metadata; from valhalla import Actor; assert importlib.metadata.version('pyvalhalla') == '3.8.3'"
ENTRYPOINT ["/opt/aic/backend/docker-entrypoint.sh"]
CMD ["celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=1", "--queues=road_analysis", "--hostname=roads@%h", "--prefetch-multiplier=1", "--max-tasks-per-child=20"]
