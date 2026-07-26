# -*- encoding: utf-8 -*-

"""录制执行模块 - 按格式录制"""

import os
import time
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from src import utils
from src.utils import Color


def record_by_format(
    port_info: Dict[str, Any],
    anchor_name: str,
    title_in_name: str,
    platform: str,
    record_url: str,
    record_name: str,
    record_quality_zh: str,
    full_path: str,
    ffmpeg_command: List[str],
    video_save_type: str,
    split_video_by_time: bool,
    split_time: int,
    converts_to_mp4: bool,
    delete_origin_file: bool,
    create_time_file: bool,
    custom_script: str,
    recording: set,
    recording_time_list: dict,
    check_subprocess_func,
    direct_download_stream_func,
    segment_video_func,
    converts_mp4_func,
    generate_subtitles_func,
    create_var: dict,
    max_request_lock,
    error_count_ref: list,
    error_window: list,
    color_obj: Color,
    logger,
    show_url: bool = False
) -> bool:
    """
    按格式执行录制
    
    Args:
        port_info: 流信息
        anchor_name: 主播名
        title_in_name: 标题（用于文件名）
        platform: 平台名称
        record_url: 录制 URL
        record_name: 录制名称
        record_quality_zh: 录制质量（中文）
        full_path: 保存路径
        ffmpeg_command: ffmpeg 基础命令
        video_save_type: 保存格式
        split_video_by_time: 是否按时间分段
        split_time: 分段时长
        converts_to_mp4: 是否转换为 MP4
        delete_origin_file: 是否删除原文件
        create_time_file: 是否创建时间文件
        custom_script: 自定义脚本
        recording: 录制中集合
        recording_time_list: 录制时间列表
        check_subprocess_func: 检查子进程函数
        direct_download_stream_func: 直接下载流函数
        segment_video_func: 分段视频函数
        converts_mp4_func: 转换 MP4 函数
        generate_subtitles_func: 生成字幕函数
        create_var: 创建变量字典
        max_request_lock: 最大请求锁
        error_count_ref: 错误计数引用
        error_window: 错误窗口
        color_obj: 颜色对象
        logger: 日志对象
        show_url: 是否显示 URL
        
    Returns:
        是否应该退出
    """
    now = datetime.datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
    real_url = port_info.get('real_url', '')
    record_save_type = video_save_type
    
    # 注册录制
    recording.add(record_name)
    start_record_time = datetime.datetime.now()
    recording_time_list[record_name] = [start_record_time, record_quality_zh]
    rec_info = f"\r{anchor_name} 准备开始录制视频: {full_path}"
    
    if show_url:
        re_plat = ('WinkTV', 'PandaTV', 'ShowRoom', 'CHZZK', 'Youtube')
        if platform in re_plat:
            logger.info(f"{platform} | {anchor_name} | 直播源地址: {port_info.get('m3u8_url')}")
        else:
            logger.info(f"{platform} | {anchor_name} | 直播源地址: {real_url}")
    
    # 特殊平台格式处理
    only_flv_record = False
    only_flv_platform_list = ['shopee', '花椒直播']
    if platform in only_flv_platform_list:
        logger.debug(f"提示: {platform} 将强制使用FLV格式录制")
        only_flv_record = True
    
    only_audio_record = False
    only_audio_platform_list = ['猫耳FM直播', 'Look直播']
    if platform in only_audio_platform_list:
        only_audio_record = True
    
    # 按格式录制
    if only_audio_record or any(i in record_save_type for i in ['MP3', 'M4A']):
        return _record_audio(
            anchor_name, title_in_name, now, full_path, record_save_type,
            split_video_by_time, split_time, ffmpeg_command, record_name,
            record_url, custom_script, check_subprocess_func, max_request_lock,
            error_count_ref, error_window, logger
        )
    
    if only_flv_record:
        return _record_flv_direct(
            port_info, anchor_name, title_in_name, now, full_path, record_url,
            platform, record_name, record_quality_zh, recording, recording_time_list,
            direct_download_stream_func, generate_subtitles_func, create_time_file,
            create_var, max_request_lock, error_count_ref, error_window, color_obj, logger
        )
    
    if record_save_type == "FLV":
        return _record_flv(
            anchor_name, title_in_name, now, full_path, split_video_by_time,
            split_time, converts_to_mp4, delete_origin_file, ffmpeg_command,
            record_name, record_url, custom_script, check_subprocess_func,
            segment_video_func, converts_mp4_func, max_request_lock,
            error_count_ref, error_window, logger
        )
    
    if record_save_type == "MKV":
        return _record_mkv(
            anchor_name, title_in_name, now, full_path, split_video_by_time,
            split_time, ffmpeg_command, record_name, record_url, custom_script,
            check_subprocess_func, max_request_lock, error_count_ref, error_window, logger
        )
    
    if record_save_type == "MP4":
        return _record_mp4(
            anchor_name, title_in_name, now, full_path, split_video_by_time,
            split_time, ffmpeg_command, record_name, record_url, custom_script,
            check_subprocess_func, max_request_lock, error_count_ref, error_window, logger
        )
    
    # 默认 TS
    return _record_ts(
        anchor_name, title_in_name, now, full_path, split_video_by_time,
        split_time, converts_to_mp4, delete_origin_file, ffmpeg_command,
        record_name, record_url, custom_script, check_subprocess_func,
        converts_mp4_func, max_request_lock, error_count_ref, error_window, logger
    )


