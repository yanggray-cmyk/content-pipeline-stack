# v6-download — 下载抖音视频 (消费者 queue.download, 写 mp4 + queue.transcribe)
#
# 设计:
#   - 持续 worker_loop 跑 (systemd 一样)
#   - bind /home/main/douyin-data (queue.db + videos/)
#   - bind /home/main/DouyinLiveRecorder/downloads (read mp4, systemd 写 mp4)
#   - chromium browser fallback (铁律 168 cookie 监控 + fallback)
#
# chromium 设计:
#   - apt install chromium 5+ min (200+ 依赖)
#   - 改 host bind /home/main/.cache/ms-playwright (host 已有 chromium)
#   - 容器只装 playwright python lib (调 chromium API)
#
# 内存: 1.5GB (chromium 405MB + worker + buffer, 跟 systemd MemoryMax=1536M 对齐)
# CPU: 1 核 (download 慢在 douyin 网络响应)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# playwright python lib (调 chromium API, chromium 本身用 host bind)
RUN pip install --no-cache-dir \
        playwright

# Health check: 验证 queue.db 可读 + chromium 可调
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3, os; sqlite3.connect('/data/queue.db').close(); assert os.path.isdir('/ms-playwright'), 'chromium not bind'; print('OK')" || exit 1

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

ENTRYPOINT ["/usr/bin/tini", "--"]

# 持续 worker_loop 跑 (跟 systemd 一样)
CMD ["python", "-u", "-m", "v6_pipeline.v6_download_worker"]