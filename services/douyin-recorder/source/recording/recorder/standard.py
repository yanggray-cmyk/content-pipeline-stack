# -*- encoding: utf-8 -*-

"""标准视频录制 (MKV / MP4 / TS)"""

import os
import time
import subprocess
from .base import RecordContext, _record_error

from src import utils


def record_mkv(ctx: RecordContext) -> bool:
    """录制 MKV 格式"""
    filename = ctx.anchor_name + f'_{ctx.title_in_name}' + ctx.now + ".mkv"
    print(f'{ctx.full_path}/{filename}')
    save_file_path = ctx.full_path + '/' + filename

    try:
        if ctx.split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{now}_%03d.mkv"
            command = ["-flags", "global_header", "-c:v", "copy", "-c:a", "aac", "-map", "0",
                       "-f", "segment", "-segment_time", str(ctx.split_time), "-segment_format", "matroska",
                       "-reset_timestamps", "1", save_file_path]
        else:
            command = ["-flags", "global_header", "-map", "0", "-c:v", "copy", "-c:a", "copy",
                       "-f", "matroska", "{path}".format(path=save_file_path)]

        ctx.ffmpeg_command.extend(command)
        return ctx.check_subprocess_func(
            ctx.record_name, ctx.record_url, ctx.ffmpeg_command, "MKV", ctx.custom_script
        )
    except subprocess.CalledProcessError as e:
        ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        _record_error(ctx)
    return False


def record_mp4(ctx: RecordContext) -> bool:
    """录制 MP4 格式"""
    filename = ctx.anchor_name + f'_{ctx.title_in_name}' + ctx.now + ".mp4"
    print(f'{ctx.full_path}/{filename}')
    save_file_path = ctx.full_path + '/' + filename

    try:
        if ctx.split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{now}_%03d.mp4"
            command = ["-c:v", "copy", "-c:a", "aac", "-map", "0", "-f", "segment",
                       "-segment_time", str(ctx.split_time), "-segment_format", "mp4",
                       "-reset_timestamps", "1", "-movflags", "+frag_keyframe+empty_moov",
                       save_file_path]
        else:
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-f", "mp4", save_file_path]

        ctx.ffmpeg_command.extend(command)
        return ctx.check_subprocess_func(
            ctx.record_name, ctx.record_url, ctx.ffmpeg_command, "MP4", ctx.custom_script
        )
    except subprocess.CalledProcessError as e:
        ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        _record_error(ctx)
    return False


def record_ts(ctx: RecordContext) -> bool:
    """录制 TS 格式（默认格式）"""
    if ctx.split_video_by_time:
        now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        filename = ctx.anchor_name + f'_{ctx.title_in_name}' + now + ".ts"
        print(f'{ctx.full_path}/{filename}')

        try:
            save_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{now}_%03d.ts"
            command = ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-f", "segment",
                       "-segment_time", str(ctx.split_time), "-segment_format", 'mpegts',
                       "-reset_timestamps", "1", save_file_path]

            ctx.ffmpeg_command.extend(command)
            comment_end = ctx.check_subprocess_func(
                ctx.record_name, ctx.record_url, ctx.ffmpeg_command, "TS", ctx.custom_script
            )
            if comment_end:
                if ctx.converts_to_mp4:
                    file_paths = utils.get_file_paths(os.path.dirname(save_file_path))
                    prefix = os.path.basename(save_file_path).rsplit('_', maxsplit=1)[0]
                    for path in file_paths:
                        if prefix in path:
                            try:
                                ctx.logger.info(
                                    f"[fix-2026-07-04] 同步转换(注释触发): {path} "
                                    f"(delete_origin={ctx.delete_origin_file})"
                                )
                                ctx.converts_mp4_func(path, ctx.delete_origin_file)
                            except Exception as e:
                                ctx.logger.error(f"转码失败: {path} - {e}")
                return True
        except subprocess.CalledProcessError as e:
            ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
            _record_error(ctx)
    else:
        filename = ctx.anchor_name + f'_{ctx.title_in_name}' + ctx.now + ".ts"
        print(f'{ctx.full_path}/{filename}')
        save_file_path = ctx.full_path + '/' + filename

        try:
            command = ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-f", "mpegts", save_file_path]
            ctx.ffmpeg_command.extend(command)
            comment_end = ctx.check_subprocess_func(
                ctx.record_name, ctx.record_url, ctx.ffmpeg_command, "TS", ctx.custom_script
            )
            if comment_end:
                try:
                    ctx.logger.info(
                        f"[fix-2026-07-04] 同步转换(单段结束): {save_file_path} "
                        f"(delete_origin={ctx.delete_origin_file})"
                    )
                    ctx.converts_mp4_func(save_file_path, ctx.delete_origin_file)
                except Exception as e:
                    ctx.logger.error(f"转码失败: {save_file_path} - {e}")
                return True
        except subprocess.CalledProcessError as e:
            ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
            _record_error(ctx)

    return False
