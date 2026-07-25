# Dockerfile — v6-monitor
# Python 3.12 daemon — 抖音账号监控,SQLite state.db + accounts.json
# Only uses stdlib (argparse, asyncio, sqlite3, json, signal, time, ...)
# systemd: v6-monitor.service (PID 936492, --daemon --interval 21600)

FROM python:3.12-slim AS runtime

# Labels
LABEL org.opencontainers.image.title="content-pipeline/v6-monitor"
LABEL org.opencontainers.image.description="Douyin account monitor daemon (铁律 143/152)"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"

# Healthcheck script: curl /health endpoint (HTTP API replacement for SIGUSR1)
# 容器跑一个 minimal HTTP wrapper,expose 18199,GET /run-now 触发 daemon 重跑
# (现有 v6_monitor.py 是 SIGUSR1 → 我们在 entrypoint 加 HTTP 监听)
# 但当前阶段先不做 — healthcheck 直接看进程在没在
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Workdir matches systemd WorkingDirectory=/home/main/douyin-data/scripts/v6_pipeline
WORKDIR /home/main/douyin-data/scripts/v6_pipeline

# Copy v6_monitor.py + monitor/ scripts (only Python stdlib needed)
COPY v6_monitor.py ./
COPY monitor/ ./monitor/ 2>/dev/null || true

# Non-root: image ships 'www-data' or create 'monitor' user (uid 1001 to avoid node 1000)
RUN useradd -u 1001 -m -d /home/monitor -s /bin/bash monitor 2>/dev/null || true

# Note: 这个 service 需要写 /home/main/douyin-data/* (state.db, download_list.json)
# 不能 USER monitor — main 用户 UID 1000 写权限最简单
# 容器跑 root,只 host mount bind,权限跟 host 一致

USER root

# No EXPOSE — v6-monitor 无 HTTP 端点(后续 P1 加 /api/run-now)
# systemd 容器版:无端口暴露,纯 daemon + SIGUSR1 (docker kill -s SIGUSR1 <id>)

# Default: --daemon --interval 21600 (6h) 跟 systemd ExecStart 完全一致
CMD ["python3", "v6_monitor.py", "--daemon", "--interval", "21600"]