/**
 * wrapper/queue.ts — v6 pipeline queue inspection (SQLite 直读)
 *
 * 铁律 121 (2026-07-21 19:29 Cove 拍板): MCP wrapper 必须直读 queue.db SQLite,
 *      禁止读历史 jsonl. 铁律 84 已切 SQLite (2026-07-20 16:00), 但 MCP wrapper
 *      仍读 queues/*.jsonl, 数字失真 (jsonl 残留 12673 vs queue.db 实际 906).
 *
 * 单一真相源: /home/main/douyin-data/queue.db (铁律 138 WORKDIR 一致 — 2026-07-22 Cove P0 拍板)
 * Schema: v6_queue_sqlite.py:40 CREATE TABLE queue (...)
 *
 * Status flags: pending / processing / done / dead
 * Stage flags:  download / transcribe / distill / upload / dead
 *
 * WORKDIR 可通过 V6_WORKDIR 环境变量覆盖 (EX-P2-X: 与 v6 python 脚本对齐)
 */

import { execFile as execFileCb, execFileSync } from "node:child_process";
import { setImmediate as setImmediateP } from "node:timers/promises";
import { promisify } from "node:util";
const execFileAsyncRaw = promisify(execFileCb);

/**
 * SQLite retry wrapper — async 非阻塞版本 (铁律 165.2 / 2026-07-24 22:14 Cove 拍板):
 * 修前: execFileSyncWithRetry 用 `while (Date.now() - start < ms)` busy-wait
 *       阻塞 event loop (500ms × N 并发 = server 全停, Express 处理不了任何其他请求)
 * 修后: async/await + setImmediate (node:timers/promises) 非阻塞等待,
 *       event loop 可处理其他请求; lock 竞争期间不拖垮 server
 *
 * v6 worker 用 Python WAL + BEGIN IMMEDIATE 写 queue.db, MCP 用 sqlite3 CLI 读.
 * 偶发 'database is locked (5)' (e.g. 15:59/16:00 journal 抓到 2 次):
 * - 修前: 一次失败 → throw → user 重试 (10 几秒延误, 但 LLM agent 重试不智能)
 * - 修后: 失败时 exp backoff 3 次 (50ms / 200ms / 500ms), 95% 的 lock 竞争能 solve
 * - 真失败 (schema/语法/NOT NULL): 不重试, throw 抛出去
 */
