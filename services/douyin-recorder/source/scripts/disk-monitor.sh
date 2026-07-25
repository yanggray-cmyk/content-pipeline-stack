#!/bin/bash
# 磁盘监控脚本 - 低于5GB停止录制
THRESHOLD=5  # 5GB
DISK_FREE=$(df -BG /home/main | tail -1 | awk '{print $4}' | sed 's/G//')
LOG_FILE="/home/main/DouyinLiveRecorder/logs/disk-alert.log"

if [ "$DISK_FREE" -lt "$THRESHOLD" ]; then
    echo "[$(date)] 警告：磁盘空间不足！剩余 ${DISK_FREE}GB，停止录制" >> $LOG_FILE
    cd /home/main/DouyinLiveRecorder && docker compose stop
    echo "[$(date)] 录制已停止" >> $LOG_FILE
fi
