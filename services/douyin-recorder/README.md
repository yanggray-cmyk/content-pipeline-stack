# douyin-recorder (docker)

Douyin live stream recorder via ffmpeg. 复用上游 Dockerfile (`/home/main/DouyinLiveRecorder/Dockerfile`) + 容器内 mount local config.ini。

## systemd → docker 行为对照

| | systemd | docker |
|---|---|---|
| Working dir | `/home/main/DouyinLiveRecorder` | `/app` (in image) |
| Config | `/home/main/DouyinLiveRecorder/config/URL_config.ini` + `config.ini` | bind mount 到 `/app/config:ro` |
| Downloads | `/home/main/DouyinLiveRecorder/downloads/抖音直播/<主播>/<场次>/` | bind mount 到 `/app/downloads` |
| Transcribe hook | `transcribe-hook-wrapper.sh` (`/home/main/douyin-data/scripts/hooks/`) | bind mount 到 `/hooks:ro` |
| MemoryMax | 1.5G (Chromium + ffmpeg) | limit 1.5G |
| 端口 BFF | (无 BFF, 直接命令行) | 18988 (可选 dashboard) |

## 镜像

build context = `/home/main/DouyinLiveRecorder/`(本机已有源码,不在 content-pipeline-stack 仓里)。Dockerfile 即上游 `DouyinLiveRecorder/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN apt-get update && apt-get install -y curl gnupg && \
    curl -sL https://deb.nodesource.com/setup_20.x | bash && \
    apt-get install -y nodejs
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get install -y ffmpeg tzdata && ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
CMD ["python", "main.py"]
```

## 验证

```bash
# 1. 启 (要抖音 cookie,直接 mount host cookie)
docker compose up -d douyin-recorder

# 2. 看录制
docker logs -f douyin-recorder

# 3. 验证 output
ls -la /home/main/DouyinLiveRecorder/downloads/抖音直播/

# 4. BFF dashboard (如果 expose 18988)
open http://127.0.0.1:18988/
```

## 关键 volume

```yaml
volumes:
  - /home/main/DouyinLiveRecorder/downloads:/app/downloads  # rw, 视频落盘
  - /home/main/douyin-data/config/douyin-recorder:/app/config:ro  # URL_config.ini + config.ini
  - /home/main/douyin-data/scripts/hooks:/hooks:ro  # transcribe-hook-wrapper.sh
```

## 备注

- **上游 Dockerfile 是 OpenClaw 自定义**(hmily-mod),不是原始 ihmily/DouyinLiveRecorder
- Python 3.11 + node 20 + ffmpeg + Chromium,~600MB 镜像层
- **Chromium 在容器内** — 性能与 systemd 几乎等(同 host mount)
- **transcribe hook 是 shell 调 MCP URL**,依赖 `MCP_URL=http://content-pipeline-mcp:18092/mcp`(环境变量)
- 当前 docker 模式**未单测**(build 验证待执行)

## 已知问题

- 上游 `main.py.bak.2026-07-04_12-15` 等备份文件被 COPY 进 image(多余,但不致命)
- `.env` 中的 `DOUYIN_RECORDER_DASHBOARD_TOKEN` 是 BFF dashboard 密码, 上游 config.ini 也要同步
- `main.py` 直接调 `pathlib.Path(__file__).parent`,容器里要确保 `/app/config` 真的有 URL_config.ini
