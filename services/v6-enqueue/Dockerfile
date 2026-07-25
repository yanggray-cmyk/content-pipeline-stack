# v6-enqueue — 把 download_list.json pending 一次性 LPUSH 到 download queue
#
# 设计: cron 驱动,不常驻
#   docker compose run --rm v6-enqueue \
#       python -u /home/main/douyin-data/scripts/v6_pipeline/v6_enqueue.py
#
# 容器启动后默认 sleep infinity (等待手动触发),健康检查通过
# 实际入队由 host cron 触发:
#   5 * * * * docker compose -f /path/docker-compose.yml run --rm v6-enqueue \
#       python -u /home/main/douyin-data/scripts/v6_pipeline/v6_enqueue.py
#
# 共享 v6-base image (跟 4 worker 一致 Python 版本)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# 健康检查: 验证 queue.db 可写 (跟 systemd cron */5 对齐)
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('/data/queue.db').close(); print('queue.db OK')" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# 默认 sleep infinity, 等 cron 触发 docker compose run
CMD ["sleep", "infinity"]