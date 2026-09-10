#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
MAP_BUNDLE_FILE="${MAP_BUNDLE_FILE:-}"

[ -f "$ENV_FILE" ] || {
    echo "缺少 ${ENV_FILE}，无法执行离线地图发布验收" >&2
    exit 1
}
[ -n "$MAP_BUNDLE_FILE" ] || {
    echo "必须通过 MAP_BUNDLE_FILE 指定一个真实的公共地图离线包" >&2
    exit 1
}
[ -r "$MAP_BUNDLE_FILE" ] || {
    echo "离线地图包不可读: $MAP_BUNDLE_FILE" >&2
    exit 1
}

case "$MAP_BUNDLE_FILE" in
    /*) ;;
    *) MAP_BUNDLE_FILE="$ROOT_DIR/${MAP_BUNDLE_FILE#./}" ;;
esac

read_env() {
    sed -n "s/^$1=//p" "$ENV_FILE" | tail -1
}

fail() {
    echo "离线地图发布验收失败: $*" >&2
    exit 1
}

compose() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

database_name="$(read_env DB_NAME)"
case "$database_name" in
    aicommander_v36_verify_*|aicommander_postgis_verify_*) ;;
    *) fail "只允许在一次性验证数据库运行，当前 DB_NAME=$database_name" ;;
esac

backend_id="$(compose ps -q backend)"
[ -n "$backend_id" ] || fail "后端容器未运行"
network_isolation=passed
for network in $(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$backend_id"); do
    internal="$(docker network inspect --format '{{.Internal}}' "$network")"
    [ "$internal" = "true" ] || fail "后端连接了非隔离网络: $network"
done

timestamp="$(date '+%Y%m%d-%H%M%S')"
TMP_ROOT="${TMPDIR:-/tmp}"
WORK_DIR="$(mktemp -d "$TMP_ROOT/aicommander-offline-map-check.XXXXXX")"
EVIDENCE_FILE="${EVIDENCE_FILE:-$ROOT_DIR/outputs/release-evidence/offline-map-v36-${timestamp}.json}"
cleanup() {
    case "$WORK_DIR" in
        "$TMP_ROOT"/aicommander-offline-map-check.*) rm -rf -- "$WORK_DIR" ;;
    esac
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

compose run --rm --no-deps \
    -v "$MAP_BUNDLE_FILE:/tmp/v36-map-bundle.zip:ro" \
    backend python -m app.release_checks.offline_map_v36 \
    --bundle /tmp/v36-map-bundle.zip --retain-artifact > "$WORK_DIR/result.json"

mkdir -p "$(dirname -- "$EVIDENCE_FILE")"
umask 077
{
    printf '{\n'
    printf '  "verified_at": "%s",\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '  "network_isolation": "%s",\n' "$network_isolation"
    printf '  "result": '
    cat "$WORK_DIR/result.json"
    printf '}\n'
} > "$EVIDENCE_FILE"
chmod 0600 "$EVIDENCE_FILE"

cleanup
trap - EXIT HUP INT TERM

echo "离线地图导入、断网运行、地图版本和回滚验收通过，证据文件: $EVIDENCE_FILE"
