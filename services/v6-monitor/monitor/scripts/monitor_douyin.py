#!/usr/bin/env python3
"""monitor_douyin.py — 抖音账号监控 (2026-07-16 数据盘迁移版)"""
import os, sys, json, time, asyncio, argparse, threading, signal
from pathlib import Path
from datetime import datetime

SKILL_ROOT = Path(__file__).parent.parent
ACCOUNTS_FILE = SKILL_ROOT / "accounts.json"
STATE_FILE = SKILL_ROOT / "state/last_seen.json"
LOG_FILE = SKILL_ROOT / "logs/monitor.log"

BRAND_VIDEO_ROOT = Path("/home/main/.openclaw/workspace/skills/brand-video-tools")
sys.path.insert(0, str(BRAND_VIDEO_ROOT / "scripts"))


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_accounts():
    """读 accounts.json → list of account dicts

    兼容两种格式 (铁律 173: 真源 = /home/main/douyin-data/config/accounts.json, dict by sec_uid):
    - 旧格式: {"accounts": [ {sec_user_id, name, alias, ...}, ... ]} (monitor 传统)
    - 新格式 (铁律 173): {"accounts": {sec_uid: {author, alias, ...}, ...}} (v6_enqueue 真源)

    新格式字段映射 (cfg 真源 → monitor 期望):
    - name      ← author
    - alias     ← alias
    - sec_user_id ← key
    - alerts_dir / alert_log / check_interval_sec / enqueue_target 等字段直接从 cfg 取
    """
    raw = json.loads(ACCOUNTS_FILE.read_text())["accounts"]
    if isinstance(raw, dict):
        # 新格式: dict by sec_uid
        result = []
        for sec_uid, acc in raw.items():
            entry = dict(acc)  # 拷贝避免改真源
            entry["sec_user_id"] = sec_uid
            entry["name"] = acc.get("author") or acc.get("name") or sec_uid
            result.append(entry)
        return result
    else:
        # 旧格式: list
        return raw


def save_accounts(accounts_list):
    """将变更后的账号列表写回 accounts.json (原子重写)

    铁律 173: 真源是 dict by sec_uid 格式. 我们转回 dict 再写.
    """
    # 读真源结构 (避免破坏顶层 metadata 字段)
    if ACCOUNTS_FILE.exists():
        raw = json.loads(ACCOUNTS_FILE.read_text())
    else:
        raw = {"accounts": {}}

    accounts_dict = {}
    for acc in accounts_list:
        sec_uid = acc.get("sec_user_id")
        if not sec_uid:
            continue
        # 把 monitor 字段映射回 cfg 字段
        entry = dict(acc)
        entry["author"] = acc.get("name") or acc.get("author") or sec_uid
        # name 是 monitor 字段, 写到 cfg 的 author
        entry.pop("name", None)
        # sec_user_id 不再写在 value 里 (它是 key)
        entry.pop("sec_user_id", None)
        accounts_dict[sec_uid] = entry

    raw["accounts"] = accounts_dict
    ACCOUNTS_FILE.write_text(json.dumps(
        raw, indent=2, ensure_ascii=False
    ), encoding="utf-8")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


async def fetch_latest_20(sec_user_id: str, max_counts: int = 50):
    """拉用户主页视频列表（支持全量翻页）

    f2 v0.0.1.7 ABogus pagination 实测通过:
      - Page 1-11: 每次 has_more=1, max_cursor 正常更新
      - ~18-22 条/页，稳定翻页
    """
    from douyin_api import fetch_user_posts
    return await fetch_user_posts(sec_user_id, max_counts=max_counts)


def detect_new(posts: list, last_seen_ids: set) -> list:
    return [p for p in posts if str(p.get("aweme_id", "")) not in last_seen_ids]


