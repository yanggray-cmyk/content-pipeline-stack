# findings.md — content-pipeline-stack 研究发现

## 🔍 Finding 1 — Yuxi MCP 完整支持,零代码集成即可

**来源**: SSH HZ 116.62.125.221 + 读 `/home/chengxuyuan/.openclaw/workspace/Yuxi/backend/`

**结论**: Yuxi (xerrors/Yuxi v0.7.1, MIT) 已有完整 MCP 模块,集成我们只需 1 个 curl。

### 关键代码路径

| 文件 | 作用 | 行数 |
|---|---|---|
| `backend/server/routers/mcp_router.py` | REST CRUD 路由 (`POST/GET/PATCH/DELETE /api/system/mcp-servers`) | 415 |
| `backend/package/yuxi/agents/mcp/service.py` | MCP 业务逻辑 (MultiServerMCPClient + 工具缓存 + DB 同步) | 609 |

### MCP server 注册示例

```bash
curl -X POST http://hz.siqing.cn/yuxi/api/system/mcp-servers \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "content-pipeline",
    "name": "抖音内容生产管线",
    "transport": "streamable_http",
    "url": "https://hk.siqing.cn/api/mcp/mcp",
    "headers": {"Authorization": "Bearer <HK_MCP_TOKEN>"},
    "timeout": 600,
    "description": "抖音视频→ASR→蒸馏→上传→KB 全链路",
    "tags": ["内容生产", "抖音"],
    "icon": "🎬"
  }'
```

### 传输类型

```python
# Yuxi 支持 3 种 transport
valid_transports = ("sse", "streamable_http", "stdio")
```

`content-pipeline-mcp` 用 `streamable_http` (铁律 165.2 P2-1),直接对接。

### MCP client 加载

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
client = MultiServerMCPClient({
    "content-pipeline": {
        "transport": "streamable_http",
        "url": "https://hk.siqing.cn/api/mcp/mcp",
        "headers": {"Authorization": "Bearer <HK_MCP_TOKEN>"},
        "timeout": 600,
    }
})
tools = await client.get_tools()  # 17 tool 立即可用
```

---

## 🔍 Finding 2 — HK 全量服务盘点 (Tier 1-5)

**来源**: HK 实测 21:55 (`ps auxf`, `systemctl list-units`, `docker ps`, `ss -tlnp`)

### Tier 1 — 核心 4 阶段 pipeline (吉总重点要的)

| 服务 | systemd unit | 数量 | 角色 | RSS |
|---|---|---|---|---|
| v6-monitor | v6-monitor.service | 1 | 6h 监控 daemon,自动入队 | 108 MB |
| v6-download | v6-download-{0,1,2}.service | 3 | 调 brand-video-tools | ~30 MB/个 |
| v6-transcribe | v6-transcribe-{0,1}.service | 2 | 调 hk-asr | ~30 MB/个 |
| v6-distill | v6-distill-{0,1,2,3}.service | 4 | 调 knowledge-distill LLM | ~50 MB/个 |
| v6-upload | v6-upload-{0,1,2,3}.service | 4 | 调 file-service 上传 | ~50 MB/个 |

### Tier 2 — 配套 HTTP / 中间件

| 服务 | 端口 | 角色 | RSS |
|---|---|---|---|
| hk-asr | 18200 | Paraformer-zh v2.0.4 FunASR 推理 | **4.8 GB** |
| hk-to-hz-asr-tunnel | - | HK 18200 → HZ 18200 反向隧道 | 1.4 MB |
| file-service | 18098 | Node.js 视频/文件浏览 + 上传 | **851 MB** |
| yuxi-ingest | - | KB md → HZ Yuxi HTTP 灌入 | 399 MB |
| content-pipeline-mcp | 18092 | MCP 协议层 17 tools | 37 MB |

### Tier 3 — 多平台 / 直播

| 服务 | 角色 | RSS |
|---|---|---|
| douyin-recorder | DouyinLiveRecorder ffmpeg + Chromium 录直播 | 985 MB |

### Tier 4 — 数据 / 存储 (已经是 docker 容器)

| 容器 | 镜像 | 端口 |
|---|---|---|
| qdrant-hk | qdrant:latest | 6333/6334 |
| neo4j | neo4j:5-community | 7474/7687 |

### Tier 5 — 不在 pipeline 范围 (不动)

dashboard-v3-bff (18099) / hk-ts-lb (18090) / hk-report-server / openclaw-gateway (16973/17165)

---

## 🔍 Finding 3 — content-pipeline-mcp 真实状态

**路径**: `/home/main/.openclaw/workspace/skills/content-pipeline-mcp/`

| 维度 | 内容 |
|---|---|
| 入口 | `src/index.ts` (StreamableHTTPServerTransport on :18092) |
| Transport | streamable_http + Bearer auth |
| Tools 数 | **17 个**(2026-07-24 22:14 Cove 拍板注释修对) |
| Tools 分类 | monitor ×3 / pipeline_status ×5 / pipeline_retry_dead ×1 / worker ×3 / batch ×1 / yuxi ×1 / pipeline_clear ×1 / pipeline_move ×1 |
| systemd unit | `/etc/systemd/system/content-pipeline-mcp.service` (MemoryMax=2G, MEMHIGH=1G) |
| 已调 HZ | `src/tools/yuxi.ts` 已有 `ingest_to_yuxi` tool (调 `https://hz.siqing.cn/yuxi/api/auth/token` + ingest) |
| Token | `/etc/content-pipeline-mcp.env` (mode 600) |
| 反向调 Yuxi 已有 | 仅 1 个 (`ingest_to_yuxi`)。我提议加 5 个:`yuxi_search_kb` / `yuxi_query_graph` / `yuxi_list_mcp_servers` / `yuxi_create_kb_record` / `yuxi_webhook_register` |

