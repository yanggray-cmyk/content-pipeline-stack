#!/bin/bash
# cutover_to_docker.sh — Cove sudo 一键切换 douyin-recorder systemd → docker
# 触发: 2026-07-26 Day 3 (b) 完成,Cove 拍板切 docker
#
# 用法 (Cove 本机 sudo 执行):
#   sudo bash cutover_to_docker.sh
#
# 步骤:
#   1. 停 systemd recorder (释放 config.ini + downloads 锁)
#   2. disable 防止重启
#   3. 验证进程已停
#   4. docker compose up -d recorder
#   5. 验证容器起 + monitor loop 跑
#
# 回滚 (如有问题):
#   sudo bash rollback_to_systemd.sh

set -euo pipefail

echo "════════════════════════════════════════════════════════"
echo " cutover: douyin-recorder systemd → docker"
echo " $(date -u +%FT%TZ)"
echo "════════════════════════════════════════════════════════"

# 1. 停 systemd
echo ""
echo "[1/5] 停 systemd douyin-recorder..."
systemctl stop douyin-recorder
echo "    ✅ stopped"

# 2. disable
echo ""
echo "[2/5] disable systemd douyin-recorder..."
systemctl disable douyin-recorder
echo "    ✅ disabled"

# 3. 验证进程
echo ""
echo "[3/5] 验证 systemd 进程已停..."
sleep 2
if pgrep -f "/home/main/DouyinLiveRecorder/main.py" >/dev/null; then
    echo "    ❌ 还有 systemd 进程在跑!停止切换"
    pgrep -af "/home/main/DouyinLiveRecorder/main.py"
    exit 1
fi
echo "    ✅ 无 systemd 进程"

# 4. docker compose up
echo ""
echo "[4/5] docker compose up -d recorder..."
cd /home/main/.openclaw/workspace/content-pipeline-stack
docker compose up -d douyin-recorder
echo "    ✅ up"

# 5. 验证
echo ""
echo "[5/5] 验证容器状态..."
sleep 5
docker compose ps douyin-recorder
echo ""
echo "    看容器日志最后 20 行 (应看到 monitor loop):"
docker compose logs --tail 20 douyin-recorder

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ cutover 完成"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  验证: docker compose ps"
echo "  日志: docker compose logs -f douyin-recorder"
echo "  回滚: sudo bash rollback_to_systemd.sh"