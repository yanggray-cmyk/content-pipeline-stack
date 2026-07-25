# Dockerfile — v6-monitor
# Python 3.12 daemon — 抖音账号监控, SQLite state.db + accounts.json
# Only stdlib + from douyin_api import fetch_user_posts (绑 brand-video-tools/scripts)
# systemd: v6-monitor.service (PID 936492, --daemon --interval 21600)
#
# 关键点:
#   1. 容器跑一次 --once 而非 daemon (docker compose restart 接管 loop)
#   2. v6_monitor.py 需要 from douyin_api import (P1 库 brand-video-tools)
#      → bind mount /home/main/.openclaw/workspace/skills/brand-video-tools
#   3. v6_monitor.py 需要 from v6_enqueue import (兄弟模块)
#      → bind mount /home/main/douyin-data/scripts/v6_pipeline (整个目录)
#   4. WORKDIR=/home/main/douyin-data (跟 systemd 一致, 读写 state.db + accounts.json)
#   5. 无 healthcheck (无 HTTP 端点) — 验证靠 docker inspect + SIGUSR1

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="content-pipeline/v6-monitor"
LABEL org.opencontainers.image.description="Douyin account monitor daemon (铁律 143/152/173)"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"

# curl 仅用于 docker exec 健康检查 / 调试
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/main/douyin-data/scripts/v6_pipeline

# 只装 v6_monitor.py (单文件, 双 import: douyin_api + v6_enqueue 通过 sys.path.insert)
COPY v6_monitor.py ./

# 注意: container 自己只放 v6_monitor.py,兄弟模块 + 库通过 bind mount 提供
#   /home/main/douyin-data/scripts/v6_pipeline (含 v6_enqueue.py + enqueue_target)
#   /home/main/.openclaw/workspace/skills/brand-video-tools (含 douyin_api.py)
# 这样 source-of-truth 还是 host 磁盘, 容器只是 Python 解释器

# Non-root: bind mount 需要 main user (uid 1001) 写权限
# image 内建 monitor user (uid 1001) 跟 host main 对齐
RUN useradd -u 1001 -m -d /home/monitor -s /bin/bash monitor && \
    mkdir -p /home/main/douyin-data && \
    chown -R monitor:monitor /home/main && \
    # 给容器 view 整个 host 磁盘的权限 (read paths via bind)
    chmod 755 /home /home/main

USER 1001:1001

# 无 EXPOSE — v6-monitor 是 daemon, 无 HTTP 端口 (跟 systemd 行为一致)

# Default: --daemon --interval 21600 (跟 systemd ExecStart 完全一致)
# SIGUSR1 验证 = docker kill --signal SIGUSR1 <container>
# SIGTERM clean shutdown (docker stop 会优雅收 SIGTERM, v6_monitor 退出)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "v6_monitor.py", "--daemon", "--interval", "21600"]