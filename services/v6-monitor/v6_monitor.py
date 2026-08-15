#!/usr/bin/env python3
"""v6_monitor.py — 抖音账号监控 daemon (SQLite backend, 铁律 143)

铁律 143 (Cove 04:27 拍板):
  - 取代 monitor_douyin.py (JSONL 时代老 daemon)
  - 用 SQLite state (state.db) 替代 last_seen.json
  - 直接读 accounts.json 4 个 enabled 账号, 各跑一次
  - 拉最新视频 → 写到各自 enqueue_target (download_list.json) → v6_enqueue 读
  - SIGUSR1 触发立即重跑

铁律 152 (Cove 11:38 拍板, 2026-07-24): fetch_strategy 区分 full / incremental
  - 新账号首次: fetch_strategy=full, max_counts=initial_fetch_count (默认 5000),
                翻页直到 has_more=0 (拉全量历史)
  - 稳定后:     fetch_strategy=incremental, max_counts=incremental_fetch_count (默认 200),
                只拉新发布(配合 last_seen 去重)
  - 拉完 full 翻 incremental: 一次拉全量后 monitor 自动维护, 不需要手动改
  - accounts.json 必须有 fetch_strategy 字段 (无则默认 incremental)
  - 远程切: MCP tool account_set_fetch_strategy(alias, strategy, count?)

设计要点:
  1. 单进程 (v6_monitor 唯一 daemon), 不要 4 个独立 process (节省资源)
  2. polling 24h (跟 accounts.json check_interval_sec 对齐)
  3. 写入 download_list.json 后, 调 v6_enqueue.main() 自动入队 (原子闭环)
  4. state.db 持久化 last_seen_aweme_ids (避免重复拉)

铁律 47: 真源 = 真领域 — enqueue 时 accounts.json 提供 domain/source_alias
铁律 12: 不要自己编视频名 — 用 Douyin API 返回的真 desc/author
铁律 139: dedup 全 status — v6_enqueue 已修, 这里只负责"拉新"
铁律 152: fetch_strategy 区分新账号首次/已有账号增量

用法:
  python3 v6_monitor.py [--dry-run] [--once] [--skip-enqueue]
  python3 v6_monitor.py --daemon [--interval SECS]  # systemd 模式 (默认 86400)
  SIGUSR1: 立即重跑 (不等 24h)

支持的 args (argparse):
  --dry-run       只拉新, 不写 download_list.json
  --once          跑一次就退出 (非 daemon)
  --skip-enqueue  写 download_list.json 但不入队 (调试用)
  --daemon        systemd 守护模式
  --interval N    daemon 循环间隔秒数 (默认 86400 = 24h, 推荐 21600 = 6h)
  注: --account ALIAS 是 v6_enqueue 的参数, v6_monitor 不支持 (铁律 142 v3 fix)
"""
import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# === 路径配置 ===
WORKDIR = Path(os.environ.get("V6_WORKDIR", "/home/main/douyin-data"))
ACCOUNTS_FILE = Path("/home/main/douyin-data/config/accounts.json")
STATE_DB = WORKDIR / "monitor_state.db"
LOG_FILE = WORKDIR / "logs" / "v6_monitor.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# === SQLite state (替代 last_seen.json) ===
import sqlite3