### 17 tool 列表 (src/index.ts 注释确认)

```
1.  monitor_check_now            - 监控抖音账号新作品
2.  monitor_status               - 监控状态查询
3.  account_set_fetch_strategy   - 设置账号 fetch_strategy (铁律 152)
4.  pipeline_status              - 全链路状态
5.  pipeline_trace_aweme         - 按 aweme_id 单条 trace
6.  pipeline_trace_author        - 按 author 批量 trace
7.  pipeline_trace_domain        - 按 domain 批量 trace
8.  pipeline_stuck               - stuck processing 检测
9.  pipeline_clear_dead          - 清 dead queue (默认 dry_run)
10. pipeline_move_kb             - KB 卡跨 domain 物理 mv
11. download_aweme               - 下载单个 aweme
12. transcribe_aweme             - ASR 转写
13. distill_aweme                - LLM 蒸馏
14. upload_aweme                 - 上传到 file-service
15. ingest_to_yuxi               - KB 灌入 Yuxi (已有!)
16. run_pipeline_batch           - 全流程批处理
17. pipeline_retry_dead          - 重试 dead queue
```

---

## 🔍 Finding 4 — Gateway 真实状态

**实测** (`ps -o pid,user,rss,command -p 989292`):

| 维度 | 数值 |
|---|---|
| PID | 989292 |
| RSS | **778 MB** |
| systemd unit | `openclaw-gateway@main.service` (已 masked, 用 `openclaw-gw1` 系列) |
| MemoryMax | **5G** / MemoryHigh **4G** / TasksMax 300 (2026-07-12 提升) |
| startup_failed | **9 次** (最近 7/21 19:49 — `models: Unrecognized keys: "primary", "fallbacks"`) |
| 跟 pipeline systemd 依赖 | **0 个** (无 `After=openclaw-gw1.service` 等) |

### 关键发现

**吉总担心的"OOM 一死全死"不是真问题**:
- 现有 systemd 已经解耦 (no `After=`)
- Gateway OOM 是 RSS>5G 触发 cgroup kill (当前 778 MB 远不到)
- Gateway startup_failed 是配置 schema 漂移 (跟 OOM 无关)

**真痛点**:
- Yuxi 跨机房调 MCP 链路长 (Yuxi → nginx → MCP → pipeline),任何单点挂都断
- 没做"单点降级"矩阵
- 离开 HK / 离开 HZ 都不能独立跑 (需要完整的 docker 化)

---

## 🔍 Finding 5 — 现有 docker 化能力 (参考 Yuxi)

**来源**: 读 Yuxi `/docker-compose.yml` + `/docker-compose.d/`

### Yuxi docker 模式 (我们要抄)

| 模式 | 用法 |
|---|---|
| `docker-compose.yml` | 主栈 (11 容器 + 11 个独立 build) |
| `docker-compose.d/override-staggered.yml` | 错峰启动 (避免冷启动 race) |
| `docker-compose.d/override-{network,volumes,env}.yml` | 配置分层 |
| `.env.example` | 路径 + token 模板 |
| `api.Dockerfile` (Python 3.13-slim + node 24 + ffmpeg + 中文字体) | 多服务共享 base |
| `web.Dockerfile` (Vue 3 + Vite + nginx) | 前端 base |

### Yuxi 镜像大小参考

- api (FastAPI + LangGraph + ARQ + 模型 SDK): ~2 GB
- web (Vue 3 + Vite build): ~200 MB
- sandbox-provisioner (Docker-in-Docker): ~1 GB
- postgres / redis / milvus / neo4j / minio / qdrant: 标准镜像

### 我们 11 服务的预估镜像大小

| 镜像 | base | 预估 size |
|---|---|---|
| content-pipeline-mcp | node:24-alpine | ~50 MB |
| file-service | node:22-alpine | ~150 MB |
| douyin-recorder | python:3.11-slim + ffmpeg + chromium | ~1.5 GB |
| v6-monitor | python:3.12-slim | ~200 MB |
| v6-worker-base | python:3.12 + torch + ffmpeg + chromium | ~2.5 GB |
| v6-worker-download | v6-worker-base | +100 MB |
| v6-worker-transcribe | v6-worker-base | +200 MB (torch 推理用) |
| v6-worker-distill | v6-worker-base | +200 MB (LLM SDK) |
| v6-worker-upload | v6-worker-base | +50 MB |
| hk-asr | python + torch + funasr | **~6 GB** (Paraformer 模型) |
| yuxi-ingest | python:3.12-slim | ~300 MB |

