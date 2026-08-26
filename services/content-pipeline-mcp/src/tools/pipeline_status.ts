/**
 * tools/pipeline_status.ts — Tool 3: 全链路状态
 *
 * 返回: workers running + queue sizes + dead + Yuxi ingest progress
 *
 * 配置 (EX-P2-X + P1-3 + 铁律 138): WORKDIR / kb_id / 凭据 全部从环境变量读
 *   - V6_WORKDIR (默认 /home/main/douyin-data — 铁律 138 WORKDIR 一致 2026-07-22 Cove P0)
 *   - YUXI_KB_ID (默认 kb_ftl95bqw46)
 *   - YUXI_USERNAME / YUXI_PASSWORD (P1-2: 替代硬编码 admin:admin123)
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { getQueueStats, checkWorkersRunning, traceAweme, getStuckProcessing, clearDead, moveKb, traceByAuthor, traceByDomain } from "../wrapper/queue.js";
import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { readdirSync } from "node:fs";

// 铁律 138 WORKDIR 一致 (2026-07-22 Cove P0): 修前 /home/main/douyin-data/batch_v5_daya_1467 → 错路径
const WORKDIR = process.env.V6_WORKDIR || "/home/main/douyin-data";
const YUXI_KB_ID = process.env.YUXI_KB_ID || "kb_ftl95bqw46";
const YUXI_USERNAME = process.env.YUXI_USERNAME || "admin";
const YUXI_PASSWORD = process.env.YUXI_PASSWORD || "";

async function fetchYuxiStats(): Promise<any> {
  try {
    if (!YUXI_PASSWORD) {
      return { error: "YUXI_PASSWORD env var not set" };
    }
    // 铁律 165.2 P1-4 (2026-07-24 22:14 Cove 拍板): 加 AbortSignal.timeout 防 fetch 挂死
    // 修前: 无超时, hz.siqing.cn 挂了 → TCP 底层超时 2 分钟, MCP 请求同步挂住
    // 修后: 10s 超时, Express event loop 不被卡死
    const FETCH_TIMEOUT_MS = 10_000;
    // Login
    const loginRes = await fetch("https://hz.siqing.cn/yuxi/api/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: `username=${encodeURIComponent(YUXI_USERNAME)}&password=${encodeURIComponent(YUXI_PASSWORD)}`,
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!loginRes.ok) return { error: `login ${loginRes.status}` };
    const { access_token } = await loginRes.json() as any;

    // KB stats
    const kbRes = await fetch(
      `https://hz.siqing.cn/yuxi/api/knowledge/databases/${encodeURIComponent(YUXI_KB_ID)}`,
      {
        headers: { Authorization: `Bearer ${access_token}` },
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      }
    );
    if (!kbRes.ok) return { error: `kb ${kbRes.status}` };
    const kbData = await kbRes.json() as any;
    const s = kbData.stats || {};
    // P3-11: files_total 从 _index.json 实时读，不再硬编码 13300
    const total = Number(process.env.YUXI_KB_FILES_TOTAL) || 0;
    return {
      kb_id: YUXI_KB_ID,
      files_total: total,
      files_done: s.file_count ?? 0,
      pct: total > 0 ? (((s.file_count ?? 0) / total) * 100).toFixed(1) : null,
      chunks: s.chunk_count,
      tokens: s.token_count,
      processing: s.processing_count,
      pending_idx: s.pending_index_count,
    };
  } catch (e: any) {
    return { error: e.message };
  }
}

export function registerPipelineStatusTools(server: McpServer) {
  server.registerTool(
    "pipeline_status",
    {
      title: "Pipeline Status",
      description:
        "全链路状态: v6 worker 存活 + 各队列 (download/transcribe/distill/upload/dead) 大小 + Yuxi ingest 进度",
      inputSchema: {},
    },
    async () => {
      const queues = await getQueueStats();
      const workers = checkWorkersRunning();
      const yuxi = await fetchYuxiStats();

      // Disk usage
      const videosDir = join(WORKDIR, "videos");
      let mp4Count = "0";
      if (existsSync(videosDir)) {
        try {
          // P3-4 + 2026-07-22 修复: 用顶部 import 的 readdirSync, 删冗余动态 import
          // (修前: 每次调用都 await import("node:fs") 浪费一次模块加载)
          mp4Count = String(readdirSync(videosDir).filter(f => f.endsWith(".mp4")).length);
        } catch {
          mp4Count = "0";
        }
      }

      const out = {
        timestamp: new Date().toISOString(),
        workers,
        workers_alive_count: Object.values(workers).filter(Boolean).length,
        queues,
        yuxi_ingest: yuxi,
        videos_dir_mp4_count: parseInt(mp4Count),
        workdir: WORKDIR,
      };
      return {
        content: [{ type: "text", text: JSON.stringify(out, null, 2) }],
        structuredContent: out,
      };
    }
  );

  // ============= Tool: pipeline_trace_aweme (铁律 121) =============
  server.registerTool(
    "pipeline_trace_aweme",
    {
      title: "Pipeline Trace Aweme",
      description:
        "按 aweme_id 单条全链路追踪 (铁律 121): 4 阶段 × 4 状态 + 死信 + 文件存在性 + timeline. 走 SQLite queue.db 直读, 不读 jsonl.",
      inputSchema: {
        aweme_id: z.string().describe("抖音作品 ID (e.g. 7657206515769560383)"),
      },
    },
    async ({ aweme_id }) => {
      const trace = await traceAweme(aweme_id);
      return {
        content: [{ type: "text", text: JSON.stringify(trace, null, 2) }],
        structuredContent: trace,
      };
    }
  );

  // ============= Tool: pipeline_trace_author (Cove 2026-07-23 16:21 拍板: 必须 MCP 禁裸 SQL) =============
  server.registerTool(
    "pipeline_trace_author",
    {
      title: "Pipeline Trace by Author",
      description:
        "按 author (e.g. '玉留君', '大雅') 批量全链路追踪. 返回 stage×status 矩阵 + fs 存在性 + 缺口分析 (Cascade/Fs missing). LIKE 匹配兼容空格变体 ('玉留君 大得鉴宝' vs '玉留君   大得鉴宝').",
      inputSchema: {
        author: z.string().min(1).describe("作者名 (LIKE 模糊匹配). e.g. '玉留君', '大雅'"),
      },
    },
    async ({ author }) => {
      const trace = await traceByAuthor(author);
      return {
        content: [{ type: "text", text: JSON.stringify(trace, null, 2) }],
        structuredContent: trace,
      };
    }
  );

  // ============= Tool: pipeline_trace_domain (Cove 2026-07-23 16:21 拍板) =============
  server.registerTool(
    "pipeline_trace_domain",
    {
      title: "Pipeline Trace by Domain",
      description:
        "按 domain (e.g. 'jade', 'livestream', 'universal') 批量全链路追踪. 接口与 pipeline_trace_author 平行.",
      inputSchema: {
        domain: z.string().min(1).describe("domain 字段 (精确匹配). e.g. 'jade', 'livestream'"),
      },
    },
    async ({ domain }) => {
      const trace = await traceByDomain(domain);
      return {
        content: [{ type: "text", text: JSON.stringify(trace, null, 2) }],
        structuredContent: trace,
      };
    }
  );

  // ============= Tool: pipeline_stuck (铁律 121) =============
  server.registerTool(
    "pipeline_stuck",
    {
      title: "Pipeline Stuck Processing",
      description:
        "所有 stuck processing (>N 分钟未动) — 走 SQLite queue.db, 不读 jsonl.",
      inputSchema: {
        minutes: z.number().int().min(1).max(120).optional()
          .describe("最小 stuck 时长 (分钟), 默认 5"),
      },
    },
    async ({ minutes }) => {
      const rows = await getStuckProcessing(minutes ?? 5);
      return {
        content: [{
          type: "text",
          text: JSON.stringify({ count: rows.length, rows }, null, 2)
        }],
        structuredContent: { count: rows.length, rows },
      };
    }
  );

  // ============= Tool: pipeline_clear_dead (铁律 123 默认 dry_run) =============
  server.registerTool(
    "pipeline_clear_dead",
    {
      title: "Pipeline Clear Dead Queue",
      description:
        "清 stage='dead' 历史累计. 默认 dry_run=true (只统计不删). needs_manual_review=1 自动保护. 删前写 audit log + VACUUM 回收空间.",
      inputSchema: {
        older_than_days: z.number().int().min(0).max(365).optional()
          .describe("保留 N 天内的 dead (默认 30). 0 = 全清."),
        author: z.string().optional()
          .describe("只清特定作者 (e.g. '大雅', '主播培训唐sir'). 不传 = 全部."),
        dry_run: z.boolean().optional()
          .describe("默认 true. 真删必须显式 false. 警告: 删后无法恢复 (依赖 audit log)."),
      },
    },
    async (args) => {
      const result = await clearDead({
        older_than_days: args.older_than_days,
        author: args.author,
        dry_run: args.dry_run,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        structuredContent: result,
      };
    }
  );

  // ============= Tool: pipeline_move_kb (铁律 123 带审计) =============
  server.registerTool(
    "pipeline_move_kb",
    {
      title: "Pipeline Move KB Cards",
      description:
        "KB 卡跨 domain 物理移动: mv 文件 + 改 frontmatter domain. 写 audit log (含 reason). 不可逆 (备份在 git history).",
      inputSchema: {
        aweme_ids: z.array(z.string()).min(1)
          .describe("要移的 KB 卡 aweme_id 列表. 找不到的会报 not_found."),
        target_domain: z.enum(["livestream", "jade", "universal", "unknown"])
          .describe("目标 domain. 同一 domain 的会 skip (already in)."),
        reason: z.string().min(3)
          .describe("必填. e.g. 'cove_2026-07-21_99_统一位置'. 写入 audit log."),
      },
    },
    async ({ aweme_ids, target_domain, reason }) => {
      const result = moveKb({
        aweme_ids,
        target_domain,
        reason,
      });
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        structuredContent: result,
      };
    }
  );
}
