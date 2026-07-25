# task_plan.md — content-pipeline-stack Docker 化项目 (v0)

**项目**: 把 HK 现有 11 个 systemd 服务 + 2 个库,分阶段 docker 化,可独立部署
**目标**: pipeline 服务脱离 openclaw Gateway;跟 Yuxi 双向接口;单 `docker compose up` 在任何 docker host 起完整 stack
**触发**: 吉总 2026-07-25 21:30 「我去 HZ 看了 Yuxi,考虑把 pipeline docker 化,回头可以独立部署」 → 21:52 「脱离 Gateway」 → 22:00 「跟 Yuxi 双向接口」

---

## ✅ 已完成 (本 session 已研究)

| Step | 任务 | 状态 |
|---|---|---|
| 1 | 读 skill: research-loop / docker / mcp-builder | ✅ |
| 2 | SSH HZ 看 Yuxi 架构 + docker-compose 状态 | ✅ (11 容器 healthy) |
| 3 | 深读 Yuxi 关键文件 (mcp_router.py / mcp_service.py) | ✅ (发现 CRUD + streamable_http + MultiServerMCPClient) |
| 4 | 本地读 content-pipeline-mcp (17 tool + StreamableHTTP :18092) | ✅ |
| 5 | 全量盘点 HK 19 systemd + 2 docker (Tier 1-5) | ✅ |
| 6 | 查 OpenClaw Gateway 现状 (PID 989292, RSS 778MB,MemoryMax 5G) | ✅ (已解耦) |
| 7 | 画 v0 设计图 + 双向接口设计 + 4 周实施顺序 | ✅ |
| 8 | 建仓目录 `content-pipeline-stack/` | ✅ |

---

## 🟡 待吉总拍板 (阻塞下一步)

| # | 问题 | 选项 |
|---|---|---|
| 1 | **范围**: 11 真服务 + 2 库全做 / 还是先 P0 4 个 | A: 全做 3 周 / B: P0 1 周出活后迭代 |
| 2 | **库打包**: brand-video-tools + knowledge-distill 跟 worker image 一起 build / 单独 wheel 推 PyPI 私有仓 | A: 一起 / B: wheel |
| 3 | **GPU**: hk-asr 4.8GB FunASR CPU 推理 50-70s/段,做 GPU 版? | A: CPU / B: GPU / C: 两套镜像 |
| 4 | **部署位置**: 完全 HK / 完全 HZ (跟 Yuxi 同机房,延迟低) / 混合 | A: HK / B: HZ / C: 混合 |
| 5 | **仓位置**: `~/.openclaw/workspace/content-pipeline-stack/` (我已建) / v6_pipeline 仓 `docker/` / dashboard-v3-bff 仓 | A: 我建的位置 / B: 子目录 / C: 合并 dashboard |
| 6 | **Yuxi 双向接口范围**: 我建议加 5 个 yuxi_* 反向 tool,够不够? | A: 5 个 / B: 只加 2 个 (search + query_graph) / C: 安妮有别的建议 |
| 7 | **「安妮的建议」具体内容**: 我 memory + context 都没搜到「安妮」 | 需要 Cove 明确 |
| 8 | **Yuxi webhook 改造**: 给 chengxuyuan 提 PR 加 webhook 接收端点 / 用飞书通知代替 | A: PR / B: 飞书 |

---

## 📋 Week 1 — P0 立即可做 (低风险,出活) — 待拍板 #1 启动

| 日 | 任务 | 验收 |
|---|---|---|
| Day 1 | content-pipeline-mcp Dockerfile + docker-compose run (替换 systemd) | `curl /health` 200, `/tools` 返 17 tool, Bearer auth 仍工作 |
| Day 1 | file-service Dockerfile + docker-compose run | 上传 mp4 跟 systemd 行为一致 |
| Day 2 | douyin-recorder 用上游 Dockerfile + 本地 build (config + hook 走 volume) | 启动后录测试直播,产 .mp4 段 |
| Day 3 | v6-monitor Dockerfile + HTTP `/api/run-now` 替代 SIGUSR1 + docker-compose | daemon 6h 循环 + curl 触发立即跑 |
| Day 4 | 起 docker-compose.yml 主栈 (4 服务) + override-staggered.yml + 跟 systemd 并行运行对比 | 行为对齐后停 systemd |

## 📋 Week 2 — P1 重组件 (v6 worker 4 stage + hk-asr)

| 日 | 任务 | 验收 |
|---|---|---|
| Day 1-2 | v6-worker-base (Python 3.12 + torch + ffmpeg + chromium + brand-video-tools + knowledge-distill) | build 成功 ~2.5GB |
| Day 3 | v6-worker-download Dockerfile (FROM base, CMD v6_download_worker.py 0) | 跑一个 aid,产 mp4 |
| Day 3 | v6-worker-transcribe/distill/upload (4 镜像同 base) | 一轮完整 pipeline |
| Day 4 | hk-asr Dockerfile (torch + funasr + Paraformer, 4.8GB) | 推理一条 mp3 50-70s, /health 返 ok |