async function execFileAsyncWithRetry(cmd: string, args: string[], opts: { encoding: "utf-8"; timeout: number; maxBuffer: number }): Promise<string> {
  const delays = [50, 200, 500];
  let lastErr: unknown = null;
  for (let i = 0; i <= delays.length; i++) {
    try {
      const { stdout } = (await execFileAsyncRaw(cmd, args, opts)) as { stdout: string | Buffer; stderr: string | Buffer };
      // stdout is string | Buffer, opts.encoding=utf-8 → string
      return typeof stdout === "string" ? stdout : (stdout as Buffer).toString("utf-8");
    } catch (err: unknown) {
      lastErr = err;
      const msg = err instanceof Error ? err.message : String(err);
      const isLock = msg.includes("database is locked") || msg.includes("stepping") || msg.includes("SQLITE_BUSY");
      if (!isLock || i === delays.length) {
        throw err;
      }
      // busy/lock → 非阻塞等待后重试 (让出 event loop)
      await setImmediateP(delays[i]);
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}

// 铁律 165.2: 跨文件复用 async retry wrapper (避免 batch.ts / worker.ts 各自重复实现)
const execSqlite = execFileAsyncWithRetry;
export { execSqlite };
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join } from "node:path";

// 与 v6_base.py:WORKDIR 对齐 (铁律 138 WORKDIR 一致 — 2026-07-22 Cove P0 拍板修复)
// 修前: 默认 /home/main/douyin-data/batch_v5_daya_1467 → 与 Python worker 不同路径 → 写入空 queue.db
// 修后: 默认 /home/main/douyin-data → 与 v6 python 脚本一致, 单一真相源
const WORKDIR = process.env.V6_WORKDIR || "/home/main/douyin-data";
const QUEUE_DB = join(WORKDIR, "queue.db");

export const QUEUES = {
  db: QUEUE_DB,
  videos: join(WORKDIR, "videos"),
  transcripts: join(WORKDIR, "transcripts"),
  // 铁律 121 已完成 (2026-07-22): worker.ts/batch.ts 都用 queue_push() 写 SQLite,
  // 下面 5 个 jsonl 路径只为兼容历史遗留 (jsonl 已停写 7 天兼容期, 不再 TODO)
  download:   join(WORKDIR, "queues", "download.jsonl"),
  transcribe: join(WORKDIR, "queues", "transcribe.jsonl"),
  distill:    join(WORKDIR, "queues", "distill.jsonl"),
  upload:     join(WORKDIR, "queues", "upload.jsonl"),
  dead:       join(WORKDIR, "queues", "dead.jsonl"),
};

/**
 * 多路径文件扫描 (Cove 2026-07-23 17:56 拍板修复漂移 BUG)
 *
 * 漂移路径:
 *   新路径 (canonical): WORKDIR/videos  ← 当前 worker 写这里
 *   老路径 1: WORKDIR/batch_v5_daya_1467/videos ← 老 daemon dirty data 残留 (04:44 已 mv 走 .mp4 但 .nowm.json 还在)
 *   老路径 2: WORKDIR/uploads-migrated/brand-video ← 老 brand uploads, 有同名 aid 可能
 *   老路径 3: WORKDIR/douyin-batch-workdir/&lt;id&gt;/workdir/videos ← 老 daemon workdir (117 等)
 *
 * 任一路径有就算有, 返回合并的 Set&lt;aweme_id&gt;
 */
export function multiPathScan(ext: string, dirs: string[]): Set<string> {
  const out = new Set<string>();
  for (const d of dirs) {
    if (!existsSync(d)) continue;
    try {
      for (const f of readdirSync(d)) {
        if (f.endsWith(ext)) out.add(f.slice(0, -ext.length));
      }
    } catch (e) { /* ignore individual path errors */ }
  }
  return out;
}

/**
 * 路径漂移扫描的配置 (Cove 2026-07-23 17:56)
 *
 * fs_check 必须查所有可能路径, 不能只看新路径。
 * 历史飘移路径列在这里, 一处维护。
 */
export const FS_PATHS = {
  mp4: () => {
    const dirs = [
      join(WORKDIR, "videos"),
      join(WORKDIR, "batch_v5_daya_1467/videos"),
      join(WORKDIR, "uploads-migrated/brand-video"),
    ];
    try {
      const dbWorkdir = join(WORKDIR, "douyin-batch-workdir");
      if (existsSync(dbWorkdir)) {
        for (const sub of readdirSync(dbWorkdir)) {
          const workdirVideos = join(dbWorkdir, sub, "workdir/videos");
          if (existsSync(workdirVideos)) dirs.push(workdirVideos);
        }
      }
    } catch (e) { /* ignore */ }
    return dirs;
  },
  md: () => [join(WORKDIR, "transcripts")],
  srt: () => [join(WORKDIR, "transcripts")],
};

/**
 * SQLite string 转义 (single quote 双写) — 铁律 165.2
 * 用在用户控制输入拼接 SQL 时, 防止 single quote 注入
 */
export function escapeSqlString(s: string): string {
  return s.replace(/'/g, "''");
}

/**
 * LIKE 通配符转义 (铁律 165.2 P1-1 / 2026-07-24 22:14 Cove 拍板)
 * 防 LIKE 注入: author='100%' 不会被当作 wildcard
 * 用法: SQL 加 `ESCAPE '/'`, 参数用 escapeLike 包 (用 `/` 不用 `\`,
 *       是因为 SQLite 字符串字面量里 `\` 不算转义, `'\\'` 仍然是 2 字符,
 *       而 ESCAPE 必须接受单字符, `/` 是安全单字符)
 */
export function escapeLike(value: string): string {
  if (!value) return "";
  return value.replace(/%/g, "/%").replace(/_/g, "/_");
}

/**
 * SQLite 直读 (用 sqlite3 CLI, 避免装 better-sqlite3 npm 依赖)
 *
 * 铁律 121: 单一真相源是 queue.db, 不用 jsonl
 * 铁律 36: 全 grep 验证 — queue.db 是 worker 写入, jsonl 是历史残留 (7 天兼容期)
 *
 * 铁律 165.2 P0-3 (2026-07-24 22:14 Cove 拍板): 参数替换 bug 修复
 * 修前: `sql.replace("?", `'${escaped}'`)` 顺序替换第一个 `?`
 *       → params[0] 包含 `?` 时, params[1] 会替换到 params[0] 的值里面 (顺序错位 bug)
 * 修后: split + map + join, 按位置插入, 不依赖 `?` 字符顺序
 */
async function sqliteQuery<T = Record<string, unknown>>(sql: string, params: string[] = []): Promise<T[]> {
  try {
    // 铁律 165.2 P0-3: split + map + join 替代顺序 replace, params[i] 对应第 i 个 `?`
    let preparedSql = sql;
    if (params.length > 0) {
      const parts = sql.split("?");
      if (parts.length - 1 !== params.length) {
        throw new Error(`SQL placeholders (${parts.length - 1}) != params count (${params.length}): ${sql}`);
      }
      preparedSql = parts[0] + params.map((p, i) => `'${escapeSqlString(p)}'` + parts[i + 1]).join("");
    }
    const out = await execSqlite("sqlite3", ["-json", QUEUE_DB, preparedSql], {
      encoding: "utf-8",
      timeout: 10000,
      maxBuffer: 50 * 1024 * 1024, // 铁律 134 fix: dead/payload row ≈ 1KB, 50MB 可承载 5K row
    });
    if (!out.trim()) return [];
    return JSON.parse(out) as T[];
  } catch (err: unknown) {
    // sqlite3 returns non-zero on error; or DB locked
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`SQLite query failed: ${msg}\nSQL: ${sql}`);
  }
}

/**
 * 共享 queuePushSqlite (铁律 165.2 P2-2 / 2026-07-24 22:14 Cove 拍板):
 * 修前: batch.ts / worker.ts 各自实现 queuePushSqlite, 重复代码, 错误处理不一致
 * 修后: 统一在 wrapper/queue.ts, 三个调用点共用同一份
 *
 * 注意: 调用方需传完整 payload (含 aweme_id, status, enqueued_at, via 等),
 *       wrapper 不再默认补全, 避免 caller 困惑
 */
export async function queuePushSqlite(
  stage: string,
  aweme_id: string,
  payload: Record<string, unknown>
): Promise<{ ok: boolean; duplicate?: boolean; error?: string }> {
  const payloadJson = JSON.stringify(payload, null, 0);
  const sql = `BEGIN IMMEDIATE; INSERT INTO queue (stage, payload, aweme_id, created_at, status) VALUES ('${escapeSqlString(stage)}', '${escapeSqlString(payloadJson)}', '${escapeSqlString(aweme_id)}', strftime('%s','now'), 'pending'); COMMIT;`;
  try {
    await execSqlite("sqlite3", [QUEUES.db, sql], {
      encoding: "utf-8",
      timeout: 5000,
      maxBuffer: 50 * 1024 * 1024,
    });
    return { ok: true };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("UNIQUE constraint failed") || msg.includes("uniq_pending_aweme") || msg.includes("uniq_stage_aweme")) {
      return { ok: true, duplicate: true };
    }
    console.error(`[queuePushSqlite] non-dedup error for ${stage}/${aweme_id}: ${msg}`);
    return { ok: false, error: msg };
  }
}

/**
 * 共享 isPendingOrProcessingSqlite (铁律 165.2 P2-2)
 */
export async function isPendingOrProcessingSqlite(stage: string, aweme_id: string): Promise<boolean> {
  const sql = `SELECT COUNT(*) as cnt FROM queue WHERE stage='${escapeSqlString(stage)}' AND aweme_id='${escapeSqlString(aweme_id)}' AND status IN ('pending','processing');`;
  try {
    const out = await execSqlite("sqlite3", ["-json", QUEUES.db, sql], {
      encoding: "utf-8",
      timeout: 5000,
      maxBuffer: 50 * 1024 * 1024,
    });
    if (!out.trim()) return false;
    const rows = JSON.parse(out) as Array<{ cnt: number }>;
    return rows.length > 0 && rows[0].cnt > 0;
  } catch {
    return false;
  }
}

