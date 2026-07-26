# douyin-recorder (docker)

Douyin live stream recorder via ffmpeg. 复用上游 Dockerfile (`/home/main/DouyinLiveRecorder/Dockerfile`) + 容器内 mount local config.ini。

## 架构 (v2.0 - 策略模式)

**2026-07-26 重构**: 51 elif 分支 → 策略模式 (PlatformStrategy + PlatformRegistry)

### 模块结构

```
src/
├── platforms/
│   ├── base.py          # PlatformStrategy 基类 + PlatformRegistry
│   ├── domestic.py      # 35 个国内平台 (声明式注册)
│   ├── overseas.py      # 7 个海外平台 (声明式注册)
│   ├── special.py       # 9 个特殊平台 (抖音/虎牙/SOOP 等)
│   └── __init__.py      # registry 初始化
├── spider.py            # 平台 API 调用
├── stream.py            # 流处理
└── utils.py             # 工具函数
```

### 平台支持 (51 个)

| 类别 | 数量 | 示例 |
|---|---|---|
| **国内** | 35 | 快手、B站、小红书、淘宝、斗鱼... |
| **海外** | 7 | TikTok、YouTube、Twitch... |
| **特殊** | 9 | 抖音、虎牙、SOOP、FlexTV... |

### 调用流程

```python
# main.py line 642
strategy = registry.match(record_url)
if strategy:
    stream_url = await strategy.get_stream_url(record_url)
```

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
```
