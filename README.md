# content-pipeline-stack

> 抖音内容采集 → 转录 → KB 蒸馏 → 上传 整套流水线
> 9 服务 docker stack, 纯源码模式, clone 即可用

## 这是什么

content-pipeline-stack 把以下 4 类工作统一成 docker 容器, 共享 `localhost:5000` 本地镜像仓库:

| 角色 | 服务 | 默认端口 |
|---|---|---|
| **采集** | `douyin-recorder` | systemd / docker |
| **下载 / 转码** | `v6-download` `v6-transcribe` `v6-distill` `v6-upload` | worker (5 min cron) |
| **监控** | `v6-monitor` `v6-enqueue` | 6h cron |
| **接口** | `content-pipeline-mcp` | `28092` (HTTP + MCP) |
| **展示** | `file-service` | `28098` (HTTP + 视频) |
| **本地镜像仓库** | `registry:2` | `5000` |

**9 个服务**:
- `content-pipeline-mcp` — MCP protocol (17 tools, Claude/Codex 调用)
- `file-service` — Node.js Express + multer (视频/文件浏览 + 上传)
- `douyin-recorder` — 抖音直播间录制 (ffmpeg + nodejs 20 + python 3.11)
- `v6-monitor` — 抖音账号监控 daemon (SIGUSR1 触发)
- `v6-enqueue` — cron 驱动入队
- `v6-download` — 抖音视频下载 + 去水印
- `v6-transcribe` — ASR 转录 (调 host.docker.internal:18200)
- `v6-distill` — LLM 蒸馏 KB 卡片
- `v6-upload` — 上传到 file-service
- `registry` — 本地镜像仓库 (10 image, 567MB layer 去重)

## 5 分钟跑通

```bash
# 1. Clone
git clone <repo-url> /opt/content-pipeline-stack
cd /opt/content-pipeline-stack

# 2. 跑 init.sh (问 4 个路径, 启 registry, rebuild, push, up)
bash init.sh

# 3. 验证
docker ps --format "table {{.Names}}\t{{.Status}}"

# 4. 访问
open http://localhost:28098  # file-service 视频浏览
open http://localhost:28092  # content-pipeline-mcp MCP endpoint
```

**默认 init.sh 会**:
1. 问 4 个关键路径 (`DATA_DIR` / `UPLOADS_DIR` / `OPENCLAW_DIR` / `RECORDER_DIR`), HK 默认值已预填
2. 写 `.env`
3. 启 `registry:2` 容器 (port 5000, 数据卷 `/home/$USER/docker-registry/`)
4. rebuild 10 image (`content-pipeline-mcp` `file-service` `douyin-recorder` `v6-base` `v6-{enqueue,download,transcribe,distill,upload}` `v6-monitor`)
5. push 到 `localhost:5000`
6. `docker compose up -d` 起 4 默认服务

## 纯源码模式 (核心设计)

**clone 仓库 + 改路径 = 跑通**,**不需要 douyin-data 迁移**。所有路径走 `.env`:

```bash
# .env 内容
DATA_DIR=/home/main/douyin-data      # 你的 queue.db / state.db / videos / KB
UPLOADS_DIR=/home/main/uploads        # file-service upload 后落这
OPENCLAW_DIR=/home/main/.openclaw     # skills 源码 (brand-video-tools 等)
RECORDER_DIR=/home/main/DouyinLiveRecorder  # douyin-recorder 源码

# 改这些, 别人 clone 后用自己的路径就能跑
# (之前 HK douyin-data 有 41GB 不用迁, 用你自己的数据即可)
```

## 9 服务架构

```
                       ┌─→ douyin-recorder (record)
                       │   ↓ /home/main/DouyinLiveRecorder/downloads/
                       │
   v6-monitor          │   ┌─→ v6-enqueue (cron 5min)
   (SIGUSR1 daemon) ────┼───┤
   ↓ monitor_state.db  │   └─→ queue.db (sqlite)
                       │      ↓
                       │   v6-download
                       │   ↓ mp4 → transcribe.jsonl
                       │   v6-transcribe (调 hk-asr)
                       │   ↓ .md/.srt → distill.jsonl + upload.jsonl (fan-out)
                       │      ├─→ v6-distill (LLM → KB card)
                       │      └─→ v6-upload (调 file-service HTTP)
                       │
                       ├─→ content-pipeline-mcp (MCP 17 tools)
                       │   ↓
                       └─→ file-service (HTTP, 上传/浏览)
```

## docker compose profiles

