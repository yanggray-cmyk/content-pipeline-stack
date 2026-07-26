# douyin-recorder (docker)

Douyin live stream recorder via ffmpeg. 复用上游 Dockerfile (`/home/main/DouyinLiveRecorder/Dockerfile`) + 容器内 mount local config.ini。

## 架构 (v3.0 - 全模块化)

**2026-07-26 重构系列** (PR #11-17):
- PR #11: 51 elif 分支 → 策略模式 (PlatformStrategy + PlatformRegistry)
- PR #12: spider.py (3394 行) → platforms/streams/ 按域拆分
- PR #13/14: start_record (737 行) → recording/ 模块 + RecordContext
- PR #15: special.py (1250 行) → special/ 按平台拆分
- PR #16/17: stream.py + 全部函数 <50 行

### 模块结构

```
source/
├── main.py                    # 入口 + start_record 编排 (313 行)
├── recording/                 # 录制执行层 (PR #13/14)
│   ├── context.py             # build_context / resolve_proxy
│   ├── ffmpeg.py              # build_ffmpeg_command
│   ├── push.py                # handle_live_status_push
│   └── recorder/              # 按格式分发 (RecordContext)
│       ├── base.py            # RecordContext dataclass + record_by_format
│       ├── audio.py           # MP3/M4A
│       ├── flv.py             # FLV + 直下载
│       └── standard.py        # MKV/MP4/TS
├── src/
│   ├── platforms/             # 策略模式 (PR #11)
│   │   ├── base.py            # PlatformStrategy 基类 + Registry
│   │   ├── domestic.py        # 35 国内平台
│   │   ├── overseas.py        # 7 海外平台
│   │   └── special.py         # 9 特殊平台
│   ├── platforms/streams/     # 平台 API 调用 (PR #12/15)
│   │   ├── domestic.py        # 国内流获取 (39 函数)
│   │   ├── overseas.py        # 海外流获取 (13 函数)
│   │   └── special/           # 特殊平台 (PR #15)
│   │       ├── douyin.py      # 抖音 Web/App
│   │       ├── huya.py / soop.py / flextv.py
│   │       ├── popkon.py / twitcasting.py
│   │       └── taobao_jd.py
│   ├── spider.py              # re-export 兼容层 (19 行)
│   └── stream.py              # 流地址选择层 + 质量 helpers
└── config/
```

### 设计原则 (铁律)

- 每个函数 < 50 行
- 参数 > 5 个 → dataclass/context 对象
- 重复模式 > 2 次 → 提取公共 helper (如 `_pad_to_five`)

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
