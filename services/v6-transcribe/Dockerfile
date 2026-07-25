# v6-transcribe — HK ASR 转录音频 (消费者 queue.transcribe, 写 transcripts/)
#
# 设计:
#   - 持续 worker_loop 跑
#   - 调 hk-asr http://host.docker.internal:18200/transcribe
#   - 写 /home/main/douyin-data/transcripts/{aid}.{md,srt,asr.json}
#
# 关键:
#   - host.docker.internal 让容器访问 host 网络 (跟 docker run 默认 bridge)
#   - 改 HK ASR URL 用环境变量 HK_ASR_URL 覆盖
#
# 内存: 256MB (调 HK ASR 自己, 不在本机跑模型)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# Health check: 验证 HK ASR 联通 (经 host.docker.internal)
HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD curl -sf "${HK_ASR_URL:-http://host.docker.internal:18200}/health" || exit 1

ENV HK_ASR_URL=http://host.docker.internal:18200

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "-u", "/home/main/douyin-data/scripts/v6_pipeline/v6_transcribe_worker.py"]