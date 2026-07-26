# -*- encoding: utf-8 -*-

"""音频录制 (MP3 / M4A)"""

import subprocess
from .base import RecordContext, _record_error


def record_audio(ctx: RecordContext) -> bool:
    """录制音频格式 (MP3 / M4A)"""
    try:
        extension = "mp3" if "m4a" not in ctx.video_save_type.lower() else "m4a"
        name_format = "_%03d" if ctx.split_video_by_time else ""
        save_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{ctx.now}{name_format}.{extension}"

        if ctx.split_video_by_time:
            print(f'\r{ctx.anchor_name} 准备开始录制音频: {save_file_path}')
            if "MP3" in ctx.video_save_type:
                command = ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k",
                           "-f", "segment", "-segment_time", str(ctx.split_time),
                           "-reset_timestamps", "1", save_file_path]
            else:
                command = ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc",
                           "-ab", "320k", "-f", "segment", "-segment_time", str(ctx.split_time),
                           "-segment_format", 'mpegts', "-reset_timestamps", "1", save_file_path]
        else:
            if "MP3" in ctx.video_save_type:
                command = ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k", save_file_path]
            else:
                command = ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc",
                           "-ab", "320k", "-movflags", "+faststart", save_file_path]

        ctx.ffmpeg_command.extend(command)
        return ctx.check_subprocess_func(
            ctx.record_name, ctx.record_url, ctx.ffmpeg_command,
            ctx.video_save_type, ctx.custom_script
        )
    except subprocess.CalledProcessError as e:
        ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        _record_error(ctx)
    return False


def _record_error(ctx: RecordContext) -> None:
    """统一的错误记录"""
    with ctx.max_request_lock:
        ctx.error_count_ref[0] += 1
        ctx.error_window.append(1)
