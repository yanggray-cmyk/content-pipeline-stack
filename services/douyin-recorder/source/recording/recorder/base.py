# -*- encoding: utf-8 -*-

"""录制上下文 & 格式分发器"""

import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from src.utils import Color


@dataclass
class RecordContext:
    """录制运行时上下文 —— 统一传递录制所需的所有参数

    替代 record_by_format() 原有 25+ 个独立参数。
    """

    # === 身份信息 ===
    port_info: Dict[str, Any] = field(default_factory=dict)
    anchor_name: str = ""
    title_in_name: str = ""
    platform: str = ""
    record_url: str = ""
    record_name: str = ""
    record_quality_zh: str = ""

    # === 输出配置 ===
    full_path: str = ""
    ffmpeg_command: List[str] = field(default_factory=list)
    video_save_type: str = "TS"
    now: str = ""  # 格式化的时间戳，set before dispatch

    # === 录制选项 ===
    split_video_by_time: bool = False
    split_time: int = 0
    converts_to_mp4: bool = False
    delete_origin_file: bool = False
    create_time_file: bool = False
    custom_script: str = ""
    show_url: bool = False

    # === 运行时可变状态 ===
    recording: set = field(default_factory=set)
    recording_time_list: dict = field(default_factory=dict)
    create_var: dict = field(default_factory=dict)
    max_request_lock: Any = None
    error_count_ref: list = field(default_factory=list)  # [count] - 可变引用
    error_window: list = field(default_factory=list)

    # === 回调函数 ===
    check_subprocess_func: Any = None
    direct_download_stream_func: Any = None
    segment_video_func: Any = None
    converts_mp4_func: Any = None
    generate_subtitles_func: Any = None

    # === 外部依赖 ===
    color_obj: Color = None
    logger: Any = None


def _record_error(ctx: RecordContext) -> None:
    """统一的错误记录"""
    with ctx.max_request_lock:
        ctx.error_count_ref[0] += 1
        ctx.error_window.append(1)


def record_by_format(ctx: RecordContext) -> bool:
    """按格式分发录制执行

    Args:
        ctx: 录制上下文

    Returns:
        是否应该退出
    """
    if not ctx.now:
        ctx.now = datetime.datetime.today().strftime("%Y-%m-%d_%H-%M-%S")

    real_url = ctx.port_info.get('real_url', '')
    record_save_type = ctx.video_save_type

    # 注册录制
    ctx.recording.add(ctx.record_name)
    start_record_time = datetime.datetime.now()
    ctx.recording_time_list[ctx.record_name] = [start_record_time, ctx.record_quality_zh]

    if ctx.show_url:
        re_plat = ('WinkTV', 'PandaTV', 'ShowRoom', 'CHZZK', 'Youtube')
        if ctx.platform in re_plat:
            ctx.logger.info(f"{ctx.platform} | {ctx.anchor_name} | 直播源地址: {ctx.port_info.get('m3u8_url')}")
        else:
            ctx.logger.info(f"{ctx.platform} | {ctx.anchor_name} | 直播源地址: {real_url}")

    # 特殊平台格式调整
    only_flv_record = ctx.platform in ('shopee', '花椒直播')
    if only_flv_record:
        ctx.logger.debug(f"提示: {ctx.platform} 将强制使用FLV格式录制")

    only_audio_record = ctx.platform in ('猫耳FM直播', 'Look直播')

    # === 格式分发 ===
    from .audio import record_audio
    from .flv import record_flv, record_flv_direct
    from .standard import record_mkv, record_mp4, record_ts

    if only_audio_record or any(i in record_save_type for i in ['MP3', 'M4A']):
        return record_audio(ctx)

    if only_flv_record:
        return record_flv_direct(ctx)

    if record_save_type == "FLV":
        return record_flv(ctx)

    if record_save_type == "MKV":
        return record_mkv(ctx)

    if record_save_type == "MP4":
        return record_mp4(ctx)

    # 默认 TS
    return record_ts(ctx)
