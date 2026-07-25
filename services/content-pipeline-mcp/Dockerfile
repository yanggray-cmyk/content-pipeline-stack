# Dockerfile for content-pipeline-mcp
# Reference: ~/.openclaw/workspace/skills/content-pipeline-mcp/src/index.ts
# Systemd unit equivalent: /etc/systemd/system/content-pipeline-mcp.service
#   - User=main, MemoryMax=2G, MemoryHigh=1G
#   - PORT=18092, HOST=127.0.0.1, NODE_ENV=production
#   - EnvironmentFile=/etc/content-pipeline-mcp.env (mode 600)
#
# Build: docker build -t ghcr.io/main-1/content-pipeline/content-pipeline-mcp:0.1.0 services/content-pipeline-mcp
# Run:   docker run -d --name content-pipeline-mcp -p 18092:18092 \
#          --env-file /etc/content-pipeline-mcp.env \
#          -v /home/main/douyin-data:/home/main/douyin-data:ro \
#          --memory=2g --memory-reservation=1g --restart=unless-stopped \
#          ghcr.io/main-1/content-pipeline/content-pipeline-mcp:0.1.0

# ─── Stage 1: Build (TypeScript → JavaScript) ─────────────────────────────────
FROM node:24-alpine AS builder
WORKDIR /build

# Install dependencies first (cache layer for npm ci)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# Prune dev dependencies for production stage
RUN npm prune --production

# ─── Stage 2: Runtime (minimal Alpine + node) ─────────────────────────────────
FROM node:24-alpine AS runtime

# Labels
LABEL org.opencontainers.image.title="content-pipeline-mcp"
LABEL org.opencontainers.image.description="MCP server for content pipeline (monitor→download→transcribe→distill→upload→ingest)"
LABEL org.opencontainers.image.source="https://github.com/main-1/content-pipeline-stack"
LABEL org.opencontainers.image.version="0.1.0"

# Install wget for healthcheck (no curl in alpine by default)
RUN apk add --no-cache wget tini

# Create non-root user (Alpine node:24-alpine already has 'node' user; we use it)
# Note: alpine's node user has uid 1000 by default; we don't re-create to avoid gid clash
USER node

WORKDIR /app

# Copy built artifacts and production dependencies from builder
COPY --from=builder --chown=appuser:appuser /build/dist ./dist
COPY --from=builder --chown=appuser:appuser /build/node_modules ./node_modules
COPY --from=builder --chown=appuser:appuser /build/package.json ./package.json

# Runtime environment (matches systemd defaults)
ENV NODE_ENV=production
ENV PORT=18092
ENV HOST=0.0.0.0

# Expose MCP port (matches systemd PORT)
EXPOSE 18092

# Healthcheck: curl /health on every 30s, fail after 3 retries
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:${PORT}/health || exit 1

# tini = PID 1, signal forwarding for graceful shutdown (SIGTERM → process)
ENTRYPOINT ["/sbin/tini", "--"]

# Start the MCP server (exec form = proper signal handling)
USER node
CMD ["node", "dist/index.js"]