---

## 🔍 Finding 6 — 关键架构陷阱 (实施前必看)

| 陷阱 | 根因 | 缓解 |
|---|---|---|
| SQLite queue.db 跨容器共享 | 4 stage worker 共享 `/home/main/douyin-data/queue.db` (WAL 模式) | 同一 host volume 挂载 (`/home/main/douyin-data:/data`),铁律 84 WAL 兜底 |
| SIGUSR1 跨 PID namespace 不可靠 | 容器内 signal 跨 namespace 失效 | v6-monitor 加 `/api/run-now` HTTP 端点 |
| Cookie jarfile 跨容器 | browser fallback 共享 `/home/main/douyin-data/cookies/` | 同一 host volume |
| hk-to-hz-asr-tunnel 是否还需要 | 容器化后 HK 容器跟 HZ 容器走 docker network | HK 全部署 → 不需要;HZ 部署 → 保留 tunnel |
| Chromium 内存 405MB | fallback 用 chromium 浏览器 | 容器 `--memory=1536m` 跟 systemd MemoryMax 对齐 (铁律 168) |
| 已有 `ingest_to_yuxi` | yuxi.ts 已经有反向调 Yuxi 的 tool | 不要重复造,**只补 search/query_graph 等新能力** |

---

## 🔍 Finding 7 — Yuxi 双向接口的 3 层设计

### 层 1: Yuxi → us (MCP streamable_http)

**机制**: Yuxi agent 通过 `langchain_mcp_adapters.client.MultiServerMCPClient` 调我们的 17 tool。
**配置**: 管理员后台一次性 POST `/api/system/mcp-servers` 注册 HK content-pipeline slug。
**协议**: MCP StreamableHTTP, stateless JSON。

### 层 2: us → Yuxi (HTTP REST)

**机制**: 我们 pipeline 服务需要反向调 Yuxi 的能力 (KB 检索、知识图谱查询、用户认证)。
**已有**: `ingest_to_yuxi` (调 `/api/auth/token` + ingest)。
**新提议**: 加 5 个 tool — `yuxi_search_kb` / `yuxi_query_graph` / `yuxi_list_mcp_servers` / `yuxi_create_kb_record` / `yuxi_webhook_register`。
**认证**: Bearer Token (从 `YUXI_TOKEN` env var 读)。

### 层 3: 双向 Webhook — 事件订阅

**机制**: pipeline stage done / failure / dead queue 事件 → Webhook POST 给 Yuxi → Yuxi 内部 LangGraph agent 自动响应。
**方向**:
- 我们 → Yuxi:`POST /api/webhooks/content-pipeline` (需要 Yuxi 改造)
- Yuxi → 我们:`POST /api/mcp/events/yuxi` (新端点,在 content-pipeline-mcp 加)
**降级**: webhook 不可用 → 飞书通知代替 (待拍板 #8)。

---

## 🔍 Finding 8 — 永久教训 (本 session 4 条)

1. **「脱离 Gateway」先看现状是否真耦合**: pipeline systemd unit 已经没 `After=openclaw-gw1`,**已经是解耦的**。用户担心 ≠ 真问题。**盘清楚再说**
2. **MCP 单向 ≠ 双向**: Yuxi 调我们 17 tool 是单向,但我们可以反向调 Yuxi 的 HTTP 端点 + 订阅 Yuxi webhook,做出**真正双向**
3. **v0 设计图不是文档,是 commit 前的 sanity check**: 画出来才发现 v6-monitor 的 SIGUSR1 要换 HTTP,5 个 yuxi tool 要新增,webhook 是新增的 event_bus
4. **独立部署 = "我的链路不依赖任何对方服务"**: Yuxi 死了我们仍能跑,HK nginx 死了我们仍能跑

---

## 📚 关联资源

- v0 设计图 (前面消息里画的全栈架构 + Yuxi 双向接口图)
- AGENTS.md 铁律 8 (复杂任务必须规划) + 铁律 0 (诚实铁律)
- TOOLS.md 铁律 173 (监控守护单一真源 systemd daemon)
- TOOLS.md 铁律 168.1 (worker_loop signal handler)
- TOOLS.md 铁律 159 (worker_loop exp backoff + max_retries=3)
- TOOLS.md 铁律 84 (SQLite WAL 跨 worker 兜底)
- mcp-builder skill (MCP 开发模板 — 已读)
- research-loop skill (调研方法论 — 已读)
- docker skill (待 Week 1 启动前读)

## ⏰ 下一步

**等 Cove 拍板 8 件事** (见 `task_plan.md`)。拍板后从 `services/content-pipeline-mcp/Dockerfile` 开始。