# file-service (docker)

Node.js Express service for browsing + uploading video files.

## systemd → docker 行为对照

| | systemd | docker |
|---|---|---|
| Service unit | `file-service.service` | compose service `file-service` |
| Working dir | `/home/main/.openclaw/workspace/file-service` | `/app` (in image) |
| Binary path | `/usr/bin/node /home/main/.openclaw/workspace/file-service/server.js` | `node server.js` |
| Port | 18098 | 18098 → 18098 |
| Memory RSS | 851 MB | limit 1G (configurable) |
| data dir | `/home/main/douyin-data` | bind mount same path |

## 验证

```bash
# 1. 容器 up
docker compose up -d file-service

# 2. /health
curl http://127.0.0.1:18098/health

# 3. 资源
docker stats file-service

# 4. /videos (browser UI)
open http://127.0.0.1:18098/

# 5. 关 systemd 不冲突
# 容器跑 28098 / systemd 跑 18098,验证并列存在
docker compose port file-service 18098
```

## 配置

`.env` 必填:

```bash
FS_UPLOAD_TOKEN=$(openssl rand -hex 32)   # 上传 bearer token
NODE_ENV=production
PORT=18098
FS_DATA_ROOT=/home/main/douyin-data/files  # bind mount 内部
```

## 文件结构(in image)

```
/app/
├── server.js
├── package.json
├── node_modules/    # only prod deps (sharp + multer + express + cors)
├── lib/             # asset-manager.js, assets-relations.js, assets-rules.js
├── index.html
├── videos.html
└── videos.html.bak
```

## 备注

- sharp native module → alpine 包了 `vips` 镜像
- 当前 **docker 模式未单测** (build 验证待执行)
- systemd 容器并行:docker 容器跑在 28098,systemd 还在 18098,验证路径不冲突