def _record_audio(anchor_name, title_in_name, now, full_path, record_save_type,
                  split_video_by_time, split_time, ffmpeg_command, record_name,
                  record_url, custom_script, check_subprocess_func, max_request_lock,
                  error_count_ref, error_window, logger):
    """录制音频"""
    try:
        extension = "mp3" if "m4a" not in record_save_type.lower() else "m4a"
        name_format = "_%03d" if split_video_by_time else ""
        save_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}{name_format}.{extension}"
        
        if split_video_by_time:
            print(f'\r{anchor_name} 准备开始录制音频: {save_file_path}')
            if "MP3" in record_save_type:
                command = ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k",
                          "-f", "segment", "-segment_time", split_time, "-reset_timestamps", "1",
                          save_file_path]
            else:
                command = ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc",
                          "-ab", "320k", "-f", "segment", "-segment_time", split_time,
                          "-segment_format", 'mpegts', "-reset_timestamps", "1", save_file_path]
        else:
            if "MP3" in record_save_type:
                command = ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k", save_file_path]
            else:
                command = ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc",
                          "-ab", "320k", "-movflags", "+faststart", save_file_path]
        
        ffmpeg_command.extend(command)
        comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, record_save_type, custom_script)
        return comment_end
    except subprocess.CalledProcessError as e:
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        with max_request_lock:
            error_count_ref[0] += 1
            error_window.append(1)
    return False


def _record_flv_direct(port_info, anchor_name, title_in_name, now, full_path, record_url,
                       platform, record_name, record_quality_zh, recording, recording_time_list,
                       direct_download_stream_func, generate_subtitles_func, create_time_file,
                       create_var, max_request_lock, error_count_ref, error_window, color_obj, logger):
    """直接下载 FLV 流"""
    logger.info(f"Use Direct Downloader to Download FLV Stream: {record_url}")
    filename = anchor_name + f'_{title_in_name}' + now + '.flv'
    save_file_path = f'{full_path}/{filename}'
    print(f'{save_file_path}')
    
    subs_file_path = save_file_path.rsplit('.', maxsplit=1)[0]
    subs_thread_name = f'subs_{Path(subs_file_path).name}'
    if create_time_file:
        create_var[subs_thread_name] = threading.Thread(
            target=generate_subtitles_func, args=(record_name, subs_file_path)
        )
        create_var[subs_thread_name].daemon = True
        create_var[subs_thread_name].start()
    
    try:
        flv_url = port_info.get('flv_url')
        if flv_url:
            recording.add(record_name)
            start_record_time = datetime.datetime.now()
            recording_time_list[record_name] = [start_record_time, record_quality_zh]
            
            download_success = direct_download_stream_func(flv_url, save_file_path, record_name, record_url, platform)
            if download_success:
                print(f"\n{anchor_name} {time.strftime('%Y-%m-%d %H:%M:%S')} 直播录制完成\n")
            recording.discard(record_name)
        else:
            logger.debug("未找到FLV直播流，跳过录制")
    except Exception as e:
        color_obj.print_colored(f"\n{anchor_name} {time.strftime('%Y-%m-%d %H:%M:%S')} 直播录制出错,请检查网络\n", color_obj.RED)
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        with max_request_lock:
            error_count_ref[0] += 1
            error_window.append(1)
    return False


def _record_flv(anchor_name, title_in_name, now, full_path, split_video_by_time, split_time,
                converts_to_mp4, delete_origin_file, ffmpeg_command, record_name, record_url,
                custom_script, check_subprocess_func, segment_video_func, converts_mp4_func,
                max_request_lock, error_count_ref, error_window, logger):
    """录制 FLV 格式"""
    filename = anchor_name + f'_{title_in_name}' + now + ".flv"
    print(f'{full_path}/{filename}')
    save_file_path = full_path + '/' + filename
    
    try:
        if split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}_%03d.flv"
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
                      "-f", "segment", "-segment_time", split_time, "-segment_format", "flv",
                      "-reset_timestamps", "1", save_file_path]
        else:
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
                      "-f", "flv", "{path}".format(path=save_file_path)]
        
        ffmpeg_command.extend(command)
        comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, "FLV", custom_script)
        if comment_end:
            return True
        
        # 转换 MP4
        if converts_to_mp4:
            seg_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}_%03d.mp4"
            if split_video_by_time:
                segment_video_func(save_file_path, seg_file_path, segment_format='mp4',
                                  segment_time=split_time, is_original_delete=delete_origin_file)
            else:
                t = threading.Thread(target=converts_mp4_func, args=(save_file_path, delete_origin_file))
                t.daemon = False
                t.start()
                logger.info(f"[fix-2026-07-04] 分段时间触发转换: {save_file_path} (daemon=False)")
    except subprocess.CalledProcessError as e:
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        with max_request_lock:
            error_count_ref[0] += 1
            error_window.append(1)
    except Exception as e:
        logger.error(f"转码失败: {e}")
    return False


