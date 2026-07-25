# Dockerfile — file-service
# Node.js Express + multer + sharp (image thumb)
# Source: /home/main/.openclaw/workspace/file-service (copied into build context)
# systemd: file-service.service (18098, RSS 851MB)
#
# 选择 Debian slim 不用 alpine:sharp 没有 prebuilt alpine 二进制,
# 强 build-from-source 要 c++ 工具链 + node-addon-api 复杂。
# node:24-bookworm-slim 默认有 sharp prebuilt。

# ─── Stage 1: deps ──────────────────────────────────────────────────────────
FROM node:24-bookworm-slim AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --omit=dev

# ─── Stage 2: runtime ───────────────────────────────────────────────────────
FROM node:24-bookworm-slim AS runtime

# sharp 在 bookworm-slim 上有 prebuild(libs/libvips 自动 vendored)
# debian 镜像补 libvips 的 .so 依赖(npm 不打包)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        # sharp 在 debian-bookworm 通常自带, 仅保险补:
        libvips42 libglib2.0-0 libexpat1 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="content-pipeline/file-service"
LABEL org.opencontainers.image.description="File/video browsing + upload service"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"

WORKDIR /app

COPY --from=builder /build/node_modules ./node_modules
COPY server.js ./
COPY package.json ./
COPY lib/ ./lib/
COPY index.html videos.html ./
COPY videos.html.bak ./

# UID/GID 1001:1001 = host 'main' user (磁盘 owner)
# 不用 alpine 'node' (uid 1000): uid 1000 不匹配磁盘 owner, EACCES
USER 1001:1001

EXPOSE 18098

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD wget -qO- http://127.0.0.1:18098/health || exit 1

CMD ["node", "server.js"]


# ─────────────────────────── 备选 (alpine only if sharp alpine prebuilt) ─────────────────────────────
# FROM node:24-alpine AS builder
# RUN apk add --no-cache vips-dev python3 make g++
# 上述需要 sharp's install script 能装 node-addon-api,但 alpine 仍然编译失败率高。
# 生产推荐 bookworm-slim (shipped prebuild),仅 alpine 用于镜像极小的场景。