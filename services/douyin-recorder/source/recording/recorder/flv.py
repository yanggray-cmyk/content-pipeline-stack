# -*- encoding: utf-8 -*-

"""FLV 录制 (ffmpeg + 直接下载)"""

import time
import threading
import subprocess
import datetime
from pathlib import Path
from .base import RecordContext, _record_error


def record_flv_direct(ctx: RecordContext) -> bool:
    """直接下载 FLV 流（shopee、花椒等平台）"""
    ctx.logger.info(f"Use Direct Downloader to Download FLV Stream: {ctx.record_url}")
    filename = ctx.anchor_name + f'_{ctx.title_in_name}' + ctx.now + '.flv'
    save_file_path = f'{ctx.full_path}/{filename}'
    print(f'{save_file_path}')

    subs_file_path = save_file_path.rsplit('.', maxsplit=1)[0]
    subs_thread_name = f'subs_{Path(subs_file_path).name}'
    if ctx.create_time_file:
        ctx.create_var[subs_thread_name] = threading.Thread(
            target=ctx.generate_subtitles_func, args=(ctx.record_name, subs_file_path)
        )
        ctx.create_var[subs_thread_name].daemon = True
        ctx.create_var[subs_thread_name].start()

    try:
        flv_url = ctx.port_info.get('flv_url')
        if flv_url:
            ctx.recording.add(ctx.record_name)
            start_record_time = datetime.datetime.now()
            ctx.recording_time_list[ctx.record_name] = [start_record_time, ctx.record_quality_zh]

            download_success = ctx.direct_download_stream_func(
                flv_url, save_file_path, ctx.record_name, ctx.record_url, ctx.platform
            )
            if download_success:
                print(f"\n{ctx.anchor_name} {time.strftime('%Y-%m-%d %H:%M:%S')} 直播录制完成\n")
            ctx.recording.discard(ctx.record_name)
        else:
            ctx.logger.debug("未找到FLV直播流，跳过录制")
    except Exception as e:
        ctx.color_obj.print_colored(
            f"\n{ctx.anchor_name} {time.strftime('%Y-%m-%d %H:%M:%S')} 直播录制出错,请检查网络\n",
            ctx.color_obj.RED
        )
        ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        _record_error(ctx)
    return False


def record_flv(ctx: RecordContext) -> bool:
    """ffmpeg 录制 FLV 格式"""
    filename = ctx.anchor_name + f'_{ctx.title_in_name}' + ctx.now + ".flv"
    print(f'{ctx.full_path}/{filename}')
    save_file_path = ctx.full_path + '/' + filename

    try:
        if ctx.split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{now}_%03d.flv"
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
                       "-f", "segment", "-segment_time", str(ctx.split_time), "-segment_format", "flv",
                       "-reset_timestamps", "1", save_file_path]
        else:
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
                       "-f", "flv", "{path}".format(path=save_file_path)]

        ctx.ffmpeg_command.extend(command)
        comment_end = ctx.check_subprocess_func(
            ctx.record_name, ctx.record_url, ctx.ffmpeg_command, "FLV", ctx.custom_script
        )
        if comment_end:
            return True

        # 转换 MP4
        if ctx.converts_to_mp4:
            seg_file_path = f"{ctx.full_path}/{ctx.anchor_name}_{ctx.title_in_name}{ctx.now}_%03d.mp4"
            if ctx.split_video_by_time:
                ctx.segment_video_func(save_file_path, seg_file_path, segment_format='mp4',
                                       segment_time=ctx.split_time, is_original_delete=ctx.delete_origin_file)
            else:
                t = threading.Thread(target=ctx.converts_mp4_func,
                                     args=(save_file_path, ctx.delete_origin_file))
                t.daemon = False
                t.start()
                ctx.logger.info(f"[fix-2026-07-04] 分段时间触发转换: {save_file_path} (daemon=False)")
    except subprocess.CalledProcessError as e:
        ctx.logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        _record_error(ctx)
    except Exception as e:
        ctx.logger.error(f"转码失败: {e}")
    return False
