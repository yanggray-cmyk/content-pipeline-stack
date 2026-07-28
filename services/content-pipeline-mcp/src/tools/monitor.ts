/**
 * tools/monitor.ts — 3 tools for monitor operations
 *
 * 铁律 152 (Cove 11:38 拍板, 2026-07-24): fetch_strategy 区分 full/incremental
 * - 新加 account_set_fetch_strategy tool
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMonitor, readMonitorState, readAccounts, readMonitorLog, setAccountFetchStrategy } from "../wrapper/monitor.js";

export function registerMonitorTools(server: McpServer) {
  // Tool 1: monitor_check_now
  server.registerTool(
    "monitor_check_now",
    {
      title: "Monitor Check Now",
      description: "立即跑一次监控 (wraps v6_monitor.py --once)。可选只查某个账号。返回新作品列表。",
      inputSchema: {
        alias: z.string().optional().describe("只查某个 alias (如 'danran_jade_c')，不传查全部"),
        json: z.boolean().optional().describe("是否输出 JSON 格式"),
      },
    },
    async ({ alias, json }) => {
      const args = ["--once"];
      if (alias) args.push("--alias", alias);
      if (json) args.push("--json");
      const result = await runMonitor(args);
      return {
        content: [{ type: "text", text: result.stdout || result.stderr }],
        structuredContent: result,
      };
    }
  );

  // Tool 2: monitor_status
  server.registerTool(
    "monitor_status",
    {
      title: "Monitor Status",
      description: "监控状态：last_seen.json + accounts.json + 最近日志 (50 行)",
      inputSchema: {
        log_tail: z.number().optional().describe("日志尾部行数（默认 50）"),
      },
    },
    async ({ log_tail }) => {
      const state = readMonitorState();
      const accounts = readAccounts();
      const log = readMonitorLog(log_tail ?? 50);
      const out = { state, accounts, log_tail_lines: log.split("\n").length, log };
      return {
        content: [{ type: "text", text: JSON.stringify(out, null, 2) }],
        structuredContent: out,
      };
    }
  );

  // Tool 3: account_set_fetch_strategy (铁律 152)
  server.registerTool(
    "account_set_fetch_strategy",
    {
      title: "Account Set Fetch Strategy (铁律 152)",
      description: "设置某个账号 fetch_strategy (full/incremental)。full: 下次 monitor 拉全量历史, 翻完自动翻 incremental; incremental: 只拉最近 200。原子写 accounts.json。",
      inputSchema: {
        alias: z.string().describe("账号 alias (如 'danran_jade_c')"),
        strategy: z.enum(["full", "incremental"]).describe("full: 拉全量历史 (首次拉取) / incremental: 增量拉新 (默认)"),
        count: z.number().optional().describe("full 用 initial_fetch_count, incremental 用 incremental_fetch_count. 默认 5000/200"),
      },
    },
    async ({ alias, strategy, count }) => {
      const result = setAccountFetchStrategy(alias, strategy, count);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        structuredContent: result,
      };
    }
  );
}
