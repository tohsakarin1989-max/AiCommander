#!/bin/sh
set -eu

load_secret() {
    variable_name="$1"
    file_path="$2"
    if [ ! -r "$file_path" ]; then
        echo "missing required secret file: $file_path" >&2
        exit 1
    fi
    value="$(cat "$file_path")"
    if [ -z "$value" ]; then
        echo "empty required secret: $variable_name" >&2
        exit 1
    fi
    export "$variable_name=$value"
}

umask 077

if [ -z "${SECRET_KEY:-}" ]; then
    load_secret SECRET_KEY "${SECRET_KEY_FILE:-/run/secrets/secret_key}"
fi

if [ -r "${BOOTSTRAP_TOKEN_FILE:-/run/secrets/bootstrap_token}" ]; then
    BOOTSTRAP_TOKEN="$(cat "${BOOTSTRAP_TOKEN_FILE:-/run/secrets/bootstrap_token}")"
    export BOOTSTRAP_TOKEN
fi

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-aicommander}"
DB_USER="${DB_USER:-aicommander}"
REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"

if [ -z "${DATABASE_URL:-}" ]; then
    load_secret DB_PASSWORD "${DB_PASSWORD_FILE:-/run/secrets/db_password}"
    # 生产初始化脚本只生成十六进制密码，因此可安全放入连接 URL。
    export DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
fi

if [ -z "${REDIS_URL:-}" ]; then
    load_secret REDIS_PASSWORD "${REDIS_PASSWORD_FILE:-/run/secrets/redis_password}"
    export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0"
fi
export CELERY_BROKER_URL="$REDIS_URL"
export CELERY_RESULT_BACKEND="$REDIS_URL"

exec "$@"
