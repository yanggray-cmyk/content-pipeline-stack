#!/bin/bash
# monitor_daemon.sh - cron */5 触发
set -euo pipefail
LOCKFILE=/tmp/douyin-monitor.lock
if [ -f "$LOCKFILE" ] && kill -0 "$(cat "$LOCKFILE")" 2>/dev/null; then
    exit 0
fi
rm -f "$LOCKFILE"
echo $$ > "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

SKILL_DIR="/home/main/douyin-data/skills/douyin-monitor"
mkdir -p "$SKILL_DIR/logs"
LOG_FILE="$SKILL_DIR/logs/daemon-$(date +%Y%m%d-%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1
echo "[monitor-daemon] 启动 $(date +%Y-%m-%d\ %H:%M:%S) GMT+8"
python3 "$SKILL_DIR/scripts/monitor_douyin.py" --once
echo "[monitor-daemon] 完成"
