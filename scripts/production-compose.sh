#!/bin/sh
# Shared by deployment, preflight and backup. Never source the configuration file.
production_env_value() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

compose() {
    # Compose gives exported shell variables precedence over --env-file. Keep
    # release identity identical in preflight, deployment and backup even when
    # the caller's terminal still exports a previous version or DB image.
    APP_VERSION="$(production_env_value APP_VERSION)"
    POSTGIS_IMAGE="$(production_env_value POSTGIS_IMAGE)"
    export APP_VERSION POSTGIS_IMAGE
    production_roads="$(production_env_value ENABLE_ROAD_ANALYSIS)"
    production_agents="$(production_env_value ENABLE_AGENT_LAB)"
    production_queries="$(production_env_value ENABLE_INTELLIGENT_QUERY)"
    # Profiles and runtime/build flags must describe the same selected
    # capability. Keep omitted values empty so Compose's existing defaults
    # (including the nullable intelligent-query switch) remain unchanged.
    ENABLE_ROAD_ANALYSIS="$production_roads"
    ENABLE_AGENT_LAB="$production_agents"
    ENABLE_INTELLIGENT_QUERY="$production_queries"
    export ENABLE_ROAD_ANALYSIS ENABLE_AGENT_LAB ENABLE_INTELLIGENT_QUERY
    production_documents="$(production_env_value ENABLE_DOCUMENT_EXPORT)"
    production_map_build="$(production_env_value ENABLE_MAP_BUILD)"
    case "${production_documents:-false}:${production_map_build:-false}" in
        true:true|true:false|false:true|false:false) ;;
        *) echo 'ENABLE_DOCUMENT_EXPORT / ENABLE_MAP_BUILD 只能为 true 或 false' >&2; return 1 ;;
    esac
    case "$production_queries" in
        ''|true|false) ;;
        *) echo 'ENABLE_INTELLIGENT_QUERY 只能留空或为 true、false' >&2; return 1 ;;
    esac
    case "${production_roads:-false}" in
        true|false) ;;
        *) echo 'ENABLE_ROAD_ANALYSIS 只能为 true 或 false' >&2; return 1 ;;
    esac
    if [ "$production_roads" = true ]; then
        # Compose override order is significant: base first, runtime second.
        set -- --profile road-analysis --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
            -f "$ROOT_DIR/docker-compose.road-runtime.yml" "$@"
    elif [ "$production_documents" = true ]; then
        set -- --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
            -f "$ROOT_DIR/docker-compose.document-renderer.yml" "$@"
    else
        set -- --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
    if [ "$production_agents" = true ] || [ "$production_queries" = true ]; then
        # Shared queue worker does not enable experimental Lab or a model.
        set -- --profile agent-lab "$@"
    fi
    if [ "$production_map_build" = true ]; then
        set -- --profile map-build "$@"
    fi
    docker compose "$@"
}

# Explicit selection avoids requiring disabled profile images during offline
# preflight. These words are fixed service names, never user-provided arguments.
production_services() {
    printf '%s\n' postgres redis backend celery celery-beat frontend
    if [ "$(production_env_value ENABLE_AGENT_LAB)" = true ] || \
       [ "$(production_env_value ENABLE_INTELLIGENT_QUERY)" = true ]; then
        printf '%s\n' agent-worker
    fi
    [ "$(production_env_value ENABLE_ROAD_ANALYSIS)" != true ] || printf '%s\n' road-worker
    [ "$(production_env_value ENABLE_MAP_BUILD)" != true ] || printf '%s\n' map-worker
}

# Prevent Compose from opportunistically pulling/building after the initial
# image check, including when a local image is removed during deployment.
compose_start() {
    if [ "$(production_env_value DEPLOY_IMAGE_MODE)" = prebuilt ]; then
        compose up --pull never --no-build "$@"
    else
        compose up "$@"
    fi
}

compose_run() {
    if [ "$(production_env_value DEPLOY_IMAGE_MODE)" = prebuilt ]; then
        compose run --pull never "$@"
    else
        compose run "$@"
    fi
}
