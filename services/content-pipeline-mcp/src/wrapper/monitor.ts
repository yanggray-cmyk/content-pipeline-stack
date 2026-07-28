/**
 * wrapper/monitor.ts — wraps v6_monitor.py + monitor_state.db
 *
 * Integration model (Option A):
 * - v6-monitor.service runs v6_monitor.py --daemon --interval 21600 as a standalone systemd service
 * - monitor_check_now sends SIGUSR1 to the daemon (triggers immediate check)
 * - No subprocess spawning — daemon handles all scheduling
 */
import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

// 2026-07-22 04:27 (Cove 拍板): 老 hk-douyin-monitor.service → v6-monitor.service
// 2026-07-24 11:42 (Cove 拍板): v6_monitor.py 加 fetch_strategy full/incremental (铁律 152)
const MONITOR_SERVICE = "v6-monitor.service";
const V6_PIPELINE_DIR = "/home/main/douyin-data/scripts/v6_pipeline";
const STATE_DB = "/home/main/douyin-data/monitor_state.db";
const ACCOUNTS_FILE = "/home/main/douyin-data/config/accounts.json";
const LOG_FILE = "/home/main/douyin-data/logs/v6-monitor.log";

/**
 * Send SIGUSR1 to v6-monitor.service daemon.
 * The daemon receives SIGUSR1 → wakes from sleep → runs immediate check.
 * Then read the log tail to surface results.
 *
 * 2026-07-22 修复 (Cove 中等 BUG): daemon 没运行时直接 reject, 避免 20s 假等
 * 修前: systemctl kill 失败但代码不检查 exit code, 永远等 20s 读日志
 * 修后: 先 systemctl is-active 检查, 死了立即 reject, 不浪费 20s
 *
 * 2026-07-24 11:42: 加 --alias 支持 (铁律 152), 单账号 mode
 */
export function runMonitor(args: string[] = []): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve, reject) => {
    // 1. 先检查 daemon 是否活着 (is-active)
    const isActive = spawn("systemctl", ["is-active", MONITOR_SERVICE], {
      env: { ...process.env },
    });
    let isActiveOut = "";
    isActive.stdout.on("data", (d) => { isActiveOut += d.toString(); });
    isActive.on("close", (isActiveCode) => {
      // is-active exit 0=active, 3=inactive/failed, 4=not-found
      const state = isActiveOut.trim();
      if (isActiveCode !== 0 || state !== "active") {
        return reject(new Error(`${MONITOR_SERVICE} is not active (state=${state || "unknown"}, code=${isActiveCode}). Start it first: sudo systemctl start ${MONITOR_SERVICE}`));
      }
      // 2. Daemon alive → 发 SIGUSR1 (需要 sudo: signal 跨 user 需 root)
      const sig = spawn("sudo", ["-n", "systemctl", "kill", "-s", "USR1", MONITOR_SERVICE], {
        env: { ...process.env },
      });
      let sigErr = "";
      sig.stderr.on("data", (d) => { sigErr += d.toString(); });
      sig.on("error", reject);
      sig.on("close", (code) => {
        if (code !== 0) {
          return reject(new Error(`systemctl kill SIGUSR1 failed (code=${code}): ${sigErr.trim()}`));
        }
        // Wait for daemon to run the check and write logs (~20s is enough for incremental, ~120s for full fetch)
        const waitMs = args.includes("--once") ? 30_000 : 30_000;  // MCP --once 模式
        setTimeout(() => {
          const log = readMonitorLog(40);
          resolve({ stdout: log, stderr: "", code: code ?? 0 });
        }, waitMs);
      });
    });
    isActive.on("error", reject);
  });
}

export function readMonitorState(): any {
  if (!existsSync(STATE_DB)) return { exists: false };
  try {
    // 用 sqlite3 CLI 读 (避免引入 better-sqlite3)
    const { execSync } = require("child_process");
    const out = execSync(`sqlite3 -separator '|' -header "${STATE_DB}" "SELECT sec_user_id, length(last_seen_aweme_ids) as seen_count, last_run_at, last_pulled_count FROM last_seen" 2>&1 || echo ""`).toString();
    return { exists: true, sqlite_dump: out, db_path: STATE_DB };
  } catch (e: any) {
    return { exists: true, error: e.message };
  }
}

export function readAccounts(): any {
  if (!existsSync(ACCOUNTS_FILE)) return { exists: false };
  try {
    return { exists: true, accounts: JSON.parse(readFileSync(ACCOUNTS_FILE, "utf-8")) };
  } catch (e: any) {
    return { exists: true, error: e.message };
  }
}

export function readMonitorLog(tail = 50): string {
  if (!existsSync(LOG_FILE)) return "";
  const lines = readFileSync(LOG_FILE, "utf-8").split("\n");
  return lines.slice(-tail).join("\n");
}

/**
 * 铁律 152 (Cove 11:38 拍板): 设置账号 fetch_strategy (full/incremental)
 * - full: 下次 monitor 跑会拉全量历史 (翻页 has_more=0), 跑完自动翻 incremental
 * - incremental: 默认模式, max_counts=200 拉最近
 * - 原子写 accounts.json (避免 SIGUSR1 触发时读到半状态)
 */
const ACCOUNTS_FILE_V6 = "/home/main/douyin-data/config/accounts.json";

export function setAccountFetchStrategy(
  alias: string,
  strategy: "full" | "incremental",
  count?: number
): { ok: boolean; alias: string; strategy: string; count?: number; message: string } {
  if (!existsSync(ACCOUNTS_FILE_V6)) {
    return { ok: false, alias, strategy, message: `accounts.json 不存在: ${ACCOUNTS_FILE_V6}` };
  }
  try {
    const cfg = JSON.parse(readFileSync(ACCOUNTS_FILE_V6, "utf-8"));
    const accounts = cfg.accounts || {};
    let target_sid: string | null = null;
    let target_acc: any = null;
    for (const [sid, acc] of Object.entries(accounts)) {
      if ((acc as any).alias === alias) {
        target_sid = sid;
        target_acc = acc;
        break;
      }
    }
    if (!target_sid || !target_acc) {
      return { ok: false, alias, strategy, message: `alias=${alias} 在 accounts.json 中不存在` };
    }
    target_acc.fetch_strategy = strategy;
    if (count !== undefined) {
      if (strategy === "full") {
        target_acc.initial_fetch_count = count;
      } else {
        target_acc.incremental_fetch_count = count;
      }
    }
    cfg._version = "1.5";
    cfg._last_updated = new Date().toISOString();
    // 原子写
    const tmp = ACCOUNTS_FILE_V6 + ".tmp";
    const { writeFileSync, renameSync } = require("fs");
    writeFileSync(tmp, JSON.stringify(cfg, null, 2), "utf-8");
    renameSync(tmp, ACCOUNTS_FILE_V6);
    return {
      ok: true,
      alias,
      strategy,
      count,
      message: `accounts.json 已原子写回, 下次 SIGUSR1 触发 monitor 会读新 strategy`,
    };
  } catch (e: any) {
    return { ok: false, alias, strategy, message: `setAccountFetchStrategy 失败: ${e.message}` };
  }
}
