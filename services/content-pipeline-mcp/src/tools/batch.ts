/**
 * tools/batch.ts — Tools 9-10: 批处理 + 重试
 *
 * 铁律 121 (2026-07-21 19:29 Cove 拍板): MCP 入队必须写 SQLite queue.db,
 *      禁止 readFileSync/appendFileSync 写 jsonl. 之前 worker 切 SQLite 后
 *      MCP 没跟上, 导致 run_pipeline_batch / pipeline_retry_dead 入队永远
 *      不会被 v6 worker 处理 (断链 bug).
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { execFileSync } from "node:child_process";
import {
  QUEUES,
  execSqlite,
  escapeSqlString,
  queuePushSqlite as sharedQueuePushSqlite,
  isPendingOrProcessingSqlite as sharedIsPendingOrProcessingSqlite,
} from "../wrapper/queue.js";

// 铁律 12.6 (P3-5): batch 入队也要验证 19 位数字
const AWEME_ID_REGEX = /^[0-9]{19}$/;
const awemeIdSchema = z.string().regex(AWEME_ID_REGEX, "aweme_id 必须是 19 位数字");
const urlSchema = z.string().url("url 必须是合法 HTTP(S) URL");

const VALID_STAGES = ["download", "transcribe", "distill", "upload"] as const;
type Stage = typeof VALID_STAGES[number];

// 铁律 165.2 P2-2 (2026-07-24 22:14 Cove 拍板): 使用 wrapper/queue.ts 共享实现,
// 修前: batch.ts / worker.ts 各自重复实现 queuePushSqlite + dedup check, 错误处理不一致
// 修后: 三个调用点共用 wrapper 版 (wrapper 负责 UNIQUE 区分 duplicate vs 真错)

async function getDeadAwemeIds(stage?: Stage, limit?: number): Promise<Array<{ aweme_id: string; payload: Record<string, unknown> }>> {
  /**查 dead stage 的 aweme_id (铁律 121: 走 SQLite, 不读 jsonl)
   *
   * Bug fix 2026-07-22 (铁律 134): limit 500 + maxBuffer 50MB
   * 铁律 165.2 (2026-07-24): 异步化 (跟随 wrapper.execSqlite async 化)
   */
  const safeLimit = Math.min(limit ?? 500, 5000);
  const sql = `SELECT aweme_id, payload FROM queue WHERE stage='dead' AND status='dead' ORDER BY id DESC LIMIT ${safeLimit};`;
  const out = await execSqlite("sqlite3", ["-json", QUEUES.db, sql], {
    encoding: "utf-8",
    timeout: 10000,
    maxBuffer: 50 * 1024 * 1024,
  });
  if (!out.trim()) return [];
  const rows = JSON.parse(out) as Array<{ aweme_id: string; payload: string }>;
  return rows.map((r) => {
    let payload: Record<string, unknown> = {};
    try { payload = JSON.parse(r.payload); } catch { /* ignore bad json */ }
    return { aweme_id: r.aweme_id, payload };
  });
}