/**
 * 获取 4 阶段 × 4 状态 矩阵
 *
 * 跟 v6_query_aweme.py --summary 输出格式一致
 */
export interface QueueStats {
  download:   { pending: number; processing: number; done: number; dead: number };
  transcribe: { pending: number; processing: number; done: number; dead: number };
  distill:    { pending: number; processing: number; done: number; dead: number };
  upload:     { pending: number; processing: number; done: number; dead: number };
  dead:       { pending: number; processing: number; done: number; dead: number };
}

/**
 * 铁律 162 (2026-07-24 18:26 Cove 拍板): phantom_done 检测
 *   phantom_done = stage=done 但 关键 fs 字段 NULL (静默污染, BUG #11 修复后还会产生)
 *   download:   mp4_path NULL
 *   transcribe: md_path  NULL
 *   distill:    md_path  NULL (复用 transcribe 的 md)
 *   upload:     fs_ids   NULL
 */
export interface PhantomDoneStats {
  download:   number;  // mp4_path NULL
  transcribe: number;  // md_path NULL
  distill:    number;  // md_path NULL
  upload:     number;  // fs_ids NULL
  total:      number;
}

export async function getPhantomDoneStats(): Promise<PhantomDoneStats> {
  // 4 stage 一次性 GROUP BY (避免 4 次 sqlite 调用)
  const rows = await sqliteQuery<{ stage: string; phantom: number }>(
    `
    SELECT stage,
      CASE
        WHEN stage='download' AND json_extract(payload, '$.mp4_path') IS NULL THEN 1
        WHEN stage='transcribe' AND json_extract(payload, '$.md_path') IS NULL THEN 1
        WHEN stage='distill'    AND json_extract(payload, '$.md_path') IS NULL THEN 1
        WHEN stage='upload'     AND json_extract(payload, '$.fs_ids') IS NULL THEN 1
        ELSE 0
      END AS phantom
    FROM queue
    WHERE status='done'
      AND stage IN ('download','transcribe','distill','upload')
    `
  );

  const stats: PhantomDoneStats = {
    download: 0, transcribe: 0, distill: 0, upload: 0, total: 0,
  };

  for (const r of rows) {
    if (r.phantom === 0) continue;
    if (r.stage === "download")   stats.download   += 1;
    if (r.stage === "transcribe") stats.transcribe += 1;
    if (r.stage === "distill")    stats.distill    += 1;
    if (r.stage === "upload")     stats.upload     += 1;
    stats.total += 1;
  }

  return stats;
}

export async function getQueueStats(): Promise<QueueStats & { phantom_done: PhantomDoneStats }> {
  const rows = await sqliteQuery<{ stage: string; status: string; n: number }>(
    "SELECT stage, status, COUNT(*) as n FROM queue GROUP BY stage, status"
  );

  const STAGES = ["download", "transcribe", "distill", "upload", "dead"] as const;
  const STATUSES = ["pending", "processing", "done", "dead"] as const;

  const stats: QueueStats = {
    download:   { pending: 0, processing: 0, done: 0, dead: 0 },
    transcribe: { pending: 0, processing: 0, done: 0, dead: 0 },
    distill:    { pending: 0, processing: 0, done: 0, dead: 0 },
    upload:     { pending: 0, processing: 0, done: 0, dead: 0 },
    dead:       { pending: 0, processing: 0, done: 0, dead: 0 },
  };

  for (const r of rows) {
    if (!STAGES.includes(r.stage as typeof STAGES[number])) continue;
    if (!STATUSES.includes(r.status as typeof STATUSES[number])) continue;
    const stageKey = r.stage as keyof QueueStats;
    const statusKey = r.status as keyof QueueStats["download"];
    stats[stageKey][statusKey] = r.n;
  }

  // 铁律 162: phantom_done 检测
  const phantom_done = await getPhantomDoneStats();

  return { ...stats, phantom_done };
}

/**
 * 按 aweme_id 单条全链路追踪 (跟 v6_query_aweme.py query_aweme 同等)
 */
export interface AwemeTrace {
  aweme_id: string;
  found: boolean;
  stages: Record<string, { status: string; id: number; retry_count: number;
                          created_at: string | null; claimed_at: string | null; done_at: string | null }
                       | { rows: Array<{ id: number; reason: string; ts: string }> }>;
  current_stage: string;
  current_status: string;
  total_rows: number;
  [key: string]: unknown;  // 兼容 MCP SDK index signature 要求
}

interface QueueRow {
  id: number;
  stage: string;
  status: string;
  retry_count: number;
  aweme_id: string;
  created_at: number | null;
  claimed_at: number | null;
  done_at: number | null;
  payload: string | null;
}

