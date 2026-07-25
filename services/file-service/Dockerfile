# Dockerfile — file-service
# Node.js Express + multer + sharp (image thumb)
# Source: /home/main/.openclaw/workspace/file-service (copied into build context)
# systemd: file-service.service (18098, RSS 851MB)

# ─── Stage 1: deps + build ───────────────────────────────────────────────────
FROM node:24-alpine AS builder

WORKDIR /build

# sharp + libvips 系统依赖(sharp 是 native module, alpine 用 musl 容易出错 — 用预编译)
# vips-dev 也可能需要 — 但 alpine npm 有 sharp prebuilds,先试官方
RUN apk add --no-cache vips-dev

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --omit=dev

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM node:24-alpine AS runtime

# sharp 在 alpine 上需要 vips + 几个 .so; 用 vips 包 + 镜像预编译
RUN apk add --no-cache vips

# Labels
LABEL org.opencontainers.image.title="content-pipeline/file-service"
LABEL org.opencontainers.image.description="File/video browsing + upload service"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"

# Workdir
WORKDIR /app

# Copy built artifacts from builder
COPY --from=builder /build/node_modules ./node_modules
COPY server.js ./
COPY package.json ./
COPY lib/ ./lib/
COPY index.html videos.html ./
COPY videos.html.bak ./

# Non-root: alpine node:24-alpine ships 'node' user (uid 1000) already
USER node

# Expose port (matches systemd)
EXPOSE 18098

# Healthcheck via wget (node:alpine has wget via busybox)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD wget -qO- http://127.0.0.1:18098/health || exit 1

# Start
CMD ["node", "server.js"]