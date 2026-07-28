/**
 * tools/worker.ts — Tools 4-7: 4 个 worker stage 单独触发
 *
 * 铁律 121 (2026-07-21 19:29 Cove 拍板): MCP 入队必须写 SQLite queue.db,
 *      禁止 appendFileSync 写 jsonl. 之前 worker 切 SQLite 后 MCP 没跟上,
 *      导致 MCP 入队永远不会被 v6 worker 处理 (断链 bug).
 *
 * 铁律 165.2 P2-2 (2026-07-24 22:14 Cove 拍板): 用 wrapper 共享 queuePushSqlite
 *      修前: worker.ts 各自实现 → 与 batch.ts 不一致, 维护负担
 *      修后: 统一用 wrapper/queue.ts 共享实现
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  queuePushSqlite,
  isPendingOrProcessingSqlite,
} from "../wrapper/queue.js";

// 铁律 12.6 (P3-5): aweme_id 必须是 19 位数字 (抖音)
const AWEME_ID_REGEX = /^[0-9]{19}$/;
const awemeIdSchema = z.string().regex(AWEME_ID_REGEX, "aweme_id 必须是 19 位数字");
const urlSchema = z.string().url("url 必须是合法 HTTP(S) URL");

// 铁律 192 (Phase 4-ii / 2026-07-28 14:47 Cove 拍 C 方案):
// text_distill service 在 host 跑, 接受任意文本入队 distill (aweme_id = text-{sha1[:16]})
// MCP 容器通过 host.docker.internal:18091 调 (Linux Docker 27+ host-gateway)
const TEXT_DISTILL_URL = process.env.TEXT_DISTILL_URL || "http://host.docker.internal:18091/distill";
const TEXT_DISTILL_TOKEN = process.env.TEXT_DISTILL_TOKEN || "";

export function registerWorkerTools(server: McpServer) {
  // Tool 4: download_aweme
  server.registerTool(
    "download_aweme",
    {
      title: "Download Aweme",
      description: "入队下载任务 (SQLite queue.db, 铁律 121). v6 download worker 会自动拾取. mp4 写入 videos/",
      inputSchema: {
        aweme_id: awemeIdSchema.describe("抖音 aweme_id, 19位数字"),
        url: urlSchema.optional().describe("抖音分享链接, 用于辅助"),
      },
    },
    async ({ aweme_id, url }) => {
      if (await isPendingOrProcessingSqlite("download", aweme_id)) {
        return { content: [{ type: "text", text: `aweme_id ${aweme_id} already in download queue` }] };
      }
      const r = await queuePushSqlite("download", aweme_id, {
        aweme_id,
        status: "pending",
        enqueued_at: new Date().toISOString(),
        via: "mcp",
        url,
      });
      if (!r.ok) {
        return { content: [{ type: "text", text: `Failed to enqueue: ${r.error}` }],
                 structuredContent: { aweme_id, status: "failed", stage: "download", error: r.error } };
      }
      return {
        content: [{ type: "text", text: r.duplicate
          ? `aweme_id ${aweme_id} already pending (L2 dedup)`
          : `Enqueued ${aweme_id} for download` }],
        structuredContent: { aweme_id, status: r.duplicate ? "duplicate" : "enqueued", stage: "download" },
      };
    }
  );

  // Tool 5: transcribe_aweme
  server.registerTool(
    "transcribe_aweme",
    {
      title: "Transcribe Aweme",
      description: "入队转写任务 (SQLite queue.db, 铁律 121). 触发 ASR",
      inputSchema: {
        aweme_id: awemeIdSchema,
      },
    },
    async ({ aweme_id }) => {
      if (await isPendingOrProcessingSqlite("transcribe", aweme_id)) {
        return { content: [{ type: "text", text: `aweme_id ${aweme_id} already in transcribe queue` }] };
      }
      const r = await queuePushSqlite("transcribe", aweme_id, {
        aweme_id,
        status: "pending",
        enqueued_at: new Date().toISOString(),
        via: "mcp",
      });
      if (!r.ok) {
        return { content: [{ type: "text", text: `Failed to enqueue: ${r.error}` }],
                 structuredContent: { aweme_id, status: "failed", stage: "transcribe", error: r.error } };
      }
      return {
        content: [{ type: "text", text: r.duplicate
          ? `aweme_id ${aweme_id} already pending (L2 dedup)`
          : `Enqueued ${aweme_id} for transcribe` }],
        structuredContent: { aweme_id, status: r.duplicate ? "duplicate" : "enqueued", stage: "transcribe" },
      };
    }
  );

  // Tool 6: distill_aweme
  server.registerTool(
    "distill_aweme",
    {
      title: "Distill Aweme",
      description: "入队蒸馏任务 (SQLite queue.db, 铁律 121). 触发 LLM 蒸馏到 KB 卡",
      inputSchema: {
        aweme_id: awemeIdSchema,
      },
    },
    async ({ aweme_id }) => {
      if (await isPendingOrProcessingSqlite("distill", aweme_id)) {
        return { content: [{ type: "text", text: `aweme_id ${aweme_id} already in distill queue` }] };
      }
      const r = await queuePushSqlite("distill", aweme_id, {
        aweme_id,
        status: "pending",
        enqueued_at: new Date().toISOString(),
        via: "mcp",
      });
      if (!r.ok) {
        return { content: [{ type: "text", text: `Failed to enqueue: ${r.error}` }],
                 structuredContent: { aweme_id, status: "failed", stage: "distill", error: r.error } };
      }
      return {
        content: [{ type: "text", text: r.duplicate
          ? `aweme_id ${aweme_id} already pending (L2 dedup)`
          : `Enqueued ${aweme_id} for distill` }],
        structuredContent: { aweme_id, status: r.duplicate ? "duplicate" : "enqueued", stage: "distill" },
      };
    }
  );

  // Tool 7: upload_aweme
  server.registerTool(
    "upload_aweme",
    {
      title: "Upload Aweme",
      description: "入队上传任务 (SQLite queue.db, 铁律 121). 触发 mp4/md/srt 三件套上传到 file-service",
      inputSchema: {
        aweme_id: awemeIdSchema,
      },
    },
    async ({ aweme_id }) => {
      if (await isPendingOrProcessingSqlite("upload", aweme_id)) {
        return { content: [{ type: "text", text: `aweme_id ${aweme_id} already in upload queue` }] };
      }
      const r = await queuePushSqlite("upload", aweme_id, {
        aweme_id,
        status: "pending",
        enqueued_at: new Date().toISOString(),
        via: "mcp",
      });
      if (!r.ok) {
        return { content: [{ type: "text", text: `Failed to enqueue: ${r.error}` }],
                 structuredContent: { aweme_id, status: "failed", stage: "upload", error: r.error } };
      }
      return {
        content: [{ type: "text", text: r.duplicate
          ? `aweme_id ${aweme_id} already pending (L2 dedup)`
          : `Enqueued ${aweme_id} for upload` }],
        structuredContent: { aweme_id, status: r.duplicate ? "duplicate" : "enqueued", stage: "upload" },
      };
    }
  );

  // Tool 8: text_distill (Phase 4-ii, 2026-07-28 14:47 Cove 拍 C 方案)
  // 接受任意文本字符串 → 通过 HTTP 调 host 上的 text-distill-service (port 18091)
  // → service 调 enqueue_text.py → 写盘 + queue_push
  // 注意: 这个 tool 不写 queue.db 直接, 完全委托给 text-distill-service
  // (因为 MCP 容器无 python3 + DATA_DIR ro mount, 无法直接入队)
  server.registerTool(
    "text_distill",
    {
      title: "Text Distill (任意文本蒸馏)",
      description: "把任意文本字符串入队到 distill stage (Phase 4-ii, C 方案). 通过 HTTP 调 host 上的 text-distill-service (port 18091). 接受 text / clipboard / file 三种输入. dedup: text-{sha1[:16]} 唯一. KB 卡产出后约 30s. 用于把微信/公众号/网页/PDF/邮件等任意文本一键蒸馏到 KB.",
      inputSchema: {
        text: z.string().min(5).describe("要蒸馏的文本 (至少 5 字符, 推荐 100+ 字符)"),
        source_name: z.string().min(1).describe("来源说明, 写到每张 KB 卡 source 字段 (例: '微信群聊 · 玉友实战')"),
        domain: z.enum(["jade", "livestream"]).default("jade").describe("蒸馏领域 (jade=玉石 / livestream=直播带货)"),
        author: z.string().default("text_input").describe("作者 / 来源账号 (默认 text_input)"),
        dry_run: z.boolean().default(false).describe("true = 只打印不写盘不入队"),
      },
    },
    async ({ text, source_name, domain, author, dry_run }) => {
      // 调 text-distill-service (Phase 4-ii C 方案)
      try {
        const url = new URL(TEXT_DISTILL_URL);
        if (dry_run) url.searchParams.set("dry_run", "1");

        const r = await fetch(url.toString(), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(TEXT_DISTILL_TOKEN ? { "Authorization": `Bearer ${TEXT_DISTILL_TOKEN}` } : {}),
          },
          body: JSON.stringify({ text, source_name, domain, author }),
          // 30s timeout (enqueue 是写盘 + 入队, 不会阻塞)
          signal: AbortSignal.timeout(30000),
        });

        const body = await r.text();
        let parsed: any;
        try { parsed = JSON.parse(body); } catch { parsed = { raw: body }; }

        if (r.ok) {
          return {
            content: [{ type: "text", text: `✓ text_distill ${parsed.aweme_id ? `aweme_id=${parsed.aweme_id}` : ""} ${parsed.dry_run ? "(dry-run)" : "enqueued"}` }],
            structuredContent: {
              ok: true,
              aweme_id: parsed.aweme_id || null,
              dry_run: parsed.dry_run || false,
              source_name,
              domain,
            },
          };
        }

        // 4xx/5xx 透传
        return {
          content: [{ type: "text", text: `✗ text_distill failed: ${parsed.error || r.statusText}` }],
          structuredContent: {
            ok: false,
            status: r.status,
            error: parsed.error || r.statusText,
            stderr: parsed.stderr || "",
          },
        };
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        return {
          content: [{ type: "text", text: `✗ text_distill HTTP error: ${msg}` }],
          structuredContent: { ok: false, error: `fetch_failed: ${msg}` },
        };
      }
    }
  );
}
