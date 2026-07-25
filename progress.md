# progress.md — content-pipeline-stack 实施进度

**项目**: content-pipeline-stack Docker 化
**开始**: 2026-07-25 21:30 (吉总「我去 HZ 看了 Yuxi」)
**当前阶段**: 规划已就绪,等吉总拍板 8 件事

---

## 📊 完成度

| 阶段 | 状态 | 完成日期 | 备注 |
|---|---|---|---|
| 规划 / 调研 | ✅ 完成 | 2026-07-25 22:08 | 三件套已建 |
| Week 1 P0 (4 服务 docker 化) | ⏳ 待启动 | TBD | 待拍板 #1 |
| Week 2 P1 (v6 worker + hk-asr) | ⏳ 待启动 | TBD | |
| Week 3 P2 (Yuxi 双向 + 文档) | ⏳ 待启动 | TBD | 待拍板 #6 #8 |

---

## 📝 Session 日志

### 2026-07-25 21:30 — 调研启动

吉总问:「我去 HZ 看了 Yuxi,考虑把 content-pipeline-mcp 集成进去,可以研究下 docker 化」

→ 读 research-loop + docker + mcp-builder skill (mcp-builder 是 MCP 开发模板)

### 2026-07-25 21:34-21:36 — HZ Yuxi 勘察

- 11 docker 容器全 healthy (api-dev :5050 / worker-dev ARQ / web-dev :5173 / sandbox-provisioner :8002 / postgres / redis / milvus / neo4j / minio / qdrant-restored / etcd)
- Yuxi v0.7.1, MIT, 开源 RAG+知识图谱+多智能体
- **Yuxi 已有完整 MCP 模块**:`agents/mcp/service.py` (609 行) + `mcp_router.py` (415 行)
- 传输类型支持:sse / streamable_http / stdio — content-pipeline-mcp StreamableHTTP 完美对接
- CRUD API: `POST/GET/PATCH/DELETE /api/system/mcp-servers`,配置存 DB `MCPServer` 表

### 2026-07-25 21:36-21:52 — 意图升级

吉总:「我的目的是把多平台下载（目前主要抖音），转录，蒸馏，上传，这种我想docker化 回头可以独立部署」「你可以在看看还有没有关联的服务 我可能没有猎取an」

→ 全量盘点 HK 19 systemd + 2 docker (Tier 1-5),出 v0 设计图 (4 周实施顺序)

### 2026-07-25 22:00-22:05 — v0 设计图确认

吉总:「想脱离 Gateway」「需要跟 Yuxi 双向接口」

→ 实测 Gateway 现状:
- PID 989292, RSS 778 MB (远低于 MemoryMax 5G)
- systemd unit `openclaw-gateway@main.service` 已 masked, 用 `openclaw-gw1`
- **Gateway ↔ pipeline 已经解耦**(无 systemd unit 依赖)
- startup_failed 9 次,根因是 config schema 漂移 (不是 OOM)

→ v0 设计图完成:
- 目标架构图 (11 docker 服务 + 2 库 + nginx + prometheus)
- Yuxi 双向接口 3 层 (MCP streamable_http / HTTP REST 反向 / Webhook 事件)
- 单点降级矩阵 (7 故障点 → 降级路径)
- 单仓布局 `content-pipeline-stack/`
- 4 周实施顺序

### 2026-07-25 22:08 — 规划落地

吉总:「按你的建议来」「开始搞」→ 「你先做计划」

→ 建仓 `~/.openclaw/workspace/content-pipeline-stack/`
→ 写 task_plan.md / progress.md / findings.md 三件套
→ **停在这里,等 Cove 拍板 8 件事再开 Day 1**

---

## 🟡 待拍板清单 (Cove 回复即可开干)

1. 范围: 全做 3 周 vs P0 1 周出活
2. 库打包: 跟 worker image 一起 vs wheel
3. GPU: CPU / GPU / 两套镜像
4. 部署位置: HK / HZ / 混合
5. 仓位置: 我建的位置 / v6_pipeline/docker/ / dashboard-v3-bff
6. yuxi_* 反向 tool: 5 个 / 2 个 / 安妮建议
7. 「安妮的建议」具体内容
8. Yuxi webhook: PR / 飞书代替

---

## 📦 已建文件

| 文件 | 内容 |
|---|---|
| `content-pipeline-stack/task_plan.md` | 完整规划 (8 拍板 / 3 周 / 文件结构 / 验收) |
| `content-pipeline-stack/progress.md` | 本文件 |
| `content-pipeline-stack/findings.md` | 研究发现 (HZ Yuxi + MCP 协议 + 现有 systemd) |
---

## ✅ 2026-07-25 23:54 — Day 2 完成

**Day 2.1–2.3 (Dockerfile + source + README):** ✅
**Day 2.4 (build):** ✅ 3 镜像全 build 成
**Day 2.5 (docker-compose up):** ✅ 2 容器跑通
**Day 2.6 (e2e verify):** ✅ 总览

### 修复的 4 个生产 Bug

| # | Bug | 根因 | 修复 |
|---|---|---|---|
| 1 | `COPY ... 2>/dev/null \|\| true` | Dockerfile 不支持 shell | 移除 |
| 2 | alpine sharp build-from-source 失败 | sharp 无 alpine prebuilt | 切 bookworm-slim + apt libvips |
| 3 | USER node=uid 1000 vs disk owner uid 1001 | alpine 'node' vs host 'main' | USER 1001:1001 映射 |
| 4 | mkdir EACCES `.openclaw/data/audit/file-service` | compose 缺 bind /home/main/uploads + .openclaw | 补 volumes |

### 验证 (23:54 实测)

| 服务 | 镜像 | 容器 | 端口 | 健康 |
|---|---|---|---|---|
| content-pipeline-mcp | 280MB/64MB | Up healthy | 28092→18092 | ✅ |
| file-service | 605MB/154MB | Up healthy | 28098→18098 | ✅ |
| v6-monitor | 209MB/49MB | (built, 未 up) | — | ✅ |

- **file-service 同 systemd 18098 共存**: docker 28098 + systemd 18098 同份磁盘 5294 files ✅
- **POST /upload 实测**: 返回 `{ok: true, file: {id, size:16, mime:image/png}}` ✅
- **容器内 uid=1001 gid=1001** = host main, EACCES 消除 ✅

### 4 Commits

```
d382a8d fix(file-service): UID 1001:1001 + 补 bind uploads + .openclaw volumes
4bf658f fix(file-service): alpine → bookworm-slim sharp prebuilt
bd71ec4 docs(stack): 三个 service README + Dockerfile shell-syntax 修复
72d5358 feat(stack): docker-compose 初始化 — Week 1 Day 1+2
```

### 待办 Day 3 候选

- (a) v6-monitor 容器 up + daemon 重跑 SIGUSR1 验证
- (b) douyin-recorder Dockerfile 写完 build(用上游 Dockerfile)
- (c) push 镜像到 GHCR
- (d) 4 服务全栈 end-to-end smoke test

