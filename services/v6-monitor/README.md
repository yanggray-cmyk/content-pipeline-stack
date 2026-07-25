# v6-monitor (docker)

Douyin account monitor daemon (铁律 143/152).

## systemd → docker 行为对照

| | systemd | docker |
|---|---|---|
| Service unit | `v6-monitor.service` | compose service `v6-monitor` |
| Working dir | `/home/main/douyin-data/scripts/v6_pipeline` | 同 |
| Binary | `/usr/bin/python3 v6_monitor.py --daemon --interval 21600` | `python3 v6_monitor.py --daemon --interval 21600` |
| MemoryMax | 200M | limit 200M (CPU 0.5) |
| Port | 无 (纯 SIGUSR1) | 无 (后续 P1 加 /api/run-now HTTP) |
| state.db | `/home/main/douyin-data/monitor_state.db` | 同 bind mount |
| accounts.json | `/home/main/douyin-data/config/accounts.json` | symlink in image |

## SIGUSR1 → HTTP 转换

systemd 版用 SIGUSR1 触发立即重跑 (`docker kill -s SIGUSR1 <id>` 兼容)。

P1 加 HTTP API:`GET /run-now` → daemon --once 重跑。

## 验证

```bash
# 1. 启
docker compose up -d v6-monitor

# 2. 看 SIGUSR1 触发
docker kill -s SIGUSR1 v6-monitor
docker logs -f v6-monitor  # 应见 "立即跑一次"

# 3. 资源 (200M, RSS 应 <100M)
docker stats v6-monitor

# 4. SQLite state.db 持续累积 (跟 systemd 行为一致)
ls -la /home/main/douyin-data/monitor_state.db
sqlite3 /home/main/douyin-data/monitor_state.db ".tables"

# 5. 配置
cat /home/main/douyin-data/config/accounts.json  # 通过 symlink 访问
```

## 数据目录挂载

```
/home/main/douyin-data/
├── config/accounts.json            # 真源 (cfg)
├── monitor_state.db                # 写
├── monitor_state.db-wal/-shm       # SQLite WAL
└── scripts/v6_pipeline/            # 容器 WORKDIR
    ├── v6_monitor.py               # copy in
    └── monitor/                    # copy in
        ├── accounts.json → ../../../config/accounts.json
        ├── logs/                   # logs bind, daemon 写
        └── scripts/
            ├── monitor_daemon.sh
            └── monitor_douyin.py
```

## 文件结构(in image)

```
/home/main/douyin-data/scripts/v6_pipeline/  # WORKDIR
├── v6_monitor.py    # copy
└── monitor/
    ├── .gitignore
    ├── accounts.json → /home/main/douyin-data/config/accounts.json (symlink)
    └── scripts/
        ├── monitor_daemon.sh
        └── monitor_douyin.py
```

## 备注

- 仅用 Python stdlib,无 pip install 需求
- 容器**不能 `USER monitor`** — daemon 要写 /home/main/douyin-data 配置/状态,host mount 需要 root UID 1000 / main UID 1000
- 当前 docker 模式**未单测**(build 验证待执行)
