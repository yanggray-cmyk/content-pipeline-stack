#!/bin/bash
# 实时监听录制文件并自动归类

RECORDINGS_DIR="/mnt/recordings/抖音直播"
LOG_FILE="/mnt/recordings/auto-organize.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# 获取场次信息
get_session() {
    local filename="$1"
    if [[ $filename =~ _([0-9]{4}-[0-9]{2}-[0-9]{2})_([0-9]{2})- ]]; then
        echo "${BASH_REMATCH[1]}_${BASH_REMATCH[2]}"
    else
        echo ""
    fi
}

# 处理单个文件
organize_file() {
    local file="$1"
    local filename=$(basename "$file")
    local dir=$(dirname "$file")
    local room_name=$(basename "$dir")
    
    # 检查是否已经在场次文件夹中
    if [[ "$dir" =~ /场次- ]]; then
        return
    fi
    
    local session=$(get_session "$filename")
    if [ -z "$session" ]; then
        log "无法解析场次: $filename"
        return
    fi
    
    local session_dir="${dir}/场次-${session}"
    mkdir -p "$session_dir"
    
    local target="${session_dir}/${filename}"
    if [ "$file" != "$target" ]; then
        mv "$file" "$target"
        log "归类: $room_name/$filename -> 场次-${session}/"
    fi
}

# 主逻辑
log "========== 启动实时监听 =========="

if [ ! -d "$RECORDINGS_DIR" ]; then
    log "错误: 录制目录不存在"
    exit 1
fi

# 先处理已有文件
log "处理已有文件..."
find "$RECORDINGS_DIR" -maxdepth 2 -type f \( -name "*.ts" -o -name "*.mp4" \) | while read -r file; do
    organize_file "$file"
done

# 实时监听新文件
log "启动inotify监听..."
inotifywait -m -r -e create --format '%w%f' "$RECORDINGS_DIR" | while read -r file; do
    # 等待文件写入完成（简单延迟）
    sleep 2
    if [ -f "$file" ]; then
        organize_file "$file"
    fi
done
