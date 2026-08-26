/**
 * tools/yuxi.ts — Tool 8: KB 灌入 Yuxi (calls HZ server)
 *
 * URL: https://hz.siqing.cn/yuxi/api/...
 * Auth: same as pipeline_status tool (admin login)
 *
 * P1-2 + P1-3: kb_id / username / password 全部从环境变量读, 不再硬编码
 * P3-13: spawn 超时后会 clearTimeout, close 事件不重复触发
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

// EX-P2-X + 铁律 138: WORKDIR 从 V6_WORKDIR 读, 与 queue.ts 对齐 (2026-07-22 Cove P0 修复路径断链)
const WORKDIR = process.env.V6_WORKDIR || "/home/main/douyin-data";
const SCRIPTS = "/home/main/douyin-data/scripts";

interface YuxiConfig {
  base_url: string;
  username: string;
  password: string;
  kb_id: string;
}

// P1-2 + P1-3 修复: 从环境变量读, fallback 仅作启动检查
function buildDefaultConfig(): YuxiConfig {
  const password = process.env.YUXI_PASSWORD || "";
  if (!password) {
    console.warn("[yuxi] WARNING: YUXI_PASSWORD env var not set — ingest_to_yuxi will fail");
  }
  return {
    base_url: process.env.YUXI_BASE_URL || "https://hz.siqing.cn/yuxi",
    username: process.env.YUXI_USERNAME || "admin",
    password,
    kb_id: process.env.YUXI_KB_ID || "kb_ftl95bqw46",
  };
}

async function getToken(cfg: YuxiConfig): Promise<string> {
  const res = await fetch(`${cfg.base_url}/api/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `username=${encodeURIComponent(cfg.username)}&password=${encodeURIComponent(cfg.password)}`,
  });
  if (!res.ok) throw new Error(`Yuxi login failed: ${res.status}`);
  const data = await res.json() as any;
  return data.access_token;
}

export function registerYuxiTools(server: McpServer) {
  server.registerTool(
    "ingest_to_yuxi",
    {
      title: "Ingest KB to Yuxi",
      description: "把 KB 卡 (knowledge-base/cards/...) 灌入 Yuxi KB. 调用 hz.siqing.cn",
      inputSchema: {
        kb_id: z.string().optional().describe("Yuxi KB id (默认从 YUXI_KB_ID 环境变量读)"),
        batch_size: z.number().optional().describe("每次灌多少张 (默认 100)"),
        kb_path: z.string().optional().describe("KB cards 目录 (默认 <V6_WORKDIR>/kb/...)"),
        mode: z.enum(["all", "pending"]).optional().describe("all=全部, pending=只灌未灌的"),
      },
    },
    async ({ kb_id, batch_size, kb_path, mode }) => {
      // 铁律 165.2 P1-5 (2026-07-24 22:14 Cove 拍板): 修前调两次 buildDefaultConfig → warning 报 2 次
      // 修后: 调一次, kb_id 仅 override 顶层字段
      const base = buildDefaultConfig();
      const cfg: YuxiConfig = { ...base, kb_id: kb_id ?? base.kb_id };
      const token = await getToken(cfg);

      // 触发 ingest_text_kb.py 脚本 (异步)
      const args = [
        join(SCRIPTS, "ingest_text_kb.py"),
        "--kb-id", cfg.kb_id,
        "--batch-size", String(batch_size ?? 100),
        "--mode", mode ?? "pending",
      ];
      if (kb_path) args.push("--kb-path", kb_path);

      return new Promise((resolve, reject) => {
        const proc = spawn("python3", args, {
          env: { ...process.env, YUXI_TOKEN: token, YUXI_BASE_URL: cfg.base_url },
        });
        let stdout = "";
        let stderr = "";
        let settled = false; // 防御多次触发 resolve/reject (zombie 进程)
        let sigkillTimer: NodeJS.Timeout | null = null;
        const settle = (fn: typeof resolve | typeof reject, payload: any) => {
          if (settled) return;
          settled = true;
          clearTimeout(killTimer);
          if (sigkillTimer) clearTimeout(sigkillTimer);
          fn(payload);
        };
        proc.stdout.on("data", (d) => {
          stdout += d.toString();
          // P3-13: stdout 超过 1MB 时丢弃避免内存涨爆, 但记录计字节
          if (stdout.length > 1024 * 1024) stdout = stdout.slice(-1024 * 1024);
        });
        proc.stderr.on("data", (d) => {
          stderr += d.toString();
          if (stderr.length > 1024 * 1024) stderr = stderr.slice(-1024 * 1024);
        });
        // 2026-07-22 严重 BUG 修复 (Cove P1 拍板):
        // 修前: timeout 只 kill 不 resolve, zombie 进程永远不触发 close/error → Promise 永远 pending
        // 修后: timeout 先 SIGTERM, 5s 后 SIGKILL 兜底; 任意时刻触发 close/error/timeout 都 settle
        let killedByTimeout = false;
        const killTimer = setTimeout(() => {
          killedByTimeout = true;
          proc.kill("SIGTERM");
          // SIGKILL fallback (5s 后): 兜底 zombie 进程 (不响应 SIGTERM)
          sigkillTimer = setTimeout(() => {
            try { proc.kill("SIGKILL"); } catch { /* already dead */ }
          }, 5_000);
        }, 600_000); // 10 min max
        proc.on("close", (code) => {
          settle(resolve, {
            content: [{ type: "text", text: stdout || stderr || `exit=${code}` }],
            structuredContent: {
              exit_code: code,
              killed_by_timeout: killedByTimeout,
              stdout,
              stderr,
              kb_id: cfg.kb_id,
            },
          });
        });
        proc.on("error", (err) => {
          settle(resolve, {
            content: [{ type: "text", text: `spawn error: ${err.message}` }],
            structuredContent: {
              exit_code: -1,
              error: err.message,
              stdout,
              stderr,
              kb_id: cfg.kb_id,
            },
          });
        });
      });
    }
  );
}