export function registerBatchTools(server: McpServer) {
  // Tool 9: run_pipeline_batch
  server.registerTool(
    "run_pipeline_batch",
    {
      title: "Run Pipeline Batch",
      description: "批量灌一批 aweme_id 到 download 队列 (SQLite queue.db, 铁律 121). v6 worker 自动拾取.",
      inputSchema: {
        aweme_ids: z.array(awemeIdSchema).describe("一批 aweme_id 列表 (每个 19 位数字)"),
        url: urlSchema.optional().describe("可选: 抖音 share URL (辅助)"),
      },
    },
    async ({ aweme_ids, url }) => {
      let enqueued = 0;
      let skipped = 0;
      const failedIds: string[] = [];

      for (const aid of aweme_ids) {
        // L1 软拦截: 查现有 pending/processing (铁律 109)
        if (await sharedIsPendingOrProcessingSqlite("download", aid)) {
          skipped++;
          continue;
        }
        // 写 SQLite (共享实现)
        const r = await sharedQueuePushSqlite("download", aid, {
          aweme_id: aid,
          status: "pending",
          enqueued_at: new Date().toISOString(),
          via: "mcp_batch",
          url: url ?? null,
        });
        if (!r.ok) {
          failedIds.push(`${aid}: ${r.error}`);
        } else {
          enqueued++;
        }
      }
      return {
        content: [{
          type: "text",
          text: `Enqueued ${enqueued}, skipped ${skipped} (already in queue)${failedIds.length ? `, failed ${failedIds.length}` : ""}`
        }],
        structuredContent: {
          enqueued, skipped, total: aweme_ids.length,
          failed: failedIds.length > 0 ? failedIds : undefined
        },
      };
    }
  );

  // Tool 10: pipeline_retry_dead (铁律 158: DELETE dead source + INSERT target + 真 retry 数)
  server.registerTool(
    "pipeline_retry_dead",
    {
      title: "Retry Dead Queue",
      description: "删除 dead stage 源 row + 重推入目标 stage (默认 download). 走 SQLite, 不读 jsonl (铁律 121). 铁律 158 fix: 旧版只 INSERT 不 DELETE, retried 数字被 UNIQUE INDEX 拦截后报假数.",
      inputSchema: {
        stage: z.enum(["download", "transcribe", "distill", "upload"]).optional()
          .describe("重推到哪个 stage (默认 download)"),
        limit: z.number().optional().describe("最多重推多少条 (默认全部)"),
      },
    },
    async ({ stage, limit }) => {
      const targetStage: Stage = stage ?? "download";

      // 1. 查 dead stage 的 aweme_ids (SQLite 直读)
      const deadItems = await getDeadAwemeIds(targetStage, limit);
      if (deadItems.length === 0) {
        return { content: [{ type: "text", text: "No dead queue" }] };
      }

      // 2. 重推入目标 stage (SQLite) + DELETE dead source
      let retried = 0;
      let skipped = 0;
      let cleaned = 0;  // 已在 target stage done, 只 DELETE dead source (cleanup)
      const seen: string[] = [];
      const failedIds: string[] = [];
      for (const item of deadItems) {
        const aid = item.aweme_id;
        if (!aid) continue;
        if (await sharedIsPendingOrProcessingSqlite(targetStage, aid)) {
          skipped++;
          continue;
        }
        // 只保留原始 metadata
        const cleanMeta: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(item.payload)) {
          if (k.startsWith("_") || k === "dead_reason" || k === "dead_at" || k === "retries" ||
              k === "status" || k === "via" || k === "retry_at") continue;
          cleanMeta[k] = v;
        }

        // 检查 target stage 是否已 done (幂等重复 dead row)
        const targetDone = await isTargetStageDoneSqlite(targetStage, aid);

        if (!targetDone) {
          // 真 retry: INSERT target stage
          const r = await sharedQueuePushSqlite(targetStage, aid, {
            ...cleanMeta,
            aweme_id: aid,
            status: "pending",
            retry_at: new Date().toISOString(),
            via: "mcp_retry_dead",
            orig_dead_reason: item.payload.dead_reason ?? null,
          });
          if (!r.ok) {
            failedIds.push(`${aid}: ${r.error}`);
            continue;
          }
          retried++;
          seen.push(aid);
        } else {
          cleaned++;
        }

        // DELETE dead source row
        const delR = await deleteDeadSourceSqlite(aid);
        if (!delR.ok) {
          failedIds.push(`${aid} DELETE dead: ${delR.error}`);
        }
      }
      return {
        content: [{
          type: "text",
          text: `Retried ${retried} (真入队), cleaned ${cleaned} (幂等已 done 清理), skipped ${skipped} (active in target), total dead=${deadItems.length}${failedIds.length ? `, failed ${failedIds.length}` : ""}`
        }],
        structuredContent: {
          retried, cleaned, skipped, total: deadItems.length,
          target_stage: targetStage, aweme_ids: seen,
          failed: failedIds.length > 0 ? failedIds : undefined
        },
      };
    }
  );
}

/** 铁律 158: 检查 target stage 是否已 done (幂等重复 dead row 检测) */
async function isTargetStageDoneSqlite(stage: Stage, awemeId: string): Promise<boolean> {
  try {
    const out = await execSqlite("sqlite3", ["-json", QUEUES.db,
      `SELECT status FROM queue WHERE stage='${escapeSqlString(stage)}' AND aweme_id='${escapeSqlString(awemeId)}' LIMIT 1;`
    ], { encoding: "utf-8", timeout: 5000, maxBuffer: 1024 });
    if (!out.trim()) return false;
    const rows = JSON.parse(out) as Array<{ status: string }>;
    return rows.length > 0 && rows[0].status === "done";
  } catch {
    return false;
  }
}

/** 铁律 158: 删除 dead stage 的源 row */
async function deleteDeadSourceSqlite(awemeId: string): Promise<{ ok: boolean; error?: string }> {
  try {
    await execSqlite("sqlite3", [QUEUES.db,
      `DELETE FROM queue WHERE stage='dead' AND status='dead' AND aweme_id='${escapeSqlString(awemeId)}';`
    ], { encoding: "utf-8", timeout: 5000, maxBuffer: 1024 });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}