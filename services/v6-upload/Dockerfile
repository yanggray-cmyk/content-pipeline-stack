# v6-upload — 上传到 file-service (消费者 queue.upload, 写 uploads/)
#
# 设计:
#   - 持续 worker_loop 跑
#   - 调 file-service http://host.docker.internal:18098/upload
#   - 写 /home/main/douyin-data/uploads-migrated/...
#
# 关键:
#   - host.docker.internal 让容器访问 host 网络 (跟 docker run 默认 bridge)
#   - 改 file-service URL 用环境变量 FILE_SERVICE_URL 覆盖
#
# 内存: 256MB (curl multipart upload)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# Health check: 验证 file-service 联通 + python worker 在走 (不创 uploads/ 不靠谱)
# 铁律 179 (2026-07-26 12:18 Cove 拍板根治): bookworm-slim 不预装 pgrep, 用 /proc cmdline 自检
HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -sf "http://${FILE_SERVICE_URL_HOST:-file-service}:${FILE_SERVICE_PORT:-18098}/health" && \
        python -c "import os; [exit(0) for p in os.listdir('/proc') if p.isdigit() and b'v6_upload_worker.py' in open(f'/proc/{p}/cmdline','rb').read()]; exit(1)" || exit 1

ENV FILE_SERVICE_URL=http://host.docker.internal:18098

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "-u", "/home/main/douyin-data/scripts/v6_pipeline/v6_upload_worker.py"]