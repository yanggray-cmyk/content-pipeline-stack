#!/bin/bash
# rollback_to_systemd.sh — 回滚 douyin-recorder docker → systemd
# 触发: cutover_to_docker.sh 出问题时回滚
#
# 用法 (Cove 本机 sudo 执行):
#   sudo bash rollback_to_systemd.sh
#
# 步骤:
#   1. docker compose down recorder (释放 config.ini + downloads)
#   2. enable + start systemd
#   3. 验证 systemd 进程跑
#
# 注意: docker compose down -v 会删除 volumes (本设计无 named volume, 都是 host bind, 安全)

set -euo pipefail

echo "════════════════════════════════════════════════════════"
echo " rollback: douyin-recorder docker → systemd"
echo " $(date -u +%FT%TZ)"
echo "════════════════════════════════════════════════════════"

# 1. docker down
echo ""
echo "[1/3] docker compose down recorder..."
cd /home/main/.openclaw/workspace/content-pipeline-stack
docker compose down douyin-recorder
echo "    ✅ down"

# 2. systemd enable + start
echo ""
echo "[2/3] systemd enable + start..."
systemctl enable douyin-recorder
systemctl start douyin-recorder
echo "    ✅ started"

# 3. 验证
echo ""
echo "[3/3] 验证 systemd 进程..."
sleep 3
if ! pgrep -f "/home/main/DouyinLiveRecorder/main.py" >/dev/null; then
    echo "    ❌ systemd 进程没起来!需手动排查"
    journalctl -u douyin-recorder --since "1 minute ago" --no-pager
    exit 1
fi
echo "    ✅ systemd 进程已起"
echo ""
echo "    主播监控状态:"
journalctl -u douyin-recorder --since "30 seconds ago" --no-pager | tail -10

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ rollback 完成"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  验证: systemctl status douyin-recorder"
echo "  日志: journalctl -u douyin-recorder -f"