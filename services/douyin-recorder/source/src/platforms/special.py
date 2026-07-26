# -*- encoding: utf-8 -*-

"""
特殊平台策略（需要额外逻辑）
"""

import asyncio
from typing import Any, Dict, List, Optional
import uuid

from .base import PlatformStrategy
from src.utils import logger
from src import utils


class DouyinStrategy(PlatformStrategy):
    """抖音直播（web/app 两种 URL）"""
    
    @property
    def name(self) -> str:
        return '抖音直播'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['douyin.com/']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        dy_cookie = context.get('dy_cookie', '')
        
        with semaphore:
            if 'v.douyin.com' not in url and '/user/' not in url:
                json_data = await spider.get_douyin_web_stream_data(
                    url=url, proxy_addr=proxy, cookies=dy_cookie)
            else:
                json_data = await spider.get_douyin_app_stream_data(
                    url=url, proxy_addr=proxy, cookies=dy_cookie)
            
            port_info = await stream.get_douyin_stream_url(json_data, quality, proxy)
        
        return port_info


class HuyaStrategy(PlatformStrategy):
    """虎牙直播（高清走 app）"""
    
    @property
    def name(self) -> str:
        return '虎牙直播'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['https://www.huya.com/']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        hy_cookie = context.get('hy_cookie', '')
        
        with semaphore:
            if quality in ['OD', 'BD', 'UHD']:
                port_info = await spider.get_huya_app_stream_url(
                    url=url, proxy_addr=proxy, cookies=hy_cookie)
            else:
                json_data = await spider.get_huya_stream_data(
                    url=url, proxy_addr=proxy, cookies=hy_cookie)
                port_info = await stream.get_huya_stream_url(json_data, quality)
        
        return port_info


class SOOPStrategy(PlatformStrategy):
    """SOOP 直播（韩国，需要登录）"""
    
    @property
    def name(self) -> str:
        return 'SOOP'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['sooplive.co.kr/', 'sooplive.com/']
    
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
            logger.error("错误信息: 网络异常，无法访问SOOP平台")
            return None
        
        sooplive_cookie = context.get('sooplive_cookie', '')
        sooplive_username = context.get('sooplive_username', '')
        sooplive_password = context.get('sooplive_password', '')
        config_file = context.get('config_file', '')
        
        with semaphore:
            json_data = await spider.get_sooplive_stream_data(
                url=url, proxy_addr=proxy, cookies=sooplive_cookie,
                username=sooplive_username, password=sooplive_password)
            
            if json_data and json_data.get('new_cookies'):
                utils.update_config(config_file, 'Cookie', 'sooplive_cookie', json_data['new_cookies'])
            
            port_info = await stream.get_stream_url(json_data, quality, spec=True)
        
        return port_info


class FlexTVStrategy(PlatformStrategy):
    """FlexTV（韩国，需要登录）"""
    
    @property
    def name(self) -> str:
        return 'FlexTV'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['www.flextv.co.kr/', 'www.ttinglive.com/']
    
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
            logger.error("错误信息: 网络异常，无法访问FlexTV")
            return None
        
        flextv_cookie = context.get('flextv_cookie', '')
        flextv_username = context.get('flextv_username', '')
        flextv_password = context.get('flextv_password', '')
        config_file = context.get('config_file', '')
        
        with semaphore:
            json_data = await spider.get_flextv_stream_data(
                url=url, proxy_addr=proxy, cookies=flextv_cookie,
                username=flextv_username, password=flextv_password)
            
            if json_data and json_data.get('new_cookies'):
                utils.update_config(config_file, 'Cookie', 'flextv_cookie', json_data['new_cookies'])
            
            if 'play_url_list' in json_data:
                port_info = await stream.get_stream_url(json_data, quality, spec=True)
            else:
                port_info = json_data
        
        return port_info


class PopkonTVStrategy(PlatformStrategy):
    """PopkonTV（韩国，需要登录+token）"""
    
    @property
    def name(self) -> str:
        return 'PopkonTV'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['www.popkontv.com/']
    
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
        from src import spider
        
        global_proxy = context.get('global_proxy', False)
        if not (global_proxy or proxy):
            logger.error("错误信息: 网络异常，无法访问PopkonTV")
            return None
        
        popkontv_cookie = context.get('popkontv_cookie', '')
        popkontv_username = context.get('popkontv_username', '')
        popkontv_password = context.get('popkontv_password', '')
        popkontv_partner_code = context.get('popkontv_partner_code', '')
        config_file = context.get('config_file', '')
        
        with semaphore:
            port_info = await spider.get_popkontv_stream_url(
                url=url, proxy_addr=proxy, cookies=popkontv_cookie,
                username=popkontv_username, password=popkontv_password,
                partner_code=popkontv_partner_code)
            
            if port_info and port_info.get('new_token'):
                utils.update_config(config_file, 'Authorization', 'popkontv_token', port_info['new_token'])
        
        return port_info


class TwitCastingStrategy(PlatformStrategy):
    """TwitCasting（需要登录）"""
    
    @property
    def name(self) -> str:
        return 'TwitCasting'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['twitcasting.tv/']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        twitcasting_cookie = context.get('twitcasting_cookie', '')
        twitcasting_account_type = context.get('twitcasting_account_type', '')
        twitcasting_username = context.get('twitcasting_username', '')
        twitcasting_password = context.get('twitcasting_password', '')
        config_file = context.get('config_file', '')
        
        with semaphore:
            json_data = await spider.get_twitcasting_stream_url(
                url=url, proxy_addr=proxy, cookies=twitcasting_cookie,
                account_type=twitcasting_account_type,
                username=twitcasting_username, password=twitcasting_password)
            
            port_info = await stream.get_stream_url(json_data, quality, spec=False)
            
            if port_info and port_info.get('new_cookies'):
                utils.update_config(config_file, 'Cookie', 'twitcasting_cookie', port_info['new_cookies'])
        
        return port_info


class ShopeeStrategy(PlatformStrategy):
    """Shopee（需要拼接 uid）"""
    
    @property
    def name(self) -> str:
        return 'shopee'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['live.shopee', 'shp.ee/']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider
        
        shopee_cookie = context.get('shopee_cookie', '')
        
        with semaphore:
            port_info = await spider.get_shopee_stream_url(
                url=url, proxy_addr=proxy, cookies=shopee_cookie)
            
            if port_info and 'uid' in port_info:
                port_info['record_url'] = f"{url}?uid={port_info['uid']}"
        
        return port_info


class TaobaoStrategy(PlatformStrategy):
    """淘宝直播"""
    
    @property
    def name(self) -> str:
        return '淘宝直播'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['tb.cn']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        taobao_cookie = context.get('taobao_cookie', '')
        
        with semaphore:
            json_data = await spider.get_taobao_stream_url(
                url=url, proxy_addr=proxy, cookies=taobao_cookie)
            port_info = await stream.get_stream_url(
                json_data, quality, url_type='all', 
                hls_extra_key='hlsUrl', flv_extra_key='flvUrl')
        
        return port_info


class CustomStrategy(PlatformStrategy):
    """自定义录制（.m3u8/.flv 直链）"""
    
    @property
    def name(self) -> str:
        return '自定义录制直播'
    
    @property
    def url_patterns(self) -> List[str]:
        return ['.m3u8', '.flv']
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        port_info = {
            "anchor_name": self.name + '_' + str(uuid.uuid4())[:8],
            "is_live": True,
            "record_url": url,
        }
        
        if '.flv' in url:
            port_info['flv_url'] = url
        else:
            port_info['m3u8_url'] = url
        
        return port_info
