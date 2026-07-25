# Day 4 — 数据持久化设计 (findings)

**触发**: 2026-07-26 01:44 Cove 拍板 (b)+(c)+(d) 后接 Day 4
**目的**: 4 服务容器化完成后,设计"数据在容器生命周期外的存放"方案

---

## 📊 数据清单 (5 类)

| # | 数据 | 当前路径 | 大小 | 写频 | 关键 |
|---|---|---|---|---|---|
| **A** | **录播 mp4** | `/home/main/DouyinLiveRecorder/downloads/抖音直播/{主播}/{场次}/` | **9 GB+** | ~1GB/h (录制中) | 唯一真源, 不能丢 |
| **B** | **v6 queue/state db** | `/home/main/douyin-data/{queue.db, monitor_state.db}` | 25MB + 45KB | 写频繁 (每 stage) | 多 worker 共享, 锁 |
| **C** | **transcripts** (.asr.json/.md/.srt) | `/home/main/douyin-data/transcripts/` | ~30K files | ~100/h (transcribe) | 由 mp4 派生, 可重生成 |
| **D** | **uploads** (file-service) | `/home/main/uploads/` | ~5K files / 多 GB | ~50/h (upload) | 已 md5, 不能丢 |
| **E** | **hk-asr 模型** | `/home/main/.cache/asr_service/` (paraformer-zh 4.8GB) | 4.8 GB | 0 (只读) | 多 worker 共享同一份 |

**5 类对比维度**:
- **A (mp4)**: 写一次, 长期存档, 不能删, 体积大
- **B (db)**: 写频繁, 锁, 多进程共享, 小但关键
- **C (transcripts)**: 可重生成 (从 mp4 再 ASR), 短期保留
- **D (uploads)**: 写一次, 唯一 ID, 不能丢
- **E (模型)**: 只读, 大, 多 worker 共享

---

## 🎯 3 个方案对比

### 方案 1: **Host Bind Mount (当前做法)**

```yaml
volumes:
  - /home/main/DouyinLiveRecorder/downloads:/app/downloads
  - /home/main/douyin-data:/data
```

| 维度 | 评价 |
|---|---|
| **易用** | ✅ docker compose 一行, 无额外组件 |
| **迁移** | ⚠️ 容器迁移到另一台, 数据留在原机器 |
| **备份** | ⚠️ 需自己 cron tar / rsync |
| **多 host 共享** | ❌ 单机, NFS/GlusterFS 才能共享 |
| **权限** | ✅ UID 1001:1001 跟 host main 对齐 (已验证) |
| **性能** | ✅ 本机 IO, 无网络开销 |
| **调试** | ✅ 容器内 `ls /data/...` 直接看 host 文件 |

**适用**: 单机生产 (HK 现在)、dev/staging、个人 NAS
**风险**: 多机房部署时数据不会跟随容器

### 方案 2: **Named Volume (Docker 管理)**

```yaml
volumes:
  downloads:/app/downloads:rw   # named volume
  v6-state:/data:rw
```

```bash
docker volume create downloads  # 默认 /var/lib/docker/volumes/downloads/_data
```

| 维度 | 评价 |
|---|---|
| **易用** | ✅ docker compose 自动创建 |
| **迁移** | ⚠️ `docker volume` 不能跨主机直接搬,需 `docker run --volumes-from` |
| **备份** | ⚠️ 需 `docker run --rm -v downloads:/data alpine tar cvf` |
| **多 host 共享** | ❌ 同 host bind, 需要分布式文件系统 |
| **权限** | ⚠️ 默认 root, 需手动 chown 1001 |
| **性能** | ✅ 本机 IO |
| **调试** | ⚠️ 容器内看不到, 需 `docker volume inspect` |

**适用**: 单机部署但不关心路径具体在哪 (docker 自己管)
**缺点**: host bind 更直接, named volume 在单机没明显优势

### 方案 3: **S3 / 对象存储**

```yaml
# s3fs 挂载, 或 rclone mount, 或各 worker 直接 boto3
volumes:
  - s3-bucket:/app/downloads  # s3fs-fuse 挂载点
```

```bash
# docker run: 容器内跑 s3fs, 或 host 跑 + bind 挂载点
s3fs my-bucket /mnt/s3 -o passwd_file=~/.passwd-s3fs
```