```bash
# 默认 profile: 4 服务 (持续 daemon)
docker compose up -d
#   content-pipeline-mcp
#   file-service
#   douyin-recorder
#   v6-monitor

# v6-workers profile: + 5 worker (queue 持续 worker_loop)
docker compose --profile v6-workers up -d
#   + v6-enqueue
#   + v6-download
#   + v6-transcribe
#   + v6-distill
#   + v6-upload
```

## 切 systemd → docker (HK 用户专属)

```bash
# 1. 停 systemd
sudo systemctl stop douyin-recorder v6-monitor v6-enqueue v6-download v6-transcribe v6-distill v6-upload
sudo systemctl disable douyin-recorder v6-monitor v6-enqueue v6-download v6-transcribe v6-distill v6-upload

# 2. 起 docker (全部 9 服务)
docker compose --profile v6-workers up -d
```

**重要**: docker douyin-recorder / v6-monitor / v6-worker 跟 systemd **不能双跑**(会双写 `downloads/` / `state.db`)。**停一个再起另一个**。

## 项目结构

```
content-pipeline-stack/
├── README.md                      # 你在这里
├── init.sh                        # 5 min installer (问路径 + 启 registry + push + up)
├── docker-compose.yml             # 9 服务 + profiles
├── .env.example                   # 别人 cp .env.example .env → 改路径
│
├── services/
│   ├── content-pipeline-mcp/      # MCP protocol layer (Node.js + Express)
│   │   ├── Dockerfile
│   │   └── README.md
│   ├── file-service/              # 视频浏览 + 上传 (Node.js + sharp)
│   │   ├── Dockerfile
│   │   ├── healthcheck.js         # node 自带 http (无 curl)
│   │   └── README.md
│   ├── douyin-recorder/           # 抖音直播录制
│   │   ├── Dockerfile             # python:3.11-slim + nodejs 20 + ffmpeg
│   │   └── source/                # upstream rsync 同步
│   ├── v6-base/                   # 共享 base image (python:3.11-slim + requests + playwright)
│   ├── v6-monitor/                # 抖音账号监控 daemon
│   │   ├── Dockerfile
│   │   └── README.md
│   ├── v6-enqueue/                # cron-driven 入队
│   ├── v6-download/               # 抖音视频下载 + 去水印 (chromium fallback)
│   ├── v6-transcribe/             # ASR 转录 (调 HK ASR HTTP 18200)
│   ├── v6-distill/                # LLM 蒸馏 KB 卡片
│   └── v6-upload/                 # 上传到 file-service
│
├── docs/                          # (P1 待补) 架构图 / 部署 / 故障排查
└── PROGRESS-2026-07-26.md         # 开发进度日志
```

## 镜像命名空间

所有 image 在 `content-pipeline-stack/` 命名空间 (本地 registry):

```
localhost:5000/content-pipeline-stack/content-pipeline-mcp:0.1.0
localhost:5000/content-pipeline-stack/file-service:0.1.0
localhost:5000/content-pipeline-stack/douyin-recorder:0.1.0
localhost:5000/content-pipeline-stack/v6-base:0.1.0
localhost:5000/content-pipeline-stack/v6-monitor:0.1.0
localhost:5000/content-pipeline-stack/v6-{enqueue,download,transcribe,distill,upload}:0.1.0
```

**Layer 去重**: v6-base 5 worker 共享, 10 image 总磁盘 567MB (vs 累加 7.2GB, 节省 92%)。

## 端口映射

| 服务 | 容器内 | host |
|---|---|---|
| content-pipeline-mcp | 18092 | 28092 |
| file-service | 18098 | 28098 |
| registry | 5000 | 5000 |
| v6-monitor | (无, SIGUSR1 daemon) | - |
| douyin-recorder | (无) | - |
| v6-worker (5) | (无) | - |

## 关键架构决策

### 1. 纯源码 + 自己数据

**不迁移 douyin-data** (HK 41GB 太重)。别人 clone 后用自己机器的数据, 改 `.env` 即可。这是开源项目标准做法 (跟 yuxin 源码模式一致)。

### 2. 本地 registry:2, 不上 GHCR

**不上 GHCR**: 需要 PAT + 公开仓库, 反而增加维护成本。
**本地 registry:2** 容器 (port 5000): 10 image, 567MB, layer 去重 92%。

### 3. SIGUSR1 daemon 容器化

`v6-monitor` 是 systemd 用 SIGUSR1 触发立即重跑的 daemon (铁律 143)。容器化时:
- `CMD --daemon --interval 21600` (非 `--once`, 立即退出会 restart loop)
- `tini` 转发 SIGUSR1 给 python
- 验证: `docker kill -s SIGUSR1 v6-monitor` → 立即重跑

### 4. systemd vs docker 共存

