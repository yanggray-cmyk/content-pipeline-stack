# -*- encoding: utf-8 -*-

"""FFmpeg 命令构建"""

from typing import List, Optional, Dict, Any


def build_ffmpeg_command(
    real_url: str,
    proxy_address: Optional[str],
    platform: str,
    record_url: str,
    overseas_platform_host: list,
    headers: Optional[List[str]] = None
) -> List[str]:
    """
    构建 ffmpeg 录制命令
    
    Args:
        real_url: 实际录制 URL
        proxy_address: 代理地址
        platform: 平台名称
        record_url: 原始 URL
        overseas_platform_host: 海外平台 host 列表
        headers: 自定义 headers
        
    Returns:
        ffmpeg 命令列表
    """
    user_agent = ("Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) AppleWebKit/537.36 ("
                  "KHTML, like Gecko) SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile "
                  "Safari/537.36")

    rw_timeout = "15000000"
    analyzeduration = "20000000"
    probesize = "10000000"
    bufsize = "8000k"
    max_muxing_queue_size = "1024"
    
    # 海外平台使用更大的超时和缓冲
    for pt_host in overseas_platform_host:
        if pt_host in record_url:
            rw_timeout = "50000000"
            analyzeduration = "40000000"
            probesize = "20000000"
            bufsize = "15000k"
            max_muxing_queue_size = "2048"
            break

    ffmpeg_command = [
        'ffmpeg', "-y",
        "-v", "verbose",
        "-rw_timeout", rw_timeout,
        "-loglevel", "error",
        "-hide_banner",
        "-user_agent", user_agent,
        "-protocol_whitelist", "rtmp,crypto,file,http,https,tcp,tls,udp,rtp,httpproxy",
        "-thread_queue_size", "1024",
        "-analyzeduration", analyzeduration,
        "-probesize", probesize,
        "-fflags", "+discardcorrupt",
        "-re", "-i", real_url,
        "-bufsize", bufsize,
        "-sn", "-dn",
        "-reconnect_delay_max", "60",
        "-reconnect_streamed", "-reconnect_at_eof",
        "-max_muxing_queue_size", max_muxing_queue_size,
        "-correct_ts_overflow", "1",
        "-avoid_negative_ts", "1"
    ]

    # 插入 headers
    if headers:
        ffmpeg_command.insert(11, "-headers")
        ffmpeg_command.insert(12, headers)

    # 插入代理
    if proxy_address:
        ffmpeg_command.insert(1, "-http_proxy")
        ffmpeg_command.insert(2, proxy_address)

    return ffmpeg_command