| 维度 | 评价 |
|---|---|
| **易用** | ⚠️ s3fs mount 偶尔崩, 需 watchdog 重启 |
| **迁移** | ✅ **跨机房/跨云天然支持**, 任何 docker host 挂同一 bucket |
| **备份** | ✅ S3 自带多 AZ + versioning + lifecycle |
| **多 host 共享** | ✅ **核心优势**: HK/HZ/任何 host 都看到同一份 |
| **权限** | ✅ S3 IAM + bucket policy |
| **性能** | ⚠️ 网络 IO, 100-500 MB/s (看 region) |
| **调试** | ✅ s3 CLI 任意查看 |

**适用**: 多机房 / 跨云 / 灾备 / 团队协作
**缺点**: 网络延迟 + 成本 (S3 存储费) + s3fs 稳定性

---

## 💡 决策矩阵 (按数据类别)

| 数据 | 推荐方案 | 理由 |
|---|---|---|
| **A mp4** | **Host bind** (短期) → **S3** (跨机房) | 体积大 + 写一次 + 不能丢, 单机 bind 性能好, 多机房时升 S3 |
| **B db (queue/monitor_state)** | **Host bind** | 写频繁 + 锁, S3 mount 抖动会损坏 SQLite WAL |
| **C transcripts** | **Host bind** | 跟 mp4 同盘, 可一起升 S3 |
| **D uploads** | **Host bind** | 跟 mp4 同盘, file-service 已统一 |
| **E hk-asr 模型** | **Host bind** (共享路径) | 4.8 GB 大文件, 多 worker bind 同一份只读, 无须每镜像 COPY |

**关键洞察**:
1. **B 类 (db) 永远不要放 S3 mount** — SQLite WAL + 网络抖动 = 必崩
2. **E 类 (模型) bind 比 COPY 进镜像好** — 镜像小 4.8GB, 多 worker 共享缓存
3. **A/C/D 同盘** (douyin-data/) — 一个 mount 涵盖三类

---

## 📐 HK 当前实测方案 (Day 2-3 现状)

### docker-compose.yml 已 bind 的数据

| 数据 | bind 来源 | 容器内路径 | 备注 |
|---|---|---|---|
| mp4 (recorder) | `/home/main/DouyinLiveRecorder/downloads` | `/app/downloads` | 9GB 录播 |
| state.db (v6-monitor) | `/home/main/douyin-data` | `/home/main/douyin-data` | V6_WORKDIR=/home/main/douyin-data |
| config + accounts (v6-monitor) | `/home/main/douyin-data/config` | `/home/main/douyin-data/config` | 单一真源 (铁律 172) |
| uploads (file-service) | `/home/main/uploads` + `/home/main/.openclaw` | `/home/main/uploads` + `/home/main/.openclaw` | UID 1001 修过 |

### Day 4 待补的 bind (Week 2 起 v6 worker)

| 服务 | bind 来源 | 容器内路径 |
|---|---|---|
| v6-enqueue | `/home/main/douyin-data` | `/data` (queue.db) |
| v6-download | `/home/main/DouyinLiveRecorder/downloads` (read 后续上传) + `/home/main/douyin-data` | `/data` |
| v6-transcribe | `/home/main/DouyinLiveRecorder/downloads` + `/home/main/douyin-data/transcripts` | `/data/in` + `/data/out` |
| v6-distill | `/home/main/douyin-data/transcripts` | `/data/in` |
| v6-upload | `/home/main/uploads` + `/home/main/douyin-data/knowledge-base` | `/data/in` + `/data/out` |
| hk-asr | `/home/main/.cache/asr_service` + `/home/main/douyin-data` | `/data/model` + `/data/queue` |

**关键**: **不要让容器写 `/home/main/douyin-data` 子目录** — systemd 可能在写同一个子目录
例外: `v6-monitor` + `v6-enqueue` 是 systemd 真源, docker bind 同一目录可写 (已有协调机制)

---

## 🚧 多机房场景 (HK + HZ + 第三地)

**触发**: (c) GHCR push 后, 镜像跨机房部署

### 当前 (HK) 数据真源

```
/home/main/douyin-data/                  ← 一切 v6 数据
/home/main/DouyinLiveRecorder/downloads/ ← 录播 mp4 (9GB)
/home/main/uploads/                      ← file-service uploads
/home/main/.cache/asr_service/           ← asr 模型 (4.8GB)
```

### 多机房目标 (e 拍板)