def save_alert_file(account: dict, post: dict):
    alert_dir = Path(account["alerts_dir"]) / account["alias"]
    alert_dir.mkdir(parents=True, exist_ok=True)
    aid = str(post.get("aweme_id", ""))
    path = alert_dir / f"{aid}.json"
    path.write_text(json.dumps({
        "account": account["name"], "alias": account["alias"],
        "aweme_id": aid, "title": post.get("desc", ""),
        "create_time": post.get("create_time"),
        "duration_ms": post.get("duration_ms"),
        "play_url": post.get("play_url"), "cover_url": post.get("cover_url"),
        "detected_at": datetime.now().isoformat(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def enqueue_to_batch(account: dict, post: dict):
    target = Path(account["enqueue_target"])
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]", encoding="utf-8")
    existing = json.loads(target.read_text(encoding="utf-8"))
    existing_ids = {str(x.get("aweme_id")) for x in existing}
    aid = str(post.get("aweme_id", ""))
    # 2026-07-20 铁律 12 fix: 优先用 post API 返回的 author (真昵称),
    # fallback 到 accounts.json.name (用户预定义/占位)。
    real_author = (post.get("author") or "").strip() or account["name"]
    if aid not in existing_ids:
        new_entry = {
            "aweme_id": aid, "desc": post.get("desc", ""),
            "create_time": post.get("create_time"),
            "duration_ms": post.get("duration_ms"),
            "play_url": post.get("play_url"),
            "cover_url": post.get("cover_url"),
            "author": real_author, "sec_user_id": account["sec_user_id"],
            "source": "monitor_auto", "queued_at": datetime.now().isoformat(),
        }
        # 2026-07-22 01:46 GMT+8 fix: append + 写入前按 create_time 字符串降序排序
        # Cove 拍板 01:29: 最新在头. 玉留君 API 单页 20 条内严格降序, 但大雅 API 内部乱序
        # (实测 766203 766202 766167 顺序错乱), 不能依赖 Douyin 返回顺序.
        # 改: append 后整体 sort (key=create_time, reverse=True) → 写入时 newest 在头
        # 注意: create_time 是字符串 "YYYY-MM-DD HH-MM-SS" (douyin_api 格式),
        #       字符串字典序 = 时间序, 所以可以直接 reverse=True
        existing.append(new_entry)
        existing.sort(key=lambda x: str(x.get("create_time", "") or ""), reverse=True)
        target.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"  ENQUEUE: {aid} → {target}")
        return True
    # 2026-07-20 16:50 fix: 账号首发后, 之前 download_list.json 里 author 是占位名
    # (_pending_xxx), 如果现在拿到了真 author → 原地 patch (避免下游全错)
    for entry in existing:
        if str(entry.get("aweme_id")) == aid:
            if entry.get("author", "").startswith("_pending_") and real_author and not real_author.startswith("_pending_"):
                old = entry["author"]
                entry["author"] = real_author
                log(f"  PATCH author: {aid} {old} → {real_author}")
                target.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            break
    return False


def patch_account_name_if_pending(account: dict, real_author: str):
    """账号首发后, accounts.json.name 还是 _pending_xxx → 原地 patch 为真名,
    并从 tags 删 'pending_nickname'。这是铁律 12 fix 的 fallback 配套。
    读 + 改 + 写 accounts.json (原子), 不依赖调用方的 dict 引用。
    """
    if not real_author or real_author.startswith("_pending_"):
        return False
    alias = account.get("alias", "")
    if not alias:
        return False
    all_accounts = load_accounts()
    target = None
    for a in all_accounts:
        if a.get("alias") == alias:
            target = a
            break
    if not target:
        return False
    if not target["name"].startswith("_pending_"):
        return False  # 已被别处 patch 过
    old_name = target["name"]
    target["name"] = real_author
    tags = target.get("tags", []) or []
    if "pending_nickname" in tags:
        tags = [t for t in tags if t != "pending_nickname"]
        target["tags"] = tags
    target["name_resolved_at"] = datetime.now().isoformat()
    save_accounts(all_accounts)
    log(f"  PATCH accounts.json: {old_name} → {real_author}")
    return True


def patch_download_list_authors(target: Path, sec_user_id: str, real_author: str):
    """账号首发后, download_list.json 里 author 是 _pending_xxx → 原地 patch 为真名
    (仅 patch 该账号的 entries, 按 sec_user_id 匹配; 不动其他账号)。
    返回 patch 数量。
    """
    if not real_author or real_author.startswith("_pending_"):
        return 0
    if not target.exists():
        return 0
    existing = json.loads(target.read_text(encoding="utf-8"))
    patched = 0
    for entry in existing:
        if entry.get("sec_user_id") == sec_user_id and entry.get("author", "").startswith("_pending_"):
            entry["author"] = real_author
            patched += 1
    if patched > 0:
        target.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"  PATCH download_list.json: {patched} 条 author → {real_author}")
    return patched


async def check_account(account: dict, state: dict) -> dict:
    alias = account["alias"]
    log(f"[{alias}] 检查 {account['name']}")

    # 新账号（无 state）：拉全部历史视频（pagination，最多 2000）
    # 已有账号：拉最新 50 条
    acc_state = state.get(alias, {})
    if not acc_state.get("last_seen_aweme_ids"):
        log(f"[{alias}] 新账号，拉取全部历史视频...")
        posts = await fetch_latest_20(account["sec_user_id"], max_counts=2000)
    else:
        posts = await fetch_latest_20(account["sec_user_id"], max_counts=50)

    if not posts:
        return {"alias": alias, "error": "no_posts"}

    last_seen = set(acc_state.get("last_seen_aweme_ids", []))
    page_ids = [str(p["aweme_id"]) for p in posts if p.get("aweme_id")]
    new_posts = detect_new(posts, last_seen)

    log(f"[{alias}] 拉 {len(posts)} 条, 新增 {len(new_posts)} 条")

    # 2026-07-20 16:50 fix: 账号首发后, accounts.json.name 是 _pending_xxx → 拿到真名后
    # 原地 patch accounts.json (避免下游全错).  只从首条 post 取 author.
    if account["name"].startswith("_pending_") and posts:
        first_real_author = (posts[0].get("author") or "").strip()
        if first_real_author and not first_real_author.startswith("_pending_"):
            if patch_account_name_if_pending(account, first_real_author):
                # 同名 patch download_list.json (上一个 cycle 留下的 _pending_xxx entries)
                target = Path(account.get("enqueue_target", ""))
                if target.exists():
                    patch_download_list_authors(target, account["sec_user_id"], first_real_author)

    for p in new_posts:
        save_alert_file(account, p)
        if account.get("auto_enqueue"):
            enqueue_to_batch(account, p)

    # 2026-07-25 19:45 fix: last_seen 累积并集, 不覆盖 (防老 aid 掉出后重报)
    # 铁律 161 同款 bug: page_ids 只有最新 50 条, 直接覆盖会丢掉历史 994 条
    state[alias] = {
        "last_seen_aweme_ids": sorted(set(page_ids) | last_seen),
        "last_check": datetime.now().isoformat(),
        "total_posts_observed": state.get(alias, {}).get("total_posts_observed", 0) + len(new_posts),
    }

    return {"alias": alias, "name": account["name"], "page_total": len(posts), "new_total": len(new_posts)}


async def main_async(args):
    accounts = load_accounts()
    state = load_state()

    if args.check:
        accounts = [a for a in accounts if a["alias"] == args.check]

    if args.json:
        results = [await check_account(a, state) for a in accounts]
        save_state(state)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    if args.daemon:
        interval = args.interval or _get_default_interval(accounts)
        log(f"=== Daemon 模式启动: {len(accounts)} 个账号, 间隔 {interval}s ===")

        # SIGUSR1 flag — 收到信号后立即触发一次检查
        sig_flag = threading.Event()

        def sigusr1_handler(signum, frame):
            sig_flag.set()
            log("[daemon] 收到 SIGUSR1，立即触发检查")

        signal.signal(signal.SIGUSR1, sigusr1_handler)

        while True:
            # 分段 sleep，让信号能及时响应（每次最多等 interval 秒）
            chunk = min(interval, 60)
            remaining = interval
            while remaining > 0:
                elapsed = sig_flag.wait(timeout=chunk)
                if sig_flag.is_set():
                    sig_flag.clear()
                    break
                remaining -= chunk

            # 2026-07-20 铁律 87 fix: 每个 cycle 重读 accounts.json,
            # 让增/改/暂停的账号下个周期生效（不需 restart daemon）。
            accounts = load_accounts()
            log(f"=== 监控启动: {len(accounts)} 个账号 ===")
            for acc in accounts:
                if not acc.get("enabled", True): continue
                try:
                    await check_account(acc, state)
                    save_state(state)
                except Exception as e:
                    log(f"[{acc['alias']}] ❌ {e}")
            log("=== 监控完成 ===")
            if not sig_flag.is_set():
                log(f"=== 休眠 {interval}s ===")
    else:
        log(f"=== 监控启动: {len(accounts)} 个账号 ===")
        for acc in accounts:
            if not acc.get("enabled", True): continue
            try:
                await check_account(acc, state)
                save_state(state)
            except Exception as e:
                log(f"[{acc['alias']}] ❌ {e}")
        log("=== 监控完成 ===")
        return 0


def _get_default_interval(accounts: list) -> int:
    for acc in accounts:
        iv = acc.get("check_interval_sec")
        if iv:
            return int(iv)
    return 600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", type=str)
    ap.add_argument("--daemon", action="store_true", help="持续循环运行，不退出")
    ap.add_argument("--interval", type=int, default=None, help="循环间隔秒数（默认从 accounts.json 读取）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
