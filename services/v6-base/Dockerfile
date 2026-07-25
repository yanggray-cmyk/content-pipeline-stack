# v6-base — 共享 base image for 5 v6 worker services
# 构建: docker build -t ghcr.io/main-1/content-pipeline/v6-base:0.1.0 -f Dockerfile ../..
#
# 5 worker 共享:
#   - v6-enqueue / v6-download / v6-transcribe / v6-distill / v6-upload
#
# 设计:
#   - python:3.11.15-slim (~150MB)
#   - 安装 pip 依赖 (requests, urllib3)
#   - WORKDIR /app
#   - 不放源码 (源码 host bind, 容器只跑 Python 解释器)
#
# 关键: 容器只跑 Python 解释器, 源码/数据 都在 host
# 优势:
#   - 1 个 base image, 5 worker 共享 (~200MB), 跟 systemd 同源
#   - 改源码不用 rebuild image, restart worker 即可
#   - 多 worker 共享同一份 queue.db + transcripts

FROM python:3.11.15-slim

LABEL maintainer="main-agent" \
      description="v6 worker base — shared image for 5 v6 pipeline workers (enqueue/download/transcribe/distill/upload)" \
      version="0.1.0"

# tini 转发 SIGTERM/SIGUSR1 (跟 v6-monitor 一致)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/*

# pip 依赖 (跟 systemd worker 一致, 避免行为漂移)
RUN pip install --no-cache-dir \
        requests \
        urllib3

# 健康检查用 (5 worker 用同一个 base, 不同 service health check 不同)
# 实际 health check 在各 service Dockerfile 覆盖

WORKDIR /app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "--version"]