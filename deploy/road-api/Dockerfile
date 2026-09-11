# Preserve the existing Word/PDF runtime while adding the accepted road engine.
ARG DOCUMENT_API_IMAGE=aicommander-backend-documents:v4.1-final-candidate
ARG ROAD_ENGINE_IMAGE=aicommander-road-engine:3.8.3-completion-candidate
FROM ${ROAD_ENGINE_IMAGE} AS road-engine
FROM ${DOCUMENT_API_IMAGE} AS road-api
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libprotobuf-lite32t64 libspatialite8t64 libluajit-5.1-2
COPY --from=road-engine /wheels/ /opt/aic-road-wheels/
RUN python -m pip install --no-index --no-deps /opt/aic-road-wheels/pyvalhalla-*.whl
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-index --no-deps -r requirements.txt && python -m pip check
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/docker-entrypoint.sh ./
COPY backend/document-renderer/map-render.mjs backend/document-renderer/render-docx.cjs ./document-renderer/
RUN chmod 0755 docker-entrypoint.sh && chmod -R a+rX app alembic && chmod a+r alembic.ini document-renderer/map-render.mjs
USER 10001:10001
RUN python -c "from valhalla import Actor; import playwright.sync_api; from alembic.config import Config; from alembic.script import ScriptDirectory; assert ScriptDirectory.from_config(Config('alembic.ini')).get_current_head() == 'b508c42fd75b'" \
    && soffice --version && node --version
