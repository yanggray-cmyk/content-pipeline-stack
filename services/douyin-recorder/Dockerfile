# Dockerfile — douyin-recorder
# Python 3.11 + nodejs 20 (抖音签名) + ffmpeg + tzdata
# 抖音/TikTok/B站 等 40+平台直播录制 (上游: ihmily/DouyinLiveRecorder)
#
# 关键设计:
#   1. image 内只装源码 (38M),数据全 host bind (9G downloads + 652K logs + 72K backup_config)
#   2. config/URL_config.ini (含 cookie 字符串)host bind → 跟 systemd 同一份
#      (cookie 是明文写在 config.ini 第 66 行,不是独立 cookie 文件)
#   3. downloads/logs/backup_config 也 bind → 容器跟 systemd 共享同一份输出
#   4. CMD: python main.py (跟上游 + systemd 一致)
#   5. SIGTERM → main.py line 87 signal_handler 优雅退出
#   6. transcribe hook = config.ini 自定义脚本 (/usr/bin/env bash <script>)
#      → 容器内也需要这个 wrapper.sh (bind mount 也可,但路径在 config.ini 写死)

FROM python:3.11-slim

LABEL org.opencontainers.image.title="content-pipeline/douyin-recorder"
LABEL org.opencontainers.image.description="Douyin/TikTok live recorder (40+ platforms, ihmily upstream)"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"

# 上游 Dockerfile 一致: curl + gnupg + nodesource + ffmpeg + tzdata
# 注意: nodesource install 大约 2-3min,build 时间偏长
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates tini && \
    curl -sL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get install -y --no-install-recommends ffmpeg tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先 COPY requirements 享受 layer cache (依赖改了不用重 install 整个 pip)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 然后 COPY 源码
COPY . /app/

# Non-root: bind mount 需要 main user (uid 1001) 写权限 (downloads 是 main 拥有的)
# image 内建 monitor user (uid 1001) 跟 host main 对齐
RUN useradd -u 1001 -m -d /home/monitor -s /bin/bash monitor && \
    mkdir -p /app/config /app/logs /app/backup_config /app/downloads && \
    chown -R monitor:monitor /app

USER 1001:1001

# 端口: recorder 不暴露 HTTP (上游也没)
# 健康检查: 容器内 ffmpeg / python 进程在跑 = 正常
# 端口: recorder 不暴露 HTTP (上游也没)
# 健康检查: 用 /proc 查 main.py 进程 (不用 pgrep/不装 psutil)
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=30s \
    CMD python -c "import os; [exit(0) for p in os.listdir('/proc') if p.isdigit() and b'main.py' in open(f'/proc/{p}/cmdline','rb').read()]; exit(1)"

# Default: python main.py (跟上游 + systemd ExecStart 一致)
# tini 转 SIGTERM 给 python 信号 handler (line 87)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]


# Build-time note:
# - Use .dockerignore to skip .git/ downloads/ logs/ backup_config/ __pycache__/
# - Image size ~400-500MB (ffmpeg ~150MB + nodejs ~50MB + python ~50MB + deps ~50MB + app ~38MB)
# - Build time ~3-4 minutes (apt install + pip install + nodesource)