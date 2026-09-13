#!/bin/sh
# Read-only capability preflight; never starts a database or pulls an image.
set -eu
postgres_candidate="${1:-}"
case "$postgres_candidate" in
    sha256:*) postgres_digest="${postgres_candidate#sha256:}" ;;
    *@sha256:*) postgres_digest="${postgres_candidate##*@sha256:}" ;;
    *) echo 'POSTGIS_IMAGE 必须为已导入镜像的不可变 sha256 摘要' >&2; exit 1 ;;
esac
case "$postgres_digest" in
    *[!0-9a-f]*|'') echo '数据库镜像摘要格式错误' >&2; exit 1 ;;
esac
[ "${#postgres_digest}" -eq 64 ] || { echo '数据库镜像摘要长度错误' >&2; exit 1; }
docker image inspect "$postgres_candidate" >/dev/null 2>&1 \
    || { echo '数据库镜像尚未导入；预检不会联网下载' >&2; exit 1; }
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --memory 128m --cpus 1 --pids-limit 32 \
    --entrypoint sh "$postgres_candidate" -c '
      for directory in /usr/share/postgresql/extension /usr/share/postgresql/16/extension /usr/local/share/postgresql/extension; do
        if [ -r "$directory/postgis.control" ] && [ -r "$directory/vector.control" ]; then exit 0; fi
      done
      echo "数据库镜像必须同时包含 PostGIS 和 pgvector 扩展文件" >&2
      exit 1
    '
