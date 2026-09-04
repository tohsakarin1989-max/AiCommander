#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.production}"

command -v openssl >/dev/null 2>&1 || {
    echo "缺少 openssl，无法生成生产密钥" >&2
    exit 1
}

if [ ! -f "$ENV_FILE" ]; then
    cp "$ROOT_DIR/.env.production.example" "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
    echo "已创建 ${ENV_FILE}，请修改 APP_DOMAIN 后再部署"
fi

configured_secrets_dir="$(sed -n 's/^SECRETS_DIR=//p' "$ENV_FILE" | tail -1)"
configured_secrets_dir="${configured_secrets_dir:-./secrets}"
case "$configured_secrets_dir" in
    /*) SECRETS_DIR="$configured_secrets_dir" ;;
    *) SECRETS_DIR="$ROOT_DIR/${configured_secrets_dir#./}" ;;
esac

mkdir -p "$SECRETS_DIR"
chmod 0700 "$SECRETS_DIR"

create_secret() {
    name="$1"
    bytes="$2"
    path="$SECRETS_DIR/$name"
    if [ -e "$path" ]; then
        echo "保留已有密钥: $path"
        return
    fi
    openssl rand -hex "$bytes" > "$path"
    chmod 0600 "$path"
    echo "已生成密钥: $path"
}

create_secret db_password 24
create_secret redis_password 24
create_secret secret_key 32
create_secret bootstrap_token 32

echo "生产配置初始化完成。下一步编辑 ${ENV_FILE}，并妥善离线备份 secrets 目录。"
