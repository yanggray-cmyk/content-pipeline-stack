# v6-distill — LLM 蒸馏 KB 卡片 (消费者 queue.distill, 写 knowledge-base/)
#
# 设计:
#   - 持续 worker_loop 跑
#   - 调 distill-llm.py (KIMI K3 → 火山 GLM-5.2 → 火山 Doubao → DeepSeek v4)
#   - 写 /home/main/douyin-data/knowledge-base/{domain}/{aid}.md
#
# 关键:
#   - LLM API key 经 host 环境变量 (compose env_file)
#   - 改 KB domain 路由用 KB_DATA_DIR env 覆盖
#
# 内存: 256MB (调 LLM API 自己, 不在本机跑模型)

FROM ghcr.io/main-1/content-pipeline/v6-base:0.1.0

# Health check: 验证 queue.db 可写 (kb data dir 共享)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os; os.makedirs(os.environ.get('KB_DATA_DIR', '/data/knowledge-base'), exist_ok=True); print('KB dir OK')" || exit 1

ENV KB_DATA_DIR=/data/knowledge-base

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "-u", "-m", "v6_pipeline.v6_distill_worker"]