def _init_state_db() -> None:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(STATE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS last_seen (
            sec_user_id TEXT PRIMARY KEY,
            last_seen_aweme_ids TEXT NOT NULL DEFAULT '[]',
            last_run_at INTEGER NOT NULL DEFAULT 0,
            last_pulled_count INTEGER NOT NULL DEFAULT 0,
            last_seen_with_ts TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.commit()
    conn.close()


def load_last_seen(sec_user_id: str) -> set:
    """读 SQLite state (铁律 143: 替代 last_seen.json)
    铁律 v285.25 P0-X: 配合 dedup_time_window，只返回窗口内的 aweme_ids
    """
    if not STATE_DB.exists():
        _init_state_db()
    conn = sqlite3.connect(str(STATE_DB))
    row = conn.execute(
        "SELECT last_seen_aweme_ids FROM last_seen WHERE sec_user_id=?",
        (sec_user_id,)
    ).fetchone()
    conn.close()
    if row:
        try:
            return set(json.loads(row[0]))
        except Exception:
            return set()
    return set()


# 铁律 v285.25 P0-X: dedup_time_window — last_seen 仅保留 [now - window, now] 窗口内的视频
# 防止 last_seen 跟 last_run_at 跨年累积导致新视频永远被 dedup 假命中
# 背景: v285.22 之前 v6_monitor 用 last_seen_aweme_ids | new_ids 累积，
#       一年下来 last_seen 可达 5000+，last_run_at 过期后无法区分 “已拉过” vs "未拉过"，造成 dedup 假命中。
DEDUP_TIME_WINDOW_SEC = int(os.getenv("DEDUP_TIME_WINDOW_SEC", "7776000"))  # 默认 90 天
# DEDUP_TIME_WINDOW_SEC=0 表示禁用时间窗口（保留原始逻辑，但不被推荐）


def load_last_seen_with_ts(sec_user_id: str) -> list:
    """读 last_seen_with_ts (aweme_id, create_time) 元组列表 — 铁律 v285.25"""
    if not STATE_DB.exists():
        _init_state_db()
    conn = sqlite3.connect(str(STATE_DB))
    row = conn.execute(
        "SELECT last_seen_with_ts FROM last_seen WHERE sec_user_id=?",
        (sec_user_id,)
    ).fetchone()
    conn.close()
    if row:
        try:
            data = json.loads(row[0])
            if isinstance(data, list):
                return data
        except Exception:
            return []
    return []


def save_last_seen_with_ts(sec_user_id: str, entries: list, pulled_count: int) -> None:
    """写 last_seen_with_ts — 铁律 v285.25
    entries = [(aweme_id, create_time), ...]
    """
    if not STATE_DB.exists():
        _init_state_db()
    conn = sqlite3.connect(str(STATE_DB))
    ids = {str(e[0]) for e in entries if e and e[0]}
    conn.execute(
        """
        INSERT INTO last_seen (sec_user_id, last_seen_aweme_ids, last_run_at, last_pulled_count, last_seen_with_ts)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sec_user_id) DO UPDATE SET
            last_seen_aweme_ids=excluded.last_seen_aweme_ids,
            last_run_at=excluded.last_run_at,
            last_pulled_count=excluded.last_pulled_count,
            last_seen_with_ts=excluded.last_seen_with_ts
        """,
        (sec_user_id, json.dumps(sorted(ids)), int(time.time()), pulled_count, json.dumps(entries))
    )
    conn.commit()
    conn.close()


def trim_last_seen_by_window(entries: list) -> list:
    """铁律 v285.25 P0-X: dedup_time_window 修剪
    返回仅包含 create_time >= now - DEDUP_TIME_WINDOW_SEC 的 entries
    """
    if DEDUP_TIME_WINDOW_SEC <= 0:
        return entries
    now = int(time.time())
    cutoff = now - DEDUP_TIME_WINDOW_SEC
    trimmed = []
    for e in entries:
        if not e or len(e) < 2:
            continue
        ct = e[1] if isinstance(e[1], (int, float)) else 0
        if ct >= cutoff:
            trimmed.append(e)
    return trimmed


def save_last_seen(sec_user_id: str, ids: set, pulled_count: int) -> None:
    """写 SQLite state (仅 last_seen_aweme_ids + last_run_at + last_pulled_count)
    铁律 v285.27 (Cove 00:33 飞书反馈): save_last_seen 不应触碰 last_seen_with_ts 列,
    save_last_seen_with_ts 才是 last_seen_with_ts 的唯一真源。旧版本 save_last_seen 用 '[]'
    字面值作为 INSERT 第5参数,导致 ON CONFLICT DO UPDATE SET last_seen_with_ts=excluded.last_seen_with_ts
    会把 save_last_seen_with_ts 刚写入的 7289 bytes 真数据 立即覆盖为空 — dedup_time_window silent failure!
    修: 只 UPDATE last_seen_aweme_ids / last_run_at / last_pulled_count, last_seen_with_ts 列保持不动。
    """
    if not STATE_DB.exists():
        _init_state_db()
    conn = sqlite3.connect(str(STATE_DB))
    conn.execute(
        """
        INSERT INTO last_seen (sec_user_id, last_seen_aweme_ids, last_run_at, last_pulled_count, last_seen_with_ts)
        VALUES (?, ?, ?, ?, '[]')
        ON CONFLICT(sec_user_id) DO UPDATE SET
            last_seen_aweme_ids=excluded.last_seen_aweme_ids,
            last_run_at=excluded.last_run_at,
            last_pulled_count=excluded.last_pulled_count
            -- 铁律 v285.27: last_seen_with_ts 不在这里 UPDATE, 由 save_last_seen_with_ts 唯一负责
        """,
        (sec_user_id, json.dumps(sorted(ids)), int(time.time()), pulled_count)
    )
    conn.commit()
    conn.close()


def load_accounts() -> dict:
    """读 accounts.json (铁律 47 + 136: 真源=真领域 + 多账号)"""
    if not ACCOUNTS_FILE.exists():
        log(f"❌ ACCOUNTS_FILE 不存在: {ACCOUNTS_FILE}")
        return {}
    try:
        return json.loads(ACCOUNTS_FILE.read_text())
    except Exception as e:
        log(f"❌ ACCOUNTS_FILE 解析失败: {e}")
        return {}


async def fetch_user_posts(sec_user_id: str, max_counts: int = 50) -> list:
    """调 douyin_api 拿用户主页视频列表

    复用 monitor_douyin.py 的 douyin_api (brand-video-tools)
    """
    BRAND_VIDEO_ROOT = Path("/home/main/.openclaw/workspace/skills/brand-video-tools")
    sys.path.insert(0, str(BRAND_VIDEO_ROOT / "scripts"))
    try:
        from douyin_api import fetch_user_posts as _fetch_user_posts
        return await _fetch_user_posts(sec_user_id, max_counts=max_counts)
    except Exception as e:
        log(f"  ❌ fetch_user_posts 失败: {e}")
        return []


def detect_new(posts: list, last_seen_ids: set) -> list:
    return [p for p in posts if str(p.get("aweme_id", "")) not in last_seen_ids]


def detect_new_with_window(posts: list, last_seen_entries: list) -> list:
    """铁律 v285.25 P0-X: dedup_time_window 过滤
    只把 [now - DEDUP_TIME_WINDOW_SEC, now] 窗口内的 last_seen 跟 posts 去重
    """
    now = int(time.time())
    cutoff = now - DEDUP_TIME_WINDOW_SEC if DEDUP_TIME_WINDOW_SEC > 0 else 0
    in_window_ids = set()
    for e in last_seen_entries:
        if not e or len(e) < 2:
            continue
        ct = e[1] if isinstance(e[1], (int, float)) else 0
        if ct >= cutoff:
            in_window_ids.add(str(e[0]))
    return [p for p in posts if str(p.get("aweme_id", "")) not in in_window_ids]


def parse_douyin_create_time(ts_value) -> int:
    """铁律 v285.25 P0-X 修正: 抖音 create_time 是 'YYYY-MM-DD HH-MM-SS' 字符串
    转成 unix timestamp (秒)。如果解析失败返 0 (表示不入 dedup 窗口 — 视为老视频)
    """
    if isinstance(ts_value, (int, float)):
        return int(ts_value)
    if not isinstance(ts_value, str) or not ts_value.strip():
        return 0
    try:
        # 抖音格式: 'YYYY-MM-DD HH-MM-SS' (用 '-' 代替 ':' 避开反爬)
        normalized = ts_value.replace("-", ":", 1) if ts_value[10:11] == "-" else ts_value
        # 例如 '2024-03-20 06:00:00' 或 '2024-03-20 06-00-00'
        # 用 datetime 解析
        from datetime import datetime
        # 两种格式都试
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S"):
            try:
                dt = datetime.strptime(ts_value, fmt)
                return int(dt.timestamp())
            except ValueError:
                continue
        return 0
    except Exception:
        return 0


def enqueue_to_download_list(target: Path, new_posts: list, account: dict) -> int:
    """把 new_posts 写到 enqueue_target (download_list.json) — 原子写入"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    else:
        target.write_text("[]", encoding="utf-8")
        existing = []

    existing_ids = {str(x.get("aweme_id")) for x in existing}
    added = 0
    real_author = account.get("author") or "unknown"
    source_alias = account.get("alias") or account.get("author") or "unknown"

    for post in new_posts:
        aid = str(post.get("aweme_id", ""))
        if not aid:
            continue
        if aid in existing_ids:
            # 铁律 v285.28 (2026-08-09 02:11 Cove 拍板): silent skip 必须加 log
            # 根因: v285.22 silent failure 模式 — 静默跳过已有 aid, added=0 看不出来原因
            #       之前 jade_b 199 existing_ids + 176 new 全静默 skip → added=0, 假装"没新视频"
            # 修法: 跳过时记 1 行 log, 区分已有 vs 没拉两种情况
            log(f"  [v285.28 silent-skip] aid={aid} already in download_list.json (existing_ids={len(existing_ids)})")
            continue
        # 铁律 142 v2 (Cove 19:50): 跳过 desc='' — f2 lib 50/50 拉到 X-Bogus 缺时 desc=''
        # 入死信只会浪费空间 (635MB+), 不入死信 = 既不浪费, 也让 monitor 能继续
        post_desc = (post.get("desc") or "").strip()
        if not post_desc:
            log(f"  [Cove 142 v2] 跳过 desc 空 aweme_id={aid} author={post.get('author','')} share_url={post.get('share_url','')}")
            continue
        # 铁律 v204 (2026-07-29 19:15 Cove 拍板 P0): 跳过图文 (duration_ms=0)
        # 根因: f2 对图文返 no video_url → fail → retry 3 → dead → 死循环
        # 当前 dead 3147 中 1665 (53%) 是图文, pending 502 中 257 (51%) 是图文, paused 169 中 120 (71%) 是图文
        # 必修: monitor 端就过滤掉, 不入死信也不占 worker time
        # 重要: 仅当 duration_ms 是数字且 <= 0 才跳. duration_ms=None (字段缺失) 表示 monitor 拉时未拿到,
        # 不能判定图文 — 入队后由 download worker 用 f2 实时拉 metadata 判定
        # 铁律 v285.26 (2026-08-08 23:36 Cove 飞书反驳): 之前 douyin_api.py 硬编码 duration_ms=0
        # 导致 v204 把所有视频误判为图文 → 0 入队. 现 douyin_api.py 已改为真 f2 video_duration 字段.
        # 优先级: is_image_post=True (f2 images 字段 > 0) > duration_ms<=0 (f2 video.duration == 0)
        _is_image = post.get("is_image_post")
        _dur_raw = post.get("duration_ms")
        post_duration_ms = None
        if _dur_raw is not None:
            try:
                post_duration_ms = int(_dur_raw)
            except (TypeError, ValueError):
                post_duration_ms = None
        if _is_image is True:
            log(f"  [铁律 v204+v285.26] 跳过图文 (is_image_post=True) aweme_id={aid} images={post.get('images_count',0)} duration_ms={post_duration_ms} author={post.get('author','')} share_url={post.get('share_url','')}")
            continue
        if post_duration_ms is not None and post_duration_ms <= 0:
            log(f"  [铁律 v204] 跳过图文 (duration_ms<=0) aweme_id={aid} duration_ms={post_duration_ms} author={post.get('author','')} share_url={post.get('share_url','')}")
            continue
        # 铁律 12: 真昵称
        post_author = (post.get("author") or "").strip() or real_author
        entry = {
            "aweme_id": aid,
            "desc": post_desc,
            "author": post_author,
            "source_alias": source_alias,
            "create_time": post.get("create_time"),
            "duration_ms": post.get("duration_ms"),
            "play_url": post.get("play_url"),  # download worker 不依赖, 但保留
            "share_url": post.get("share_url") or f"https://www.douyin.com/video/{aid}",
            # 铁律 142 v3 (2026-07-23 01:55): sec_user_id 优先用 account (accounts.json 真源),
            # fallback 到 post (f2 lib 有时 None). 如果都 None, 跳过 (避免 enqueue NoneType)
            "sec_user_id": (post.get("sec_user_id") or account.get("sec_user_id") or "").strip(),
        }
        existing.append(entry)
        added += 1

    if added > 0:
        # 排序 by create_time 降序 (Cove 02:00 拍板)
        existing.sort(
            key=lambda x: str(x.get("create_time", "") or ""),
            reverse=True
        )
        # 原子写
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp.rename(target)
    return added


async def check_account(account: dict) -> dict:
    """检查单个账号 — 拉最新视频 → 写 enqueue_target → 更新 state"""
    sec_user_id = account.get("sec_user_id") or account.get("id", "")
    alias = account.get("alias", "?")
    author = account.get("author", "?")
    target_path = account.get("enqueue_target")

    if not target_path:
        log(f"  [{alias}] ⚠️ no enqueue_target, 跳过")
        return {"alias": alias, "status": "skipped", "reason": "no enqueue_target"}

    if account.get("enabled") is False:
        log(f"  [{alias}] disabled, 跳过")
        return {"alias": alias, "status": "skipped", "reason": "disabled"}

    log(f"  [{alias}] ({author}) → {target_path}")
    log(f"    sid: {sec_user_id[:30]}...")

    # 铁律 194 (Cove 00:15 拍板): mix_only 账号跳过主页 fetch_user_posts,
    # 走合集监控分支 fetch_mix_videos_for_account (拉每个 mix_id 视频入队)
    mix_only = bool(account.get("mix_only"))
    if mix_only:
        log(f"    [铁律 194] mix_only=True, 跳过主页 fetch_user_posts, 走合集监控分支")
        return await _check_mix_only_account(account)

    last_seen_ids = load_last_seen(sec_user_id)
    last_seen_with_ts = load_last_seen_with_ts(sec_user_id)
    # 铁律 v285.25 P0-X: dedup_time_window 修剪 — last_seen_with_ts 只保留 90 天窗口
    last_seen_with_ts = trim_last_seen_by_window(last_seen_with_ts)
    last_seen_in_window_ids = {str(e[0]) for e in last_seen_with_ts if e and e[0]}
    log(f"    last_seen: {len(last_seen_ids)} 个 (窗口内 dedup: {len(last_seen_in_window_ids)})")

    # 铁律 152 (Cove 11:38 拍板): fetch_strategy 决定拉多少
    # - full: 翻页拉到 has_more=0, 拉全量历史
    # - incremental: max_counts 拉最近
    # - auto (铁律 v285.78.21.3 Cove 19:04 拍板): 看 last_full_fetch_at 金标准判断
    #   - last_full_fetch_at is None → 自动 full (新账号首次, 不用读 accounts.json 字段)
    #   - last_full_fetch_at is not None → 自动 incremental (已拉过全量, 走增量)
    fetch_strategy = account.get("fetch_strategy", "auto")
    last_full_fetch_at = account.get("last_full_fetch_at")
    if fetch_strategy == "auto":
        if last_full_fetch_at is None:
            fetch_strategy = "full"
            log(f"    [铁律 285.78.21.3] fetch_strategy=auto + last_full_fetch_at=None → 自动切 full (新账号首次)")
        else:
            fetch_strategy = "incremental"
            log(f"    [铁律 285.78.21.3] fetch_strategy=auto + last_full_fetch_at={last_full_fetch_at} → 自动切 incremental (已拉过全量)")
    if fetch_strategy == "full":
        max_counts = int(account.get("initial_fetch_count", 1500))  # 铁律 v285.78.21 Cove 拍板 1500
        log(f"    [铁律 152] fetch_strategy=full, max_counts={max_counts} (拉全量历史)")
    else:
        # 铁律 v285.78.21 Cove 拍板: 增量 max_counts=1500 (拉宽涵盖最近所有新视频)
        max_counts = int(account.get("incremental_fetch_count", 1500))
        log(f"    [铁律 152 + v285.78.21] fetch_strategy=incremental, max_counts={max_counts} (拉增量)")

    # 铁律 154 (Cove 02:04): incremental 默认 200, 防止 last_seen 50 永远拉不到新视频
    # 根因: Douyin 主页只显示最新 50, monitor max_counts=50 → 永远只拉这 50, dedup 永远 0
    # 升到 200 配合 dedup, 新视频推入 51-200 区间就能被捞到
    # 铁律 152: full 模式 5000 翻到底 (has_more=0 退出), 一次拉全量
    posts = await fetch_user_posts(sec_user_id, max_counts=max_counts)
    log(f"    拉到 {len(posts)} 条")

    if not posts:
        log(f"    ⚠️ 没拉到, 跳过")
        return {"alias": alias, "status": "no_posts", "pulled": 0}

    # 铁律 v285.25 P0-X: 用 dedup_time_window 过滤 — 不让超 90 天的 last_seen 阻挡新视频
    new_posts = detect_new_with_window(posts, last_seen_with_ts)
    log(f"    新条: {len(new_posts)} (dedup_time_window={DEDUP_TIME_WINDOW_SEC}s)")

    # 写 download_list.json
    target = Path(target_path)
    added = enqueue_to_download_list(target, new_posts, account)
    log(f"    写入: {added} 条")

    # 更新 state (包含全部拉到的, 不只是新的, 这样下次拉能去重)
    # 铁律 161 (Cove 17:55 反思): union 已有的 last_seen — incremental 拉 200 不应覆盖 full 拉的 589
    # 根因: 老代码 save_last_seen 用本次拉到的 all_ids 直接覆盖,daemon incremental 跑会把
    #       之前 full 拉到的 589 覆盖回 200,导致下次 fetch 又能拉到 200-589 区间里的视频 (丢失 dedup)
    new_ids = {str(p.get("aweme_id", "")) for p in posts if p.get("aweme_id")}
    merged_ids = last_seen_ids | new_ids  # 铁律 161: union 已有 + 本次
    # 铁律 v285.25 P0-X: 同时维护 last_seen_with_ts (含 create_time) 用于 dedup_time_window
    # 修正: 抖音 create_time 是 'YYYY-MM-DD HH-MM-SS' 字符串, 用 parse_douyin_create_time 转 unix ts
    new_entries = [
        [str(p.get("aweme_id", "")), parse_douyin_create_time(p.get("create_time", 0))]
        for p in posts if p.get("aweme_id")
    ]
    merged_entries = last_seen_with_ts + new_entries
    merged_entries = trim_last_seen_by_window(merged_entries)
    # 去重 (按 aweme_id 保留最新 create_time)
    seen_ids = set()
    deduped_entries = []
    for e in reversed(merged_entries):
        if not e or not e[0]:
            continue
        if str(e[0]) in seen_ids:
            continue
        seen_ids.add(str(e[0]))
        deduped_entries.append(e)
    deduped_entries.reverse()
    # 铁律 v285.27: 必须先 save_last_seen_with_ts (新), 再 save_last_seen (旧), 否则旧函数会用 '[]' 覆盖新写入
    save_last_seen_with_ts(sec_user_id, deduped_entries, len(deduped_entries))
    save_last_seen(sec_user_id, merged_ids, len(merged_ids))
    # 铁律 161: 让 _flip_to_incremental 能读到本次拉到的 count (修 _last_pulled_count 永远 0 的 bug)
    account["_last_pulled_count"] = len(merged_ids)
    account["_last_pulled_ids"] = merged_ids

    # 铁律 152: full 拉完后自动翻 incremental (一次拉全量, 之后增量)
    # 避免下次 SIGUSR1 又拉 5000 (耗时, rate limit 风险)
    if fetch_strategy == "full":
        _flip_to_incremental(sid=sec_user_id, account=account)
        log(f"    [铁律 152] full → incremental (已自动写回 accounts.json)")

    return {
        "alias": alias,
        "status": "ok",
        "pulled": len(posts),
        "new": len(new_posts),
        "added": added,
        "target": str(target),
        "fetch_strategy": fetch_strategy,
    }


async def _check_mix_only_account(account: dict) -> dict:
    """铁律 194 (Cove 00:15 拍板): mix_only 账号走合集监控
    
    跳过 fetch_user_posts, 而是遍历 account 里所有 mix_<id> 字段 (mix_ids)
    每个 mix_id 调 fetch_mix_by_id 拉该合集所有视频入队。
    """
    sec_user_id = account.get("sec_user_id") or account.get("id", "")
    alias = account.get("alias", "?")
    author = account.get("author", "?")
    target_path = account.get("enqueue_target")
    target = Path(target_path)

    # 提取 mix_ids: account 里所有以 mix_ 开头的 key (值是 dict)
    mix_ids = []
    for key, val in account.items():
        if key.startswith("mix_") and isinstance(val, dict):
            mid = key.removeprefix("mix_")
            mix_ids.append(mid)
    if not mix_ids:
        log(f"  [{alias}] ⚠️ mix_only=True 但没找到 mix_<id> 配置, 跳过")
        return {"alias": alias, "status": "skipped", "reason": "no_mix_ids"}

    log(f"  [{alias}] ({author}) → mix_only 监控 {len(mix_ids)} 个合集")
    total_added = 0
    total_new = 0
    mix_stats = []
    from douyin_api import fetch_mix_by_id

    for mix_id in mix_ids:
        log(f"    [{alias}] mix_id={mix_id}: 拉取...")
        try:
            mix_result = await fetch_mix_by_id(mix_id)
        except Exception as e:
            log(f"    [{alias}] ❌ fetch_mix_by_id 失败: {e}")
            mix_stats.append({"mix_id": mix_id, "error": str(e)})
            continue
        if not mix_result:
            log(f"    [{alias}] ⚠️ mix_id={mix_id} 返空 (cookie 失效? 合集不存在?)")
            mix_stats.append({"mix_id": mix_id, "videos_count": 0, "status": "empty"})
            continue

        videos = mix_result.get("videos", [])
        log(f"    [{alias}] mix_id={mix_id}: {len(videos)} 视频")

        # 转成与 enqueue_to_download_list 期望的格式 (用到 mix 的视频)
        # enqueue_to_download_list 要求 dict 含 aweme_id / desc / video_url
        posts = []
        for v in videos:
            aweme_id = v.get("aweme_id")
            if not aweme_id:
                continue
            # 找视频 URL
            video_url = v.get("video_url") or ""
            # 转换 last_seen 用 str
            posts.append({
                "aweme_id": str(aweme_id),
                "desc": v.get("desc", ""),
                "video_url": video_url,
                "duration": v.get("duration", 0),
                "create_time": v.get("create_time", 0),
                "author_nickname": v.get("author_nickname", author),
                "mix_id": mix_id,
                "source": "mix",  # 标记来源合集
            })

        last_seen_ids = load_last_seen(f"mix_{mix_id}")
        new_posts = detect_new(posts, last_seen_ids)
        log(f"    [{alias}] mix_id={mix_id}: {len(new_posts)} 新视频")
        added = enqueue_to_download_list(target, new_posts, account)
        total_added += added
        total_new += len(new_posts)

        # 更新 last_seen — 用 mix_id 而非 sec_user_id (避免主页/合集 ID 冲突)
        new_ids = {str(p.get("aweme_id", "")) for p in posts if p.get("aweme_id")}
        merged_ids = last_seen_ids | new_ids
        save_last_seen(f"mix_{mix_id}", merged_ids, len(merged_ids))

        mix_stats.append({
            "mix_id": mix_id,
            "videos_count": len(videos),
            "new": len(new_posts),
            "added": added,
        })

    log(f"  [{alias}] mix_only 汇总: 新={total_new}, 入队={total_added}")
    return {
        "alias": alias,
        "status": "ok",
        "mode": "mix_only",
        "mix_count": len(mix_ids),
        "new": total_new,
        "added": total_added,
        "target": str(target),
        "mix_stats": mix_stats,
    }


def _flip_to_incremental(sid: str, account: dict) -> None:
    """铁律 152: full 拉完后, 写回 accounts.json fetch_strategy=incremental
    
    注意: accounts.json 顶层用 sec_user_id 作 key, 我们要原位更新
    """
    if not ACCOUNTS_FILE.exists():
        log(f"    ⚠️ ACCOUNTS_FILE 不存在, 无法写回")
        return
    try:
        cfg = json.loads(ACCOUNTS_FILE.read_text())
        acc = cfg.get("accounts", {}).get(sid)
        if acc and acc.get("fetch_strategy") == "full":
            acc["fetch_strategy"] = "incremental"
            acc["incremental_fetch_count"] = acc.get("incremental_fetch_count", 200)
            acc["last_full_fetch_at"] = datetime.now().isoformat(timespec="seconds")
            acc["last_full_fetch_count"] = account.get("_last_pulled_count", 0) or len(account.get("_last_pulled_ids", set()))
            # 原子写
            tmp = ACCOUNTS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(ACCOUNTS_FILE)
    except Exception as e:
        log(f"    ⚠️ _flip_to_incremental 写回失败: {e}")


async def main_async(args: argparse.Namespace) -> None:
    """主入口"""
    cfg = load_accounts()
    accounts_dict = cfg.get("accounts", {})
    if not accounts_dict:
        log("❌ accounts.json 无账号")
        return

    # 过滤 enabled
    enabled = {
        sid: acc for sid, acc in accounts_dict.items()
        if acc.get("enabled") is True
    }

    # 铁律 0.78.20.10 (Cove 18:46 闭环): douyin_recorder 直播账号不该被 v6_monitor 拉主页视频
    # 直播账号 (source_type=douyin_recorder) 走 DouyinLiveRecorder → live_output_dir → v6_enq_livestream
    # 跟 v6_monitor 的 fetch_user_post_videos + enqueue_target 链路完全独立
    # 不过滤会输出 "no enqueue_target" 噪音 log (minzu / huaiyinshanfang / zhaofeng 都中招)
    live_aliases_skipped = []
    enabled_no_live = {}
    for sid, acc in enabled.items():
        if acc.get("source_type") == "douyin_recorder":
            live_aliases_skipped.append(acc.get("alias", sid))
        else:
            enabled_no_live[sid] = acc
    if live_aliases_skipped:
        log(f"[铁律 0.78.20.10] 跳过 {len(live_aliases_skipped)} 个 douyin_recorder 直播账号: {live_aliases_skipped}")
    enabled = enabled_no_live
    
    # 铁律 152: --alias 只查某个账号 (调试 / MCP 触发)
    if args.alias:
        target_sid = None
        for sid, acc in accounts_dict.items():
            if acc.get("alias") == args.alias:
                target_sid = sid
                break
        if not target_sid:
            log(f"❌ --alias {args.alias} 不存在")
            return
        enabled = {target_sid: accounts_dict[target_sid]}
        log(f"[铁律 152] --alias 过滤: {args.alias}")
    
    log(f"=== v6_monitor {'(DRY-RUN)' if args.dry_run else ''} ===")
    log(f"accounts.json: {len(accounts_dict)} 个, enabled: {len(enabled)}")
    log("")

    results = []
    for sid, acc in enabled.items():
        # 给 acc 补 sec_user_id (accounts.json 用 sid 作 key, 但 monitor 内部逻辑用 sec_user_id 字段)
        acc_for_check = dict(acc)
        acc_for_check["sec_user_id"] = sid
        result = await check_account(acc_for_check)
        results.append(result)

    log("")
    log("=== 总结 ===")
    for r in results:
        log(f"  {r}")
    log("")

    # 调 v6_enqueue.main() 真正入队 (闭环)
    if not args.dry_run and not args.skip_enqueue:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from v6_enqueue import main as v6_enqueue_main
            log("[v6_monitor] 调 v6_enqueue.main() 自动入队...")
            # v6_enqueue 不接 argv, 跑默认 (全部账号)
            old_argv = sys.argv
            sys.argv = ["v6_enqueue.py"]
            try:
                v6_enqueue_main()
            finally:
                sys.argv = old_argv
        except Exception as e:
            log(f"❌ v6_enqueue.main() 调用失败: {e}")

    log("=== v6_monitor done ===")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="跑一次就退出 (非 daemon)")
    parser.add_argument("--skip-enqueue", action="store_true", help="写 download_list.json 但不入队")
    parser.add_argument("--daemon", action="store_true", help="daemon 模式 (24h 循环 + SIGUSR1)")
    parser.add_argument("--interval", type=int, default=86400, help="daemon 循环间隔秒数")
    parser.add_argument("--alias", type=str, help="铁律 152: 只跑某个 alias (调试/MCP)")
    args = parser.parse_args()

    _init_state_db()

    if args.daemon:
        # daemon 模式
        log(f"=== v6_monitor daemon 模式启动 (interval={args.interval}s) ===")

        # SIGUSR1 立即触发
        sigusr1_flag = {"now": False}

        def _sigusr1_handler(signum, frame):
            log("⚡ SIGUSR1 收到, 立即重跑")
            sigusr1_flag["now"] = True

        signal.signal(signal.SIGUSR1, _sigusr1_handler)

        while True:
            try:
                asyncio.run(main_async(args))
            except Exception as e:
                log(f"❌ main_async 异常: {e}")
            # 分段 sleep
            slept = 0
            while slept < args.interval:
                sleep_chunk = min(60, args.interval - slept)
                time.sleep(sleep_chunk)
                slept += sleep_chunk
                if sigusr1_flag["now"]:
                    sigusr1_flag["now"] = False
                    log("⚡ SIGUSR1 触发, 提前重跑")
                    break
    else:
        asyncio.run(main_async(args))


if __name__ == "__main__":
    main()