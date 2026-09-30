#!/bin/sh
# Shared by deployment, preflight and backup. Never source the configuration file.
production_env_value() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

compose() {
    production_roads="$(production_env_value ENABLE_ROAD_ANALYSIS)"
    production_agents="$(production_env_value ENABLE_AGENT_LAB)"
    production_queries="$(production_env_value ENABLE_INTELLIGENT_QUERY)"
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
    else
        set -- --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
    if [ "$production_agents" = true ] || [ "$production_queries" = true ]; then
        # Shared queue worker does not enable experimental Lab or a model.
        set -- --profile agent-lab "$@"
    fi
    docker compose "$@"
}