def _record_mkv(anchor_name, title_in_name, now, full_path, split_video_by_time, split_time,
                ffmpeg_command, record_name, record_url, custom_script, check_subprocess_func,
                max_request_lock, error_count_ref, error_window, logger):
    """录制 MKV 格式"""
    filename = anchor_name + f'_{title_in_name}' + now + ".mkv"
    print(f'{full_path}/{filename}')
    save_file_path = full_path + '/' + filename
    
    try:
        if split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}_%03d.mkv"
            command = ["-flags", "global_header", "-c:v", "copy", "-c:a", "aac", "-map", "0",
                      "-f", "segment", "-segment_time", split_time, "-segment_format", "matroska",
                      "-reset_timestamps", "1", save_file_path]
        else:
            command = ["-flags", "global_header", "-map", "0", "-c:v", "copy", "-c:a", "copy",
                      "-f", "matroska", "{path}".format(path=save_file_path)]
        
        ffmpeg_command.extend(command)
        comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, "MKV", custom_script)
        return comment_end
    except subprocess.CalledProcessError as e:
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        with max_request_lock:
            error_count_ref[0] += 1
            error_window.append(1)
    return False


def _record_mp4(anchor_name, title_in_name, now, full_path, split_video_by_time, split_time,
                ffmpeg_command, record_name, record_url, custom_script, check_subprocess_func,
                max_request_lock, error_count_ref, error_window, logger):
    """录制 MP4 格式"""
    filename = anchor_name + f'_{title_in_name}' + now + ".mp4"
    print(f'{full_path}/{filename}')
    save_file_path = full_path + '/' + filename
    
    try:
        if split_video_by_time:
            now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
            save_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}_%03d.mp4"
            command = ["-c:v", "copy", "-c:a", "aac", "-map", "0", "-f", "segment",
                      "-segment_time", split_time, "-segment_format", "mp4",
                      "-reset_timestamps", "1", "-movflags", "+frag_keyframe+empty_moov",
                      save_file_path]
        else:
            command = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-f", "mp4", save_file_path]
        
        ffmpeg_command.extend(command)
        comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, "MP4", custom_script)
        return comment_end
    except subprocess.CalledProcessError as e:
        logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
        with max_request_lock:
            error_count_ref[0] += 1
            error_window.append(1)
    return False


def _record_ts(anchor_name, title_in_name, now, full_path, split_video_by_time, split_time,
               converts_to_mp4, delete_origin_file, ffmpeg_command, record_name, record_url,
               custom_script, check_subprocess_func, converts_mp4_func, max_request_lock,
               error_count_ref, error_window, logger):
    """录制 TS 格式"""
    if split_video_by_time:
        now = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        filename = anchor_name + f'_{title_in_name}' + now + ".ts"
        print(f'{full_path}/{filename}')
        
        try:
            save_file_path = f"{full_path}/{anchor_name}_{title_in_name}{now}_%03d.ts"
            command = ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-f", "segment",
                      "-segment_time", split_time, "-segment_format", 'mpegts',
                      "-reset_timestamps", "1", save_file_path]
            
            ffmpeg_command.extend(command)
            comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, "TS", custom_script)
            if comment_end:
                if converts_to_mp4:
                    file_paths = utils.get_file_paths(os.path.dirname(save_file_path))
                    prefix = os.path.basename(save_file_path).rsplit('_', maxsplit=1)[0]
                    for path in file_paths:
                        if prefix in path:
                            try:
                                logger.info(f"[fix-2026-07-04] 同步转换(注释触发): {path} (delete_origin={delete_origin_file})")
                                converts_mp4_func(path, delete_origin_file)
                            except Exception as e:
                                logger.error(f"转码失败: {path} - {e}")
                return True
        except subprocess.CalledProcessError as e:
            logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
            with max_request_lock:
                error_count_ref[0] += 1
                error_window.append(1)
    else:
        filename = anchor_name + f'_{title_in_name}' + now + ".ts"
        print(f'{full_path}/{filename}')
        save_file_path = full_path + '/' + filename
        
        try:
            command = ["-c:v", "copy", "-c:a", "copy", "-map", "0", "-f", "mpegts", save_file_path]
            ffmpeg_command.extend(command)
            comment_end = check_subprocess_func(record_name, record_url, ffmpeg_command, "TS", custom_script)
            if comment_end:
                try:
                    logger.info(f"[fix-2026-07-04] 同步转换(单段结束): {save_file_path} (delete_origin={delete_origin_file})")
                    converts_mp4_func(save_file_path, delete_origin_file)
                except Exception as e:
                    logger.error(f"转码失败: {save_file_path} - {e}")
                return True
        except subprocess.CalledProcessError as e:
            logger.error(f"错误信息: {e} 发生错误的行数: {e.__traceback__.tb_lineno}")
            with max_request_lock:
                error_count_ref[0] += 1
                error_window.append(1)
    
    return False
