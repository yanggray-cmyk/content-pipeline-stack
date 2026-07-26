# -*- encoding: utf-8 -*-

"""
海外平台策略（需要代理）
"""

import asyncio
from typing import Any, Dict, Optional

from .base import PlatformStrategy
from src.utils import logger


class SimpleOverseasPlatform(PlatformStrategy):
    """简单海外平台（通用实现）"""
    
    def __init__(
        self,
        name: str,
        url_patterns: list,
        spider_func: str,
        stream_func: Optional[str] = None,
        cookie_key: str = ''
    ):
        self._name = name
        self._url_patterns = url_patterns
        self._spider_func = spider_func
        self._stream_func = stream_func
        self._cookie_key = cookie_key
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def url_patterns(self) -> list:
        return self._url_patterns
    
    @property
    def requires_proxy(self) -> bool:
        return True
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        global_proxy = context.get('global_proxy', False)
        
        if not (global_proxy or proxy):
            logger.error(f"错误信息: 网络异常，无法访问{self._name}")
            return None
        
        cookie = context.get(self._cookie_key, '') if self._cookie_key else ''
        
        with semaphore:
            spider_func = getattr(spider, self._spider_func)
            
            if self._stream_func:
                json_data = await spider_func(url=url, proxy_addr=proxy, cookies=cookie)
                stream_func = getattr(stream, self._stream_func)
                port_info = await stream_func(json_data, quality, spec=True)
            else:
                port_info = await spider_func(url=url, proxy_addr=proxy, cookies=cookie)
        
        return port_info


# 海外平台列表
OVERSEAS_PLATFORMS = [
    SimpleOverseasPlatform('TikTok直播', ['https://www.tiktok.com/'],
                          'get_tiktok_stream_data', 'get_tiktok_stream_url', 'tiktok_cookie'),
    SimpleOverseasPlatform('PandaTV', ['www.pandalive.co.kr/'],
                          'get_pandatv_stream_data', 'get_stream_url', 'pandatv_cookie'),
    SimpleOverseasPlatform('WinkTV', ['www.winktv.co.kr/'],
                          'get_winktv_stream_data', 'get_stream_url', 'winktv_cookie'),
    SimpleOverseasPlatform('TwitchTV', ['www.twitch.tv/'],
                          'get_twitchtv_stream_data', 'get_stream_url', 'twitch_cookie'),
    SimpleOverseasPlatform('LiveMe', ['www.liveme.com/'],
                          'get_liveme_stream_url', None, 'liveme_cookie'),
    SimpleOverseasPlatform('Youtube', ['www.youtube.com/', 'youtu.be/'],
                          'get_youtube_stream_url', 'get_stream_url', 'youtube_cookie'),
    SimpleOverseasPlatform('faceit', ['faceit.com/'],
                          'get_faceit_stream_data', 'get_stream_url', 'faceit_cookie'),
]