**采集 daemon 不能双跑** (会双写 `downloads/`):
- `douyin-recorder` downloads/ 9GB
- `v6-monitor` state.db

**接口 / 展示可以并存**:
- `content-pipeline-mcp` systemd 占 18092 + docker 占 28092 (端口错位)
- `file-service` 同上 (18098 / 28098)

**worker 可以并存** (docker compose 用 v6-workers profile, systemd 用独立 unit)。

## 健康检查 (7 个 bug 全修)

| 服务 | 健康检查方式 |
|---|---|
| content-pipeline-mcp | wget /health |
| file-service | node /app/healthcheck.js (无 curl) |
| v6-monitor | (无, SIGUSR1 daemon) |
| v6-enqueue | python sqlite3.connect(`${V6_WORKDIR}/queue.db`) |
| v6-download | python sqlite3 + playwright dir check |
| v6-transcribe | curl `${HK_ASR_URL}/health` |
| v6-distill | python os.makedirs `${KB_DATA_DIR}` |
| v6-upload | curl `${FILE_SERVICE_URL}/health` |
| douyin-recorder | python import test |

## 故障排查

```bash
# 1. 9 服务都跑?
docker compose ps

# 2. 健康检查
docker inspect <service> --format '{{.State.Health.Status}}'

# 3. 看 log
docker logs <service> --tail 30

# 4. 进容器
docker exec -it <service> bash

# 5. 重启某服务
docker compose restart <service>

# 6. 全部重起
docker compose --profile v6-workers down && docker compose --profile v6-workers up -d
```

## 数据持久化

| 数据 | 路径 | 模式 |
|---|---|---|
| queue.db | `$DATA_DIR/queue.db` | host bind (SQLite WAL) |
| monitor_state.db | `$DATA_DIR/monitor_state.db` | host bind |
| downloads | `$RECORDER_DIR/downloads` | host bind (9GB) |
| uploads | `$UPLOADS_DIR` | host bind (27GB) |
| 镜像层 | `/home/$USER/docker-registry` | host bind (567MB) |

**永远 host bind**: SQLite WAL 在网络 mount 上必崩, 不要用 named volume。

## 资源需求 (HK 实际)

| 资源 | 最低 | HK 实际 |
|---|---|---|
| CPU | 2 核 | 4 核 |
| RAM | 8 GB | 14 GB |
| 数据盘 | 100 GB | 200 GB |

| 进程 | 内存 | CPU |
|---|---|---|
| hk-asr (host systemd) | 5.1 GB | 83% (受 CPUQuota=200% 限) |
| openclaw (Gateway) | 1.0 GB | 12.5% |
| Neo4j (Java) | 519 MB | 1% |
| douyin-recorder | 62 MB | 3.7% |

## 开发流程

```bash
# 1. 改 Dockerfile 后
docker build -t localhost:5000/content-pipeline-stack/<svc>:0.1.0 -f Dockerfile ../<ctx>
docker push localhost:5000/content-pipeline-stack/<svc>:0.1.0
docker compose restart <svc>

# 2. 改 docker-compose.yml 后
docker compose --profile v6-workers up -d  # 自动 recreate

# 3. 改 .env.example 后
# 让用户 cp .env.example .env (init.sh 自动覆盖)
```

## 永久教训 (摘要)

1. **裸脚本目录不能用 `-m`**: v6_pipeline 是裸目录, `python -m v6_pipeline.<worker>` 永远失败, 用 `python /path/to/script.py`
2. **Dockerfile multi-stage COPY 不跨 stage**: COPY healthcheck.js 在 stage 1, stage 2 必须 `COPY --from=builder` 才有
3. **Linux `host.docker.internal` 不存在**: Mac/Windows 自动有, Linux 需 `extra_hosts: - "host.docker.internal:host-gateway"`
4. **同 compose 内 service 走 container name**: `http://file-service:18098` 不是 `host.docker.internal:18098` (后者 = host gateway, 会被 systemd 抢)
5. **systemd vs docker 端口冲突**: systemd 用 18098, docker 用 28098 (错位), 同端口=冲突
6. **SQLite 永远 host bind**: WAL 在网络 mount 必崩
7. **SIGUSR1 daemon 容器化金标准**: `CMD --daemon` (非 `--once`), tini 转发信号
8. **douyin-recorder 不能双跑**: systemd + docker 双写 `downloads/` 会截断 mp4
9. **chromium 不装 image**: 200+ 依赖, build 太慢; host bind playwright cache 更实用

## 完整 commit 链

参见 `git log --oneline` (从 Day 1 ~ Day 5, 14 commits)。

## License

TBD (等 Cove 拍板)