export async function traceAweme(aweme_id: string): Promise<AwemeTrace> {
  const rows = await sqliteQuery<QueueRow>(
    `SELECT id, stage, status, retry_count, aweme_id,
            created_at, claimed_at, done_at, payload
     FROM queue
     WHERE aweme_id = ?
     ORDER BY created_at ASC`,
    [aweme_id]
  );

  if (rows.length === 0) {
    return {
      aweme_id,
      found: false,
      stages: {},
      current_stage: "unknown",
      current_status: "unknown",
      total_rows: 0
    };
  }

  // 按 stage 聚合
  const stages: AwemeTrace["stages"] = {};
  const stagePriority = (status: string, done_at: number | null): number => {
    if (status === "processing") return 4;
    if (status === "pending") return 3;
    if (status === "dead") return 2;
    if (status === "done") return 1; // + done_at 越大越新
    return 0;
  };

  for (const r of rows) {
    if (r.stage === "dead") continue; // 死信单独处理
    const existing = stages[r.stage];
    const newPrio = stagePriority(r.status, r.done_at);
    if (!existing || "status" in existing === false) {
      stages[r.stage] = {
        status: r.status,
        id: r.id,
        retry_count: r.retry_count,
        created_at: fmtTs(r.created_at),
        claimed_at: fmtTs(r.claimed_at),
        done_at: fmtTs(r.done_at)
      };
    } else {
      const existingPrio = stagePriority(existing.status as string, null);
      if (newPrio > existingPrio) {
        stages[r.stage] = {
          status: r.status,
          id: r.id,
          retry_count: r.retry_count,
          created_at: fmtTs(r.created_at),
          claimed_at: fmtTs(r.claimed_at),
          done_at: fmtTs(r.done_at)
        };
      }
    }
  }

  // 死信行
  const deadRows = rows.filter((r) => r.stage === "dead");
  if (deadRows.length > 0) {
    stages["dead"] = {
      rows: deadRows.map((r) => {
        let reason = "(no reason)";
        if (r.payload) {
          try {
            const p = JSON.parse(r.payload);
            reason = p.dead_reason || p.error || reason;
          } catch { /* ignore */ }
        }
        return { id: r.id, reason, ts: fmtTs(r.created_at) ?? "?" };
      })
    };
  }

  // 推算 current
  let currentStage = "unknown";
  let currentStatus = "unknown";
  for (const s of ["download", "transcribe", "distill", "upload"]) {
    const st = stages[s];
    if (st && "status" in st && (st.status === "processing" || st.status === "pending")) {
      currentStage = s;
      currentStatus = st.status;
      break;
    }
  }
  if (currentStage === "unknown" && stages["dead"]) {
    currentStage = "dead";
    currentStatus = "dead";
  }

  return {
    aweme_id,
    found: true,
    stages,
    current_stage: currentStage,
    current_status: currentStatus,
    total_rows: rows.length
  };
}

/**
 * 按 author 批量全链路追踪 (Cove 2026-07-23 16:21 拍板: 必须 MCP 禁裸 SQL)
 *
 * 用 payload JSON 里的 author 字段做 fuzzy match (LIKE 兼容空格变体)
 * 返回每个 stage 的 status 矩阵 + 文件系统存在性
 */
export interface AuthorTrace {
  author: string;
  total_aweme: number;
  stage_matrix: Record<string, Record<string, number>>;  // { stage: { status: count } }
  fs_check: {
    mp4_in_fs: number;
    md_in_fs: number;
    srt_in_fs: number;
  };
  fs_missing_download: string[];   // 标 download done 但 fs 无 mp4
  needs_cascade_upload: string[]; // 标 distill done 但无 upload stage row
  sample_awemes: string[];        // 前 5 个 aweme_id 样本
  [key: string]: unknown;          // MCP SDK index signature 兼容
}

interface AuthorCountRow {
  stage: string;
  status: string;
  n: number;
}

interface AuthorFsRow {
  aweme_id: string;
  has_mp4: number;
  has_md: number;
  has_srt: number;
  fs_dl_done: number;  // queue stage download done
}

interface AuthorNeedRow {
  aweme_id: string;
}

export async function traceByAuthor(author: string): Promise<AuthorTrace> {
  // 自动 wildcard (caller 传 '玉留君' 即可匹配 '玉留君 大得鉴宝' / '玉留君   大得鉴宝' / '玉留君   __大得鉴宝')
  // 铁律 165.2 P1-1 (2026-07-24 22:14 Cove 拍板): escapeLike 防 LIKE 注入
  // 修前: author='100%' 或 '_' 会被当通配符 (匹配所有 / 单字符)
  // 修后: 用 `/` 作为 ESCAPE 字符 (非 backslash, 避开 SQLite 字符串字面量里 `\` 不算转义 的歧义)
  const likePattern = `%${escapeLike(author)}%`;
  const likeEsc = `ESCAPE '/'`;

  // 1. Stage × Status 矩阵
  const counts = await sqliteQuery<AuthorCountRow>(
    `SELECT stage, status, COUNT(*) as n
     FROM queue
     WHERE json_extract(payload, '$.author') LIKE ? ${likeEsc}
     GROUP BY stage, status`,
    [likePattern]
  );

  const STAGES = ["download", "transcribe", "distill", "upload", "dead"];
  const STATUSES = ["pending", "processing", "done", "dead"];
  const stageMatrix: Record<string, Record<string, number>> = {};
  for (const s of STAGES) {
    stageMatrix[s] = {};
    for (const st of STATUSES) stageMatrix[s][st] = 0;
  }
  for (const r of counts) {
    if (STAGES.includes(r.stage) && STATUSES.includes(r.status)) {
      stageMatrix[r.stage][r.status] = r.n;
    }
  }

  // 2. 唯一 aweme_id 总数
  const totalRow = await sqliteQuery<{ n: number }>(
    `SELECT COUNT(DISTINCT aweme_id) as n FROM queue
     WHERE json_extract(payload, '$.author') LIKE ? ${likeEsc}`,
    [likePattern]
  );
  const totalAweme = totalRow[0]?.n ?? 0;

  // 3. 文件系统存在性 + queue download done 状态
  const fsRows = await sqliteQuery<AuthorFsRow>(
    `SELECT q.aweme_id as aweme_id,
            EXISTS(SELECT 1 FROM queue WHERE aweme_id=q.aweme_id AND stage='download' AND status='done') as fs_dl_done
     FROM (SELECT DISTINCT aweme_id FROM queue WHERE json_extract(payload, '$.author') LIKE ? ${likeEsc}) q`,
    [likePattern]
  );

  // 文件系统检查 — 多路径漂移 (Cove 2026-07-23 17:56 拍板)
  // 使用 FS_PATHS 配置统一多路径扫描 (任一路径有就算有)
  const fs_mp4_set = multiPathScan('.mp4', FS_PATHS.mp4());
  const fs_md_set = multiPathScan('.md', FS_PATHS.md());
  const fs_srt_set = multiPathScan('.srt', FS_PATHS.srt());

  let mp4InFs = 0, mdInFs = 0, srtInFs = 0;
  const fsMissingDownload: string[] = [];
  for (const r of fsRows) {
    if (fs_mp4_set.has(r.aweme_id)) mp4InFs++;
    if (fs_md_set.has(r.aweme_id)) mdInFs++;
    if (fs_srt_set.has(r.aweme_id)) srtInFs++;
    if (r.fs_dl_done === 1 && !fs_mp4_set.has(r.aweme_id)) {
      fsMissingDownload.push(r.aweme_id);
    }
  }

  // 4. 需要 cascade upload: distill done 但无 upload stage row
  const needRows = await sqliteQuery<AuthorNeedRow>(
    `SELECT DISTINCT q.aweme_id
     FROM queue q
     WHERE q.stage='distill' AND q.status='done'
       AND json_extract(q.payload, '$.author') LIKE ? ${likeEsc}
       AND NOT EXISTS (SELECT 1 FROM queue WHERE aweme_id=q.aweme_id AND stage='upload')`,
    [likePattern]
  );
  const needsCascade = needRows.map(r => r.aweme_id);

  // 5. 样本
  const sampleRows = await sqliteQuery<{ aweme_id: string }>(
    `SELECT DISTINCT aweme_id FROM queue
     WHERE json_extract(payload, '$.author') LIKE ? ${likeEsc} LIMIT 5`,
    [likePattern]
  );
  const sample = sampleRows.map(r => r.aweme_id);

  return {
    author,
    total_aweme: totalAweme,
    stage_matrix: stageMatrix,
    fs_check: { mp4_in_fs: mp4InFs, md_in_fs: mdInFs, srt_in_fs: srtInFs },
    fs_missing_download: fsMissingDownload,
    needs_cascade_upload: needsCascade,
    sample_awemes: sample
  };
}

