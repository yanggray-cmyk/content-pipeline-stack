#!/bin/bash
# 直播录制文件按场次归类脚本
# 使用规则：根据文件名中的时间戳，将同一场直播的分段文件归类到同一文件夹

RECORDINGS_DIR="/mnt/recordings/抖音直播"
LOG_FILE="/home/main/recordings/organize.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 解析文件名获取场次信息
# 文件名格式：直播间名_2026-06-06_14-56-30_000.ts
get_session_from_filename() {
    local filename="$1"
    # 提取日期和时间（小时）
    if [[ $filename =~ _([0-9]{4}-[0-9]{2}-[0-9]{2})_([0-9]{2})- ]]; then
        local date="${BASH_REMATCH[1]}"
        local hour="${BASH_REMATCH[2]}"
        echo "${date}_${hour}"
    else
        echo "unknown"
    fi
}

# 处理单个直播间目录
organize_room() {
    local room_dir="$1"
    local room_name=$(basename "$room_dir")
    
    log "处理直播间: $room_name"
    
    # 收集所有文件并按场次分组
    declare -A session_files
    
    while IFS= read -r file; do
        local filename=$(basename "$file")
        local session=$(get_session_from_filename "$filename")
        
        if [ "$session" != "unknown" ]; then
            session_files[$session]+="$file|"
            log "  文件: $filename -> 场次: $session"
        else
            log "  警告: 无法解析文件名: $filename"
        fi
    done < <(find "$room_dir" -maxdepth 1 -type f \( -name "*.ts" -o -name "*.mp4" \) | sort)
    
    # 创建场次文件夹并移动文件
    for session in "${!session_files[@]}"; do
        local session_dir="${room_dir}/场次-${session}"
        mkdir -p "$session_dir"
        
        IFS='|' read -ra files <<< "${session_files[$session]}"
        for file in "${files[@]}"; do
            if [ -n "$file" ] && [ -f "$file" ]; then
                local filename=$(basename "$file")
                local target="${session_dir}/${filename}"
                
                if [ "$file" != "$target" ]; then
                    mv "$file" "$target"
                    log "  移动: $filename -> 场次-${session}/"
                fi
            fi
        done
        
        log "  完成场次: ${session}, 文件数: ${#files[@]}"
    done
}

# 主逻辑
log "========== 开始归类录制文件 =========="

if [ ! -d "$RECORDINGS_DIR" ]; then
    log "错误: 录制目录不存在: $RECORDINGS_DIR"
    exit 1
fi

# 遍历所有直播间目录
for room_dir in "$RECORDINGS_DIR"/*/; do
    if [ -d "$room_dir" ]; then
        organize_room "$room_dir"
    fi
done

log "========== 归类完成 =========="

# 显示结果
echo ""
echo "归类后的目录结构:"
find "$RECORDINGS_DIR" -type d | sort
