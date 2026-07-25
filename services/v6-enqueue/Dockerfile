# v6-enqueue — 把 download_list.json pending 一次性 LPUSH 到 download queue
# Build context: ./services/v6-enqueue (本目录)
# Dockerfile FROM v6-base (避免重复层)
#
# 用法:
#   docker build -t ghcr.io/main-1/content-pipeline/v6-enqueue:0.1.0 \
#       -f Dockerfile ../v6-base
#
# 设计:
#   - 不放源码, host bind /home/main/douyin-data (含 v6_pipeline 脚本目录)
#   - 不放 accounts.json (host bind)
#   - 不写状态 (只读 read download_list.json + state.db)
#
# 跟 systemd 行为对齐:
#   - WORKDIR=/home/main/douyin-data
#   - 调 v6_enqueue.py from cron */15 (跟 systemd 一致)
#
# 关键:
#   - 容器只跑 python 解释器
#   - 改 v6_enqueue.py 不用 rebuild, restart 即可
#   - 共享 v6-base image (5 worker 一致 Python 版本)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# ENTRYPOINT 复用 base 的 tini
ENTRYPOINT ["/usr/bin/tini", "--"]

# 默认空跑 (实际由 cron 调 docker run --rm 或 systemd timer 启)
# 容器模式可改: docker compose run --rm v6-enqueue
CMD ["python", "-c", "import sys; sys.path.insert(0, '/data/scripts/v6_pipeline'); import v6_enqueue; print('v6-enqueue OK')"]