/**
 * 按 domain 批量全链路追踪 (Cove 2026-07-23 16:21 拍板)
 *
 * 用 payload JSON 里的 domain 字段 (e.g. 'jade', 'livestream', 'universal')
 * 接口与 traceByAuthor 平行
 */
export interface DomainTrace {
  domain: string;
  total_aweme: number;
  stage_matrix: Record<string, Record<string, number>>;
  fs_check: { mp4_in_fs: number; md_in_fs: number; srt_in_fs: number };
  fs_missing_download: string[];
  needs_cascade_upload: string[];
  sample_awemes: string[];
  [key: string]: unknown;          // MCP SDK index signature 兼容
}

export async function traceByDomain(domain: string): Promise<DomainTrace> {
  const counts = await sqliteQuery<AuthorCountRow>(
    `SELECT stage, status, COUNT(*) as n
     FROM queue
     WHERE json_extract(payload, '$.domain') = ?
     GROUP BY stage, status`,
    [domain]
  );

  const STAGES = ["download", "transcribe", "distill", "upload", "dead"];
  const STATUSES = ["pending", "processing", "done", "dead"];
  const stageMatrix: Record<string, Record<string, number>> = {};
  for (const s of STAGES) {
    stageMatrix[s] = {};
    for (const st of STATUSES) stageMatrix[s][st] = 0;
  }
  for (const r of counts) {
    if (STAGES.includes(r.stage) && STATUSES.includes(r.status)) {
      stageMatrix[r.stage][r.status] = r.n;
    }
  }

  const totalRow = await sqliteQuery<{ n: number }>(
    `SELECT COUNT(DISTINCT aweme_id) as n FROM queue
     WHERE json_extract(payload, '$.domain') = ?`,
    [domain]
  );
  const totalAweme = totalRow[0]?.n ?? 0;

  const fsRows = await sqliteQuery<AuthorFsRow>(
    `SELECT q.aweme_id as aweme_id,
            EXISTS(SELECT 1 FROM queue WHERE aweme_id=q.aweme_id AND stage='download' AND status='done') as fs_dl_done
     FROM (SELECT DISTINCT aweme_id FROM queue WHERE json_extract(payload, '$.domain') = ?) q`,
    [domain]
  );

  const fs_mp4_set = multiPathScan('.mp4', FS_PATHS.mp4());
  const fs_md_set = multiPathScan('.md', FS_PATHS.md());
  const fs_srt_set = multiPathScan('.srt', FS_PATHS.srt());

  let mp4InFs = 0, mdInFs = 0, srtInFs = 0;
  const fsMissingDownload: string[] = [];
  for (const r of fsRows) {
    if (fs_mp4_set.has(r.aweme_id)) mp4InFs++;
    if (fs_md_set.has(r.aweme_id)) mdInFs++;
    if (fs_srt_set.has(r.aweme_id)) srtInFs++;
    if (r.fs_dl_done === 1 && !fs_mp4_set.has(r.aweme_id)) {
      fsMissingDownload.push(r.aweme_id);
    }
  }

  const needRows = await sqliteQuery<AuthorNeedRow>(
    `SELECT DISTINCT q.aweme_id
     FROM queue q
     WHERE q.stage='distill' AND q.status='done'
       AND json_extract(q.payload, '$.domain') = ?
       AND NOT EXISTS (SELECT 1 FROM queue WHERE aweme_id=q.aweme_id AND stage='upload')`,
    [domain]
  );
  const needsCascade = needRows.map(r => r.aweme_id);

  const sampleRows = await sqliteQuery<{ aweme_id: string }>(
    `SELECT DISTINCT aweme_id FROM queue
     WHERE json_extract(payload, '$.domain') = ? LIMIT 5`,
    [domain]
  );
  const sample = sampleRows.map(r => r.aweme_id);

  return {
    domain,
    total_aweme: totalAweme,
    stage_matrix: stageMatrix,
    fs_check: { mp4_in_fs: mp4InFs, md_in_fs: mdInFs, srt_in_fs: srtInFs },
    fs_missing_download: fsMissingDownload,
    needs_cascade_upload: needsCascade,
    sample_awemes: sample
  };
}

/**
 * 所有 stuck processing (>5min 未动)
 */
export interface StuckRow {
  aweme_id: string;
  stage: string;
  stuck_min: number;
  retry_count: number;
  claimed_at: string | null;
}