## 📋 Week 3 — P2 集成 + Yuxi 双向 + 文档

| 日 | 任务 | 验收 |
|---|---|---|
| Day 1 | Yuxi 注册 content-pipeline slug (curl 命令 + 落 DB) | admin 后台看得到,mcp_tools_stats +1 |
| Day 2 | content-pipeline-mcp 新增 yuxi_search_kb / yuxi_query_graph (待拍板 #6) | tools 计数 17 → 19 |
| Day 3 | yuxi-ingest Dockerfile + 跨 docker network 测试 + webhook 推 (待拍板 #8) | ingest 一个 md 入 Yuxi,Yuxi 收到 webhook |
| Day 4 | qdrant-hk + neo4j 进 docker-compose + observability/prometheus + DEPLOY.md + INTEGRATION.md | 独立部署手册 + 集成手册齐全 |

---

## 🎯 第一件事 (拍板 #1 之后立刻)

如果选 A(全做 3 周),**Day 1 第一件事**:写 `services/content-pipeline-mcp/Dockerfile` + `docker-compose.yml` 主栈先起 4 个服务(mcp/file/recorder/monitor)。

如果选 B(P0 1 周),同上但只做 4 个服务,先验证 docker 化可行性。

## 🚧 已知风险 (实施时关注)

| 风险 | 缓解 |
|---|---|
| SQLite queue.db 跨容器共享 | 同一 host volume `/home/main/douyin-data:/data`,铁律 84 WAL 兜底 |
| SIGUSR1 跨 PID namespace 不可靠 | v6-monitor 加 `/api/run-now` HTTP 端点 |
| Cookie jarfile 跨容器 | 同一 host volume `/home/main/douyin-data/cookies` |
| hk-to-hz-asr-tunnel 在容器化后是否需要 | HK 全部署 → 不需要;HZ 部署 → 保留 tunnel |
| Chromium 内存 405MB → 容器需 1536M | 跟 systemd MemoryMax 对齐 |
| 「安妮的建议」待 Cove 明确 | 不凭猜,等明确再扩 yuxi_* tool |

## 📊 验收标准 (Done Definition)

**P0 完成 = 4 服务在 docker-compose.yml 跑起来 + 跟 systemd 并行对比 24h 行为一致 + docker compose down/up 都能恢复 + Prometheus metrics 暴露**

**P1 完成 = 1 轮完整 pipeline (download → transcribe → distill → upload → yuxi-ingest) 在 docker stack 内跑通**

**P2 完成 = 任意 docker host `git clone + docker compose up -d` 5 分钟内起完整 stack + Yuxi 端能看到 mcp_servers +1**

## 📂 文件结构 (计划)

```
content-pipeline-stack/
├── task_plan.md                  # 本文件
├── progress.md                   # 每日进度
├── findings.md                   # 研究发现 (HZ Yuxi, MCP 协议, 现有 systemd)
├── docker-compose.yml            # 主栈 (待拍板后写)
├── docker-compose.d/             # override (待拍板后写)
├── .env.example                  # token / 路径模板
├── services/
│   ├── content-pipeline-mcp/     # Week 1 Day 1
│   ├── file-service/             # Week 1 Day 1
│   ├── douyin-recorder/          # Week 1 Day 2
│   ├── v6-monitor/               # Week 1 Day 3
│   ├── v6-worker-base/           # Week 2 Day 1-2
│   ├── v6-worker-download/       # Week 2 Day 3
│   ├── v6-worker-transcribe/     # Week 2 Day 3
│   ├── v6-worker-distill/        # Week 2 Day 3
│   ├── v6-worker-upload/         # Week 2 Day 3
│   ├── hk-asr/                   # Week 2 Day 4
│   └── yuxi-ingest/              # Week 3 Day 3
├── integrations/
│   └── yuxi/                     # Week 3 (待拍板 #6 #8)
├── observability/                # Week 3 Day 4
└── docs/
    ├── ARCHITECTURE.md           # Week 3 Day 4
    ├── DEPLOY.md                 # Week 3 Day 4
    └── INTEGRATION.md            # Week 3 Day 4
```

## 🔗 关联上下文

- v0 设计图 (前面消息里画的全栈架构 + Yuxi 双向接口图)
- AGENTS.md 铁律 8 (复杂任务必须规划) + 铁律 0 (诚实铁律)
- TOOLS.md 铁律 173 (监控守护单一真源 systemd daemon)
- TOOLS.md 铁律 168.1 (worker_loop signal handler)
- TOOLS.md 铁律 159 (worker_loop exp backoff + max_retries=3)
- TOOLS.md 铁律 158 (pipeline_retry_dead 真 retry 数)
- TOOLS.md 铁律 157 (MemoryMax 256→512M 兜底)
- TOOLS.md 铁律 156 (timeout 600s 系列)
- TOOLS.md 铁律 84 (SQLite WAL 跨 worker 兜底)

## ⏰ 下一步

**等 Cove 拍板 #1-#8**。拍板 #1 (范围) 后,从 `services/content-pipeline-mcp/Dockerfile` 开始。