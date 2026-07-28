#!/usr/bin/env node
/**
 * content-pipeline-mcp — MCP Server for content pipeline
 *
 * 17 tools (铁律 165.2 P2-1 / 2026-07-24 22:14 Cove 拍板 — 修前注释说 12, 实际 17):
 *   1. monitor_check_now          - 监控抖音账号新作品 (wraps v6_monitor.py)
 *   2. monitor_status             - 监控状态查询 (state file + last run)
 *   3. account_set_fetch_strategy - 设置账号 fetch_strategy (full/incremental, 铁律 152)
 *   4. pipeline_status            - 全链路状态 (worker 数 + 队列 + dead + ingest)
 *   5. pipeline_trace_aweme       - 按 aweme_id 单条 trace
 *   6. pipeline_trace_author      - 按 author 批量 trace (Cove 2026-07-23 16:21 拍板)
 *   7. pipeline_trace_domain      - 按 domain 批量 trace
 *   8. pipeline_stuck             - stuck processing 检测 (>N 分钟未动)
 *   9. pipeline_clear_dead        - 清 dead queue (默认 dry_run)
 *  10. pipeline_move_kb           - KB 卡跨 domain 物理 mv
 *  11. download_aweme             - 下载单个 aweme
 *  12. transcribe_aweme           - ASR 转写
 *  13. distill_aweme              - LLM 蒸馏
 *  14. upload_aweme               - 上传到 file-service
 *  15. ingest_to_yuxi             - KB 灌入 Yuxi (hz.siqing.cn)
 *  16. run_pipeline_batch         - 全流程批处理
 *  17. pipeline_retry_dead        - 重试 dead queue
 *
 * Transport: streamable HTTP on port 18092 (HK localhost, 2026-07-22 修复: 旧注释 18098 跟实际 systemd PORT=18092 不一致)
 * Cross-server: HZ agents call via nginx https://hk.siqing.cn/api/mcp/
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";
import cors from "cors";
import dotenv from "dotenv";

import { registerMonitorTools } from "./tools/monitor.js";
import { registerPipelineStatusTools } from "./tools/pipeline_status.js";
import { registerWorkerTools } from "./tools/worker.js";
import { registerYuxiTools } from "./tools/yuxi.js";
import { registerBatchTools } from "./tools/batch.js";

dotenv.config();

const PORT = parseInt(process.env.PORT || "18092");
const HOST = process.env.HOST || "127.0.0.1";
const MCP_TOKEN = process.env.MCP_TOKEN || "default-dev-token-change-me";
const USING_DEFAULT_TOKEN = !process.env.MCP_TOKEN;

// ─── Server setup ─────────────────────────────────────────────────────────────
const server = new McpServer({
  name: "content-pipeline-mcp",
  version: "0.1.0",
});

// ─── Register 10 tools ───────────────────────────────────────────────────────
registerMonitorTools(server);            // 1. monitor_check_now  2. monitor_status
registerPipelineStatusTools(server);     // 3. pipeline_status
registerWorkerTools(server);             // 4-7. download/transcribe/distill/upload
registerYuxiTools(server);               // 8. ingest_to_yuxi
registerBatchTools(server);              // 9. run_pipeline_batch  10. pipeline_retry_dead

// ─── HTTP transport ──────────────────────────────────────────────────────────
async function runHTTP() {
  const app = express();
  app.use(cors());
  app.use(express.json({ limit: "4mb" }));

  // Bearer token middleware for /mcp (auth required)
  app.use("/mcp", (req, res, next) => {
    if (process.env.MCP_NO_AUTH === "1") return next();
    const auth = req.headers["authorization"] || "";
    if (auth !== `Bearer ${MCP_TOKEN}`) {
      return res.status(401).json({ error: "Unauthorized", hint: "Set Authorization: Bearer $MCP_TOKEN" });
    }
    next();
  });

  app.post("/mcp", async (req, res) => {
    try {
      // Stateless: each request creates fresh transport
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      res.on("close", () => transport.close());
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (err: any) {
      console.error("[mcp] error:", err);
      res.status(500).json({ error: err.message || String(err) });
    }
  });

  // Health probe for systemd / monitoring
  app.get("/health", (_req, res) => {
    // 铁律 162.1: tools_count 从 server._registeredTools 动态计算, 跟硬编码漂移
    const toolsCount = Object.keys((server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools || {}).length;
    res.json({
      status: USING_DEFAULT_TOKEN ? "warning" : "ok",
      warnings: USING_DEFAULT_TOKEN ? ["MCP_TOKEN not set, using default 'default-dev-token-change-me'"] : [],
      service: "content-pipeline-mcp",
      version: "0.1.0",
      port: PORT,
      tools_count: toolsCount,
      pid: process.pid,
      uptime_s: Math.floor(process.uptime()),
      memory_mb: Math.round(process.memoryUsage().rss / 1024 / 1024),
    });
  });

  // List tools endpoint (for debugging / HZ dashboard introspection)
  // 铁律 162.1 (2026-07-24 18:43 Cove 拍板): /tools 必须 Bearer auth + 动态列真 tool list
  // 修前: 硬编码 12 个 tool (永远跟代码漂移) + 无 auth (信息泄露)
  // 修后: 从 server._registeredTools 动态取真 tool name + desc; 未授权 401
  app.get("/tools", (req, res, next) => {
    if (process.env.MCP_NO_AUTH === "1") return next();
    const auth = req.headers["authorization"] || "";
    if (auth !== `Bearer ${MCP_TOKEN}`) {
      return res.status(401).json({ error: "Unauthorized", hint: "Set Authorization: Bearer $MCP_TOKEN" });
    }
    next();
  }, async (_req, res) => {
    // MCP SDK 把 RegisteredTool 存在 server._registeredTools (TS private, 实际 JS 可访问)
    const registered = (server as unknown as { _registeredTools: Record<string, { title?: string; description?: string }> })._registeredTools || {};
    const tools = Object.entries(registered).map(([name, t]) => ({
      name,
      title: t.title,
      description: t.description,
    })).sort((a, b) => a.name.localeCompare(b.name));
    res.json({ tools_count: tools.length, tools });
  });

  app.listen(PORT, HOST, () => {
    console.error(`[content-pipeline-mcp] listening on http://${HOST}:${PORT}`);
    console.error(`[content-pipeline-mcp] POST /mcp  (MCP protocol)`);
    console.error(`[content-pipeline-mcp] GET  /health`);
    console.error(`[content-pipeline-mcp] GET  /tools`);
    // 铁律 12.5 强化: MCP_TOKEN 未设环境变量时启动报黄警告 + 计入 health
    if (USING_DEFAULT_TOKEN) {
      console.error(`[content-pipeline-mcp] ⚠️  WARNING: MCP_TOKEN 未设置, 使用默认 token "default-dev-token-change-me"`);
      console.error(`[content-pipeline-mcp] ⚠️  生产环境请设: export MCP_TOKEN=<random-32-bytes>`);
      console.error(`[content-pipeline-mcp] ⚠️  临时绕过 auth: export MCP_NO_AUTH=1`);
    } else {
      console.error(`[content-pipeline-mcp] ✅ MCP_TOKEN configured (length=${MCP_TOKEN.length})`);
    }
  });
}

runHTTP().catch((err) => {
  console.error("[content-pipeline-mcp] fatal:", err);
  process.exit(1);
});