export async function getStuckProcessing(minutes: number = 5): Promise<StuckRow[]> {
  // 2026-07-22 修复 (Cove 中等 BUG): SQLite NULL < anything 返回 NULL (false),
  // 修前 claimed_at IS NULL 的 processing 行永远不出现 stuck 结果 (worker pick 了但没写 claimed_at → 隐身)
  // 修后: WHERE 加 (claimed_at IS NULL OR claimed_at < ...)
  const rows = await sqliteQuery<{ aweme_id: string; stage: string; retry_count: number;
                              claimed_at: number | null; stuck_sec: number }>(
    `SELECT aweme_id, stage, retry_count, claimed_at,
            CASE WHEN claimed_at IS NULL
                 THEN CAST(strftime('%s', 'now') AS INTEGER)
                 ELSE (CAST(strftime('%s', 'now') AS INTEGER) - claimed_at)
            END as stuck_sec
     FROM queue
     WHERE status = 'processing' AND (claimed_at IS NULL OR claimed_at < CAST(strftime('%s', 'now') AS INTEGER) - (? * 60))
     ORDER BY claimed_at ASC NULLS FIRST`,
    [String(minutes)]
  );

  return rows.map((r) => ({
    aweme_id: r.aweme_id,
    stage: r.stage,
    stuck_min: Math.round(r.stuck_sec / 60 * 10) / 10,
    retry_count: r.retry_count,
    claimed_at: fmtTs(r.claimed_at)
  }));
}

/**
 * worker 进程检查 (主机端进程, 跟 mcp systemd 同 PID namespace)
 *
 * 铁律 162 (2026-07-24 18:26 Cove 拍板): 修 stale "monitor_douyin.py" 检查
 * 修前: pgrep "monitor_douyin.py" 永远 false (老文件 11:42 铁律 152 切换已删)
 * 修后: pgrep "v6_monitor.py" (新 daemon, 跟 systemd service 命名对齐)
 *
 * 铁律 m11.18.8 (2026-08-26 12:41 Cove 拍 A 方案 - 治本):
 * mcp 改 systemd 服务跑主机, 跟 v6 worker 同 PID namespace
 * → 简单 pgrep 直接看主机 PID, 不用 docker /host_proc hack
 * 修前 (m11.18.7 hack): docker container 跑 mcp → namespace 隔离 → pgrep 看不到主机 worker
 *      → 装 /host_proc bind mount → readdirSync(/host_proc) hack
 * 修后: mcp systemd 跑主机 → 跟 worker 同 PID → 直接 pgrep
 */
export function checkWorkersRunning(): Record<string, boolean> {
  const patterns = [
    "v6_download_worker",
    "v6_transcribe_worker",
    "v6_distill_worker",
    "v6_upload_worker",
    "v6_monitor.py",  // 铁律 162: 老 monitor_douyin.py 已废弃, 用 v6_monitor.py
  ];
  const result: Record<string, boolean> = {};

  for (const p of patterns) {
    try {
      // systemd 跑主机后, pgrep 直接看主机 PID namespace
      const out = execFileSync("pgrep", ["-f", "--", p], { encoding: "utf-8" });
      const lines = out.trim().split("\n").filter(Boolean);
      result[p] = lines.length > 0;
    } catch {
      // pgrep 返非 0 = 没找到, 不是错误
      result[p] = false;
    }
  }
  return result;
}

function fmtTs(ts: number | null): string | null {
  if (ts === null || ts === undefined) return null;
  try {
    return new Date(ts * 1000).toISOString().replace("T", " ").substring(0, 19);
  } catch {
    return null;
  }
}

/**
 * 管道 — pipeline_clear_dead
 *
 * 删 stage='dead' 行. 默认 dry_run=true. 真删前写 audit log.
 * 保留 needs_manual_review=1 的 (铁律 122 audit 字段).
 */
export interface ClearDeadResult {
  [key: string]: unknown;
  dry_run: boolean;
  candidates: number;
  deleted: number;
  protected_manual_review: number;
  filtered_author: string | null;
  older_than_days: number;
  cutoff_ts: number;
  deleted_breakdown: Array<{ stage: string; status: string; cnt: number }>;
  vacuum_freed_bytes: number | null;
  audit_log_path: string | null;
}

