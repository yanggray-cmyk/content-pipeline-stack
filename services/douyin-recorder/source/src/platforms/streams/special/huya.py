# -*- encoding: utf-8 -*-

"""特殊平台流媒体获取函数"""

import asyncio
import hashlib
import json
import random
import re
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid
from operator import itemgetter
from typing import List, Optional, Dict, Any

import execjs
import httpx
import ssl

from src import JS_SCRIPT_PATH, utils
from src.utils import trace_error_decorator, generate_random_string
from src.logger import script_path
from src.room import get_sec_user_id, get_unique_id, UnsupportedUrlError
from src.http_clients.async_http import async_req
from src.ab_sign import ab_sign

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
OptionalStr = str | None
OptionalDict = dict | None


@trace_error_decorator
async def get_huya_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Cookie': '',
    }
    if cookies:
        headers['Cookie'] = cookies

    html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    json_str = re.findall('stream: (\\{"data".*?),"iWebDefaultBitRate"', html_str)[0]
    json_data = json.loads(json_str + '}')
    return json_data


@trace_error_decorator
async def _huya_resolve_room_id(url: str, headers: dict, proxy_addr: OptionalStr) -> str:
    """解析虎牙房间 ID，字母别名需二次请求"""
    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    if any(char.isalpha() for char in room_id):
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers)
        match = re.search('ProfileRoom":(.*?),"sPrivateHost', html_str)
        if match:
            room_id = match.group(1)
        else:
            raise Exception('Please use "https://www.huya.com/+room_number" for recording')
    return room_id


def _huya_select_cdn_url(play_url_list: list) -> str:
    """按 CDN 优先级 (TX > HW > HS > AL) 选择 FLV 地址"""
    priority_order = ["TX", "HW", "HS", "AL"]
    selected_flv_url = None
    selected_cdn_type = None

    for cdn in priority_order:
        for item in play_url_list:
            if item["cdn_type"] == cdn:
                selected_flv_url = item["flv_url"]
                selected_cdn_type = cdn
                break
        if selected_flv_url:
            break

    if not selected_flv_url:
        return None

    flv_url = 'https://' + selected_flv_url.split('://')[1]
    if selected_cdn_type == "TX":
        flv_url = flv_url.replace("&ctype=tars_mp", "&ctype=huya_webh5").replace("&fs=bhct", "&fs=bgct")
    return flv_url


async def get_huya_app_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'xweb_xhr': '1',
        'referer': 'https://servicewechat.com/wx74767bf0b684f7d3/301/page-frame.html',
        'accept-language': 'zh-CN,zh;q=0.9',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = await _huya_resolve_room_id(url, headers, proxy_addr)

    params = {
        'm': 'Live',
        'do': 'profileRoom',
        'roomid': room_id,
        'showSecret': '1',
    }
    wx_app_api = f'https://mp.huya.com/cache.php?{urllib.parse.urlencode(params)}'
    json_str = await async_req(url=wx_app_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['profileInfo']['nick']
    live_status = json_data['data']['realLiveStatus']
    live_title = json_data['data']['liveData']['introduction']
    if live_status != 'ON':
        return {'anchor_name': anchor_name, 'is_live': False}

    base_steam_info_list = json_data['data']['stream']['baseSteamInfoList']
    play_url_list = []
    for i in base_steam_info_list:
        play_url_list.append(
            {
                'cdn_type': i['sCdnType'],
                'm3u8_url': f"{i['sHlsUrl']}/{i['sStreamName']}.m3u8?{i['sHlsAntiCode']}",
                'flv_url': f"{i['sFlvUrl']}/{i['sStreamName']}.flv?{i['sFlvAntiCode']}",
            }
        )

    return {
        'anchor_name': anchor_name,
        'is_live': True,
        'm3u8_url': play_url_list[0]['m3u8_url'],
        'flv_url': play_url_list[0]['flv_url'],
        'record_url': _huya_select_cdn_url(play_url_list),
        'title': live_title
    }

