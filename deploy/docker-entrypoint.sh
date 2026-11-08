#!/bin/sh
# 容器入口：修正挂载卷属主后以非 root 用户运行。
# 这样宿主机上的 ./data ./output 不会因为容器写文件变成 root 所有。
set -e

mkdir -p /app/data /app/data/logs /app/output /app/input

if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /app/data /app/output /app/input 2>/dev/null || true
    exec gosu appuser "$@"
fi
exec "$@"