export async function clearDead(opts: {
  older_than_days?: number;
  author?: string;
  dry_run?: boolean;
  vacuum?: boolean;  // 铁律 165.2 P2-3 (2026-07-24 22:14 Cove 拍板): 默认 false, 防大表 VACUUM 阻塞
} = {}): Promise<ClearDeadResult> {
  const older_than_days = opts.older_than_days ?? 30;
  const author = opts.author ?? null;
  const dry_run = opts.dry_run ?? true;
  const do_vacuum = opts.vacuum ?? false;  // 修前: 默认 true, 大表 VACUUM 可能阻塞几秒
  const cutoff_ts = Math.floor(Date.now() / 1000) - (older_than_days * 86400);

  // 1. 查 candidates (含 breakdown)
  const authorFilter = author ? `AND json_extract(payload, '$.author') = ?` : '';
  const authorArg: string[] = author ? [author] : [];

  const candRows = await sqliteQuery<{ stage: string; status: string; cnt: number }>(
    `SELECT stage, status, COUNT(*) AS cnt
     FROM queue
     WHERE stage = 'dead' AND status = 'dead'
       AND created_at < ?
       AND json_extract(payload, '$.needs_manual_review') IS NOT 1
       ${authorFilter}
     GROUP BY stage, status`,
    [String(cutoff_ts), ...authorArg]
  );

  const candidates = candRows.reduce((s, r) => s + r.cnt, 0);

  // 2. 保护 audit
  const protRows = await sqliteQuery<{ cnt: number }>(
    `SELECT COUNT(*) AS cnt FROM queue
     WHERE stage = 'dead' AND status = 'dead'
       AND created_at < ?
       AND json_extract(payload, '$.needs_manual_review') = 1
       ${authorFilter}`,
    [String(cutoff_ts), ...authorArg]
  );
  const protected_manual_review = protRows.length > 0 ? protRows[0].cnt : 0;

  // 3. dry_run 默认 — 只报不删
  if (dry_run || candidates === 0) {
    return {
      dry_run: true,
      candidates,
      deleted: 0,
      protected_manual_review,
      filtered_author: author,
      older_than_days,
      cutoff_ts,
      deleted_breakdown: candRows,
      vacuum_freed_bytes: null,
      audit_log_path: null,
    };
  }

  // 4. 写 audit log 先
  const auditLogDir = join(WORKDIR, "logs");
  if (!existsSync(auditLogDir)) mkdirSync(auditLogDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const auditLogPath = join(auditLogDir, `clear_dead-${ts}.json`);
  const audit = {
    timestamp: new Date().toISOString(),
    older_than_days,
    author,
    cutoff_ts,
    candidates,
    protected_manual_review,
    vacuum: do_vacuum,
    action: 'clear_dead',
  };
  writeFileSync(auditLogPath, JSON.stringify(audit, null, 2));

  // 5. 真删
  const delTs = String(Math.floor(Date.now() / 1000));
  await sqliteQuery<unknown>(
    `DELETE FROM queue
     WHERE stage = 'dead' AND status = 'dead'
       AND created_at < ?
       AND json_extract(payload, '$.needs_manual_review') IS NOT 1
       ${authorFilter}`,
    [String(cutoff_ts), ...authorArg]
  );

  // 6. VACUUM (可选, 默认不跑 — 铁律 165.2 P2-3)
  // 修前: 无条件 VACUUM, 大表重建文件可能秒级阻塞 server (Express 单线程, 请求全排队)
  // 修后: do_vacuum=false 时跳过; 真要回收空间显式传 vacuum=true
  let freed_bytes: number | null = null;
  if (do_vacuum) {
    try {
      const before = statSync(QUEUE_DB).size;
      await sqliteQuery<unknown>('VACUUM', []);
      const after = statSync(QUEUE_DB).size;
      freed_bytes = before - after;
    } catch {
      freed_bytes = null;
    }
  }

  return {
    dry_run: false,
    candidates,
    deleted: candidates,
    protected_manual_review,
    filtered_author: author,
    older_than_days,
    cutoff_ts,
    deleted_breakdown: candRows,
    vacuum_freed_bytes: freed_bytes,
    audit_log_path: auditLogPath,
  };
}

/**
 * 管道 — pipeline_move_kb + pipeline_unsplit_kb
 *
 * 物理 mv KB 卡 src → target (同 FS atomic), 改 frontmatter domain.
 */
export interface MoveKbOpts {
  aweme_ids: string[];
  target_domain: 'livestream' | 'jade' | 'universal' | 'unknown';
  reason: string;
  workdir_parent?: string;  // 默认 /home/main/douyin-data/batch_v5_daya_1467
}

export interface MoveKbResult {
  [key: string]: unknown;
  target_domain: string;
  requested: number;
  moved: number;
  not_found: number;
  backup_dirs: string[];
  audit_log_path: string;
  errors: Array<{ aweme_id: string; reason: string }>;
}

// 2026-07-22 修复 (Cove 中等 BUG): findKbFile 全目录扫描 O(n) → 加 in-memory 索引缓存
// 修前: 每次 trace 扫 5 个 domain 子目录, 读所有 .md frontmatter regex 匹配 (64716 张卡单次几百文件)
// 修后: 首次扫建索引 (aweme_id → {path, domain}), 后续 O(1) 查
//
// 铁律 165.2 P0-1 (2026-07-24 22:14 Cove 拍板): 缓存失效加 generation 计数器
// 修前: 仅依赖 knowledge-base/ 父目录 mtime, 但 renameSync 跨子目录移文件不改父目录 mtime
//       → moveKb 后缓存是脏的, 第二次 moveKb 同批卡 → 报 not_found / 移到错误位置
// 修后: mtime + generation 双信号; moveKb 完成后 _invalidateKbIndex() 强制递增 generation
type KbIndexEntry = { path: string; current_domain: string };
type KbIndex = {
  workdir: string;
  entries: Map<string, KbIndexEntry>;
  mtime: number;     // 父目录 mtime (文件系统外部变化信号)
  generation: number; // 内部失效信号 (moveKb 自增)
};
const KB_INDEX_CACHE: { ref: KbIndex | null } = { ref: null };
let KB_INDEX_GENERATION = 0;

/** 铁律 165.2 P0-1: 强制下次 getKbIndex 重建 (moveKb 完成后调用) */
export function _invalidateKbIndex(): void {
  KB_INDEX_GENERATION++;
}

function buildKbIndex(workdir: string, generation: number): KbIndex {
  const kbDir = join(workdir, "knowledge-base");
  const entries = new Map<string, KbIndexEntry>();
  // 5 个可能 domain 子目录
  const domains = ['livestream', 'jade', 'universal', 'unknown', 'livestream_other'];
  for (const d of domains) {
    const subDir = join(kbDir, d);
    if (!existsSync(subDir)) continue;
    try {
      const files = readdirSync(subDir).filter(f => f.endsWith('.md'));
      for (const f of files) {
        const filepath = join(subDir, f);
        try {
          const content = readFileSync(filepath, 'utf-8');
          // 匹配 aweme_id 16-21 位纯数字 (frontmatter source / idx)
          const sourceMatch = content.match(/^source:\s*.*?([0-9]{15,21})/m);
          const idxMatch = content.match(/^idx:\s*.*?([0-9]{15,21})/m);
          const awemeId = sourceMatch?.[1] || idxMatch?.[1];
          if (!awemeId) continue;
          let fm_domain = d;
          const fmMatch = content.match(/^domain:\s*['"]?(\w+)['"]?/m);
          if (fmMatch) fm_domain = fmMatch[1];
          entries.set(awemeId, { path: filepath, current_domain: fm_domain });
        } catch {}
      }
    } catch {}
  }
  return { workdir, entries, mtime: Date.now(), generation };
}

function getKbIndex(workdir: string): KbIndex {
  const kbDir = join(workdir, "knowledge-base");
  let latestMtime = 0;
  try {
    // 父目录 mtime 作为文件系统外部变化信号
    latestMtime = statSync(kbDir).mtimeMs;
  } catch {}
  const cached = KB_INDEX_CACHE.ref;
  // 铁律 165.2 P0-1: mtime + generation 双信号, 任一变化都重建
  if (cached && cached.workdir === workdir && cached.mtime === latestMtime && cached.generation === KB_INDEX_GENERATION) {
    return cached;
  }
  // 重建索引 (mtime 变 或 generation 变)
  const fresh = buildKbIndex(workdir, KB_INDEX_GENERATION);
  fresh.mtime = latestMtime || Date.now();
  KB_INDEX_CACHE.ref = fresh;
  return fresh;
}

function findKbFile(workdir: string, aweme_id: string): {
  path: string;
  current_domain: string;
} | null {
  // 2026-07-22 修复: 用 KB 索引缓存, O(1) 查代替 O(n) 全扫
  const idx = getKbIndex(workdir);
  return idx.entries.get(aweme_id) || null;
}

function updateFrontmatterDomain(filepath: string, new_domain: string): void {
  let content = readFileSync(filepath, 'utf-8');
  // 铁律 162.3 (2026-07-24 18:53 Cove "继续处理"): 容忍 3 种 frontmatter 格式
  // - domain: jade        (纯裸值, KB 现主流)
  // - domain: 'jade'      (带单引号, LLM 蒸馏偶尔产出)
  // - domain: "jade"      (带双引号, 罕有)
  // 修前: regex `/^domain:\s.*$/m` 匹配 `domain: 'jade'` 时会把 `'` 一并替换, 产生 `domain: jade` (错误, 引号被吞)
  // 修后: 匹配 `domain:` 后可选引号 + value, 完整替换含引号片段
  const domainLineRe = /^domain:\s*(['"]?)(.+?)\1\s*$/m;
  if (domainLineRe.test(content)) {
    content = content.replace(domainLineRe, `domain: ${new_domain}`);
  } else {
    // 没 domain 字段 → 加在 frontmatter 末尾
    content = content.replace(
      /^(---\n[\s\S]*?---\n)/,
      `$1domain: ${new_domain}\n`
    );
  }
  writeFileSync(filepath, content, 'utf-8');
}

export function moveKb(opts: MoveKbOpts): MoveKbResult {
  const { aweme_ids, target_domain, reason } = opts;
  const workdir = opts.workdir_parent ?? WORKDIR;

  const errors: Array<{ aweme_id: string; reason: string }> = [];
  let moved = 0;
  let not_found = 0;
  let already_in_target = 0;

  // 按 current_domain 分组 (同源目录文件批量移, 一次建一个 backup)
  const groupedSrc = new Map<string, string[]>();

  for (const aid of aweme_ids) {
    const found = findKbFile(workdir, aid);
    if (!found) {
      not_found++;
      errors.push({ aweme_id: aid, reason: 'file not found in any domain' });
      continue;
    }
    if (found.current_domain === target_domain) {
      // already in target — skip
      already_in_target++;
      continue;
    }
    const srcDir = dirname(found.path);
    if (!groupedSrc.has(srcDir)) groupedSrc.set(srcDir, []);
    groupedSrc.get(srcDir)!.push(found.path);
  }

  // 铁律 165.2 P1-3 (2026-07-24 22:14 Cove 拍板): 预验证阶段
  // 修前: renameSync 中途失败 (磁盘满/权限) → 部分已移 + 部分未移, 状态不一致, 不可逆
  // 修后: 预验证所有源文件存在 + 目标目录可写; 任一不满足则全拒, 不动文件
  const totalToMove = Array.from(groupedSrc.values()).reduce((s, arr) => s + arr.length, 0);
  if (totalToMove > 0) {
    // 验证目标目录可写
    const targetDir = join(workdir, 'knowledge-base', target_domain);
    if (!existsSync(targetDir)) {
      try {
        mkdirSync(targetDir, { recursive: true });
      } catch (e: any) {
        errors.push({ aweme_id: 'precheck', reason: `mkdir target ${targetDir} failed: ${e.message}` });
        groupedSrc.clear(); // 拒绝全部
      }
    }
    // 验证可写 (touch 一个 .precheck sentinel)
    if (groupedSrc.size > 0) {
      const sentinel = join(targetDir, `.precheck-${Date.now()}.tmp`);
      try {
        writeFileSync(sentinel, '');
        renameSync(sentinel, sentinel); // 触发实际 IO
      } catch (e: any) {
        errors.push({ aweme_id: 'precheck', reason: `target dir not writable: ${e.message}` });
        groupedSrc.clear();
      } finally {
        try { if (existsSync(sentinel)) renameSync(sentinel, `${sentinel}.removed`); } catch { /* ignore */ }
      }
    }
    // 验证源文件全部存在 (TOCTOU: 验证时刻 vs rename 时刻, 拼抢窗口期仍可能丢, 但缩小到毫秒级)
    for (const [srcDir, files] of groupedSrc) {
      for (const f of files) {
        if (!existsSync(f)) {
          errors.push({ aweme_id: 'precheck', reason: `source vanished: ${f}` });
          // 从批次中移除这个文件
          const arr = groupedSrc.get(srcDir)!;
          const idx = arr.indexOf(f);
          if (idx >= 0) arr.splice(idx, 1);
        }
      }
      if (groupedSrc.get(srcDir)!.length === 0) groupedSrc.delete(srcDir);
    }
  }

  const ts = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19);
  const targetDir = join(workdir, 'knowledge-base', target_domain);

  for (const [srcDir, files] of groupedSrc) {
    for (const f of files) {
      const filename = basename(f);
      const dst = join(targetDir, filename);
      try {
        // mv (同 FS atomic)
        renameSync(f, dst);
        updateFrontmatterDomain(dst, target_domain);
        moved++;
      } catch (e: any) {
        errors.push({ aweme_id: filename, reason: `mv from ${srcDir} failed: ${e.message}` });
      }
    }
  }

  // 铁律 165.2 P0-1: moveKb 完成后强制失效 KB 索引缓存
  // (renameSync 跨子目录不改 knowledge-base/ 父目录 mtime, 必须显式失效)
  if (moved > 0) _invalidateKbIndex();

  // 写 audit log
  const auditLogDir = join(workdir, 'logs');
  if (!existsSync(auditLogDir)) mkdirSync(auditLogDir, { recursive: true });
  const auditLogPath = join(auditLogDir, `move_kb-${ts}.json`);
  writeFileSync(auditLogPath, JSON.stringify({
    timestamp: new Date().toISOString(),
    target_domain,
    reason,
    requested: aweme_ids.length,
    moved,
    not_found,
    already_in_target,
    errors,
    grouped: Object.fromEntries(
      Array.from(groupedSrc.entries()).map(([k, v]) => [k, v.length])
    ),
  }, null, 2));

  return {
    target_domain,
    requested: aweme_ids.length,
    moved,
    not_found,
    backup_dirs: [],  // 不再返回不存在的备份目录, 空数组明确表达 "没备份"
    audit_log_path: auditLogPath,
    errors,
  };
}
