#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
CALLER_DIR="$(pwd -P)"
MAP_BUNDLE_FILE="${MAP_BUNDLE_FILE:-}"

[ -n "$MAP_BUNDLE_FILE" ] || {
    echo "必须通过 MAP_BUNDLE_FILE 指定已经深度验包的真实公共地图 ZIP" >&2
    exit 1
}
case "$MAP_BUNDLE_FILE" in
    /*) ;;
    *) MAP_BUNDLE_FILE="$CALLER_DIR/${MAP_BUNDLE_FILE#./}" ;;
esac
[ -r "$MAP_BUNDLE_FILE" ] || {
    echo "离线地图包不可读: $MAP_BUNDLE_FILE" >&2
    exit 1
}

timestamp="$(date '+%Y%m%d-%H%M%S')-$$"
EVIDENCE_FILE="${EVIDENCE_FILE:-$ROOT_DIR/output/release-gates/v36-competition-demo-${timestamp}.json}"
case "$EVIDENCE_FILE" in
    /*) ;;
    *) EVIDENCE_FILE="$ROOT_DIR/${EVIDENCE_FILE#./}" ;;
esac
mkdir -p "$(dirname -- "$EVIDENCE_FILE")"

cd "$ROOT_DIR/backend"
PYTHONPATH=. venv/bin/python -m app.release_checks.competition_v36 \
    --bundle "$MAP_BUNDLE_FILE" \
    --evidence "$EVIDENCE_FILE" \
    --runs 5 >/dev/null

echo "v3.6 五轮自动业务链路竞赛彩排通过，证据文件: $EVIDENCE_FILE"
