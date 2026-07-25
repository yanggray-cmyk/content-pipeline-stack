# content-pipeline-mcp (Docker 化版本)

**原版 systemd**: `/etc/systemd/system/content-pipeline-mcp.service`
**原版源码**: `/home/main/.openclaw/workspace/skills/content-pipeline-mcp/` (软链或 COPY 进 build context)
**MCP port**: 18092
**Transport**: streamable_http + Bearer auth
**Tools 数**: 17 (5 tool modules × monitor/pipeline_status/worker/yuxi/batch)

## 快速开始

```bash
# 1. 构建镜像
docker build \
  -t ghcr.io/main-1/content-pipeline/content-pipeline-mcp:0.1.0 \
  -f services/content-pipeline-mcp/Dockerfile \
  services/content-pipeline-mcp

# 2. 准备 env 文件 (从 systemd 复制, mode 600)
cp /etc/content-pipeline-mcp.env .env
chmod 600 .env

# 3. 启动容器
docker run -d \
  --name content-pipeline-mcp \
  --restart=unless-stopped \
  --memory=2g \
  --memory-reservation=1g \
  -p 18092:18092 \
  --env-file .env \
  -v /home/main/douyin-data:/home/main/douyin-data:ro \
  ghcr.io/main-1/content-pipeline/content-pipeline-mcp:0.1.0

# 4. 健康检查
curl -fsS http://127.0.0.1:18092/health

# 5. 列 tools (需要 Bearer auth)
TOKEN=$(grep MCP_TOKEN .env | cut -d= -f2)
curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18092/tools
```

## 跟 systemd 行为对比

| 维度 | systemd | docker | 一致? |
|---|---|---|---|
| Port | 18092 | 18092 | ✅ |
| Host | 127.0.0.1 | 0.0.0.0 (容器内) | ✅ (nginx 走 bridge network) |
| User | main (uid 1000) | appuser (uid 1000) | ✅ |
| MemoryMax | 2G | --memory=2g | ✅ |
| MemoryHigh | 1G | --memory-reservation=1g | ✅ |
| Env file | /etc/content-pipeline-mcp.env | --env-file | ✅ |
| Restart | Restart=always | --restart=unless-stopped | ✅ |
| Logging | journal | docker logs | ✅ (journal 已不再用) |

## 数据卷挂载说明

| 路径 | 用途 | ro/rw |
|---|---|---|
| `/home/main/douyin-data:/home/main/douyin-data:ro` | pipeline_status / pipeline_trace_aweme 等 tool 读 queue.db + transcripts | **ro** (MCP 只读) |

## 故障排查

```bash
# 容器日志
docker logs -f content-pipeline-mcp

# 进入容器排查
docker exec -it content-pipeline-mcp /bin/sh

# MCP_TOKEN 没设?
docker exec content-pipeline-mcp env | grep MCP_TOKEN

# 17 tools 都在?
TOKEN=$(grep MCP_TOKEN .env | cut -d= -f2)
docker exec -e TOKEN=$TOKEN content-pipeline-mcp \
  wget -qO- --header="Authorization: Bearer $TOKEN" http://127.0.0.1:18092/tools | jq '.tools | length'
```

## 跟 Yuxi 集成

Yuxi HZ 端通过 `MultiServerMCPClient` 调我们:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
client = MultiServerMCPClient({
    "content-pipeline": {
        "transport": "streamable_http",
        "url": "http://content-pipeline-mcp:18092/mcp",  # docker network 内
        "headers": {"Authorization": "Bearer ${MCP_TOKEN}"},
        "timeout": 600,
    }
})
tools = await client.get_tools()  # 17 tool
```

如果 Yuxi 在 HZ,需要 `https://hk.siqing.cn/api/mcp/mcp` (走 nginx 反代)。