**方案 A: rsync cron 同步** (现有做法)
- HK → HZ 每 6h rsync 增量
- 优点: 简单, 已有
- 缺点: 延迟, 不一致

**方案 B: S3 统一真源**
- 所有数据上 S3 bucket
- HK/HZ/其他 mount 同一 bucket (s3fs)
- 优点: 强一致
- 缺点: s3fs 稳定性, 成本

**方案 C: HK 真源 + HZ 副本, 容灾切换**
- HK = master (写)
- HZ = replica (读, rsync 跟)
- 故障: HZ 接管
- 优点: 明确主从
- 缺点: 切换需手动

**推荐 (Cove 拍板前不实施)**:
- **A 类 mp4** = 方案 B (S3, 跨机房只读归档, HK 写完 sync)
- **B 类 db** = 方案 A (HK 真源, rsync 单向)
- **C 类 transcripts** = 方案 B (S3 同 A)
- **D 类 uploads** = 方案 A
- **E 类模型** = 方案 A (模型文件大, rsync 一次就够)

---

## 🎯 Day 4 决策清单 (等 Cove 拍板)

### 已确定 (无需拍板)
1. ✅ 5 类数据都用 **host bind** (Day 2-3 已生效)
2. ✅ **db (queue/monitor_state) 永远在 host bind** (不 S3)
3. ✅ **hk-asr 模型 host bind** (不 COPY 进镜像)
4. ✅ v6 worker bind 跟 systemd 写同一份目录 (协调机制已有)

### 待 Cove 拍板
1. **(e) 多机房数据同步策略**:
   - A: rsync cron 6h (现状, 延迟 6h)
   - B: S3 真源 (跨机房强一致, 成本)
   - C: HK 主 + HZ 副本 (明确主从, 手动切)
   - D: 不做多机房, 保持单点
2. **(f) 灾备**: 关键数据 snapshot 频率? `restic/borg backup to where?`
3. **(g) 容器写 host 权限范围**: 哪些子目录容器可写? 哪些只读?
   - 例: `/home/main/douyin-data/queue.db` 容器可写, 但 `transcripts/` 只读 (systemd 写)

---

## 🛠️ Day 4 实施清单 (拍板后)

### P1: 补全 v6 worker bind (Week 2 Day 1-3)
- [ ] v6-enqueue Dockerfile + bind
- [ ] v6-download Dockerfile + bind
- [ ] v6-transcribe Dockerfile + bind
- [ ] v6-distill Dockerfile + bind
- [ ] v6-upload Dockerfile + bind
- [ ] hk-asr Dockerfile + bind 模型目录
- [ ] docker-compose.yml 加 5 worker 服务

### P2: 多机房 (Week 2 Day 4-5, 等 e 拍板)
- [ ] 选 rsync / S3 / 主从 方案
- [ ] 写多机房同步脚本 (cron / 实时)
- [ ] HZ 端 docker compose 配置
- [ ] 灾备演练 (HK down, HZ 起)

### P3: 监控 (Week 3 Day 4)
- [ ] 各 bind 路径磁盘空间告警 (cron + webhook)
- [ ] S3/rsync 同步状态监控
- [ ] 容器 vs systemd 写冲突检测

---

## 📌 永久教训 (本段新增)

1. **SQLite WAL + 网络 mount = 必崩**: 永远不要把 queue.db / state.db 放 S3 / NFS,网络抖动 → WAL 损坏 → 整个 db 重导
2. **大模型文件 bind 比 COPY 进镜像好**: 4.8GB paraformer-zh COPY 进镜像 = 镜像 6.8GB,多 worker 各一份浪费; bind 共享 = 镜像小 + 缓存友好
3. **多 worker 写同一目录要协调**: docker v6-worker + systemd v6-worker 写同一 `/data` 必须有锁 (queue.db 已经用 SQLite WAL 处理)
4. **docker volume 不一定比 host bind 好**: 单机场景, host bind 更直接可调试; 只有跨主机或不想暴露路径时, named volume 才有意义
5. **s3fs 不是 silver bullet**: mount 抖动 / 内存泄漏 / 网络分区 都会让 s3fs 卡死,需要 fuse mount watchdog

---

*版本: v0.1 (2026-07-26 01:44 Day 4 设计稿)*
*下一步: 等 Cove 拍板 (e) 多机房方案 → 写实施代码*