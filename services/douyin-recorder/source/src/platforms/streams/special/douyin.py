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


async def _douyin_web_fetch_room_data(web_rid: str, proxy_addr: OptionalStr,
                                      headers: dict, url: str) -> dict:
    """请求抖音 Web 接口（含 a_bogus 签名）"""
    params = {
        "aid": "6383",
        "app_name": "douyin_web",
        "live_id": "1",
        "device_platform": "web",
        "language": "zh-CN",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "116.0.0.0",
        "web_rid": web_rid,
        'msToken': '',
    }
    api = f'https://live.douyin.com/webcast/room/web/enter/?{urllib.parse.urlencode(params)}'
    a_bogus = ab_sign(urllib.parse.urlparse(api).query, headers['user-agent'])
    api += "&a_bogus=" + a_bogus
    try:
        json_str = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
        if not json_str:
            raise Exception("it triggered risk control")
        json_data = json.loads(json_str)['data']
        if not json_data['data']:
            raise Exception(f"{url} VR live is not supported")
        room_data = json_data['data'][0]
        room_data['anchor_name'] = json_data['user']['nickname']
        return room_data
    except Exception as e:
        raise Exception(f"Douyin web data fetch error, because {e}.")


async def get_douyin_web_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None):
    headers = {
        'cookie': ''
                  '%7Cab35197d5cfb21df6cbb2fa7ef1c9262206b062c315b9d04da746d0b37dfbc7d',
        'referer': 'https://live.douyin.com/335354047186',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/116.0.5845.97 Safari/537.36 Core/1.116.567.400 QQBrowser/19.7.6764.400',
    }
    if cookies:
        headers['cookie'] = cookies

    try:
        web_rid = url.split('?')[0].split('live.douyin.com/')[-1]
        room_data = await _douyin_web_fetch_room_data(web_rid, proxy_addr, headers, url)

        if room_data['status'] == 2:
            if 'stream_url' not in room_data:
                raise RuntimeError(
                    "The live streaming type or gameplay is not supported on the computer side yet, please use the "
                    "app to share the link for recording."
                )
            _douyin_process_origin_stream(room_data)
    except Exception as e:
        print(f"Error message: {e} Error line: {e.__traceback__.tb_lineno}")
        room_data = {'anchor_name': ""}
    return room_data


@trace_error_decorator
async def _douyin_get_app_data(room_id: str, sec_uid: str, proxy_addr: OptionalStr,
                               headers: dict, url: str) -> dict:
    """请求抖音 APP 接口（含 a_bogus 签名）"""
    app_params = {
        "verifyFp": "verify_hwj52020_7szNlAB7_pxNY_48Vh_ALKF_GA1Uf3yteoOY",
        "type_id": "0",
        "live_id": "1",
        "room_id": room_id,
        "sec_user_id": sec_uid,
        "version_code": "99.99.99",
        "app_id": "1128"
    }
    api2 = f'https://webcast.amemv.com/webcast/room/reflow/info/?{urllib.parse.urlencode(app_params)}'
    a_bogus = ab_sign(urllib.parse.urlparse(api2).query, headers['User-Agent'])
    api2 += "&a_bogus=" + a_bogus
    try:
        json_str2 = await async_req(url=api2, proxy_addr=proxy_addr, headers=headers)
        if not json_str2:
            raise Exception("it triggered risk control")
        json_data2 = json.loads(json_str2)['data']
        if not json_data2.get('room'):
            raise Exception(f"{url} VR live is not supported")
        room_data2 = json_data2['room']
        room_data2['anchor_name'] = room_data2['owner']['nickname']
        return room_data2
    except Exception as e:
        raise Exception(f"Douyin app data fetch error, because {e}.")


def _douyin_process_origin_stream(room_data: dict) -> None:
    """处理 origin 原画质流（修改 room_data 中的 stream_url 映射）"""
    live_core_sdk_data = room_data['stream_url']['live_core_sdk_data']
    pull_datas = room_data['stream_url']['pull_datas']
    if not live_core_sdk_data:
        return
    if pull_datas:
        key = list(pull_datas.keys())[0]
        json_str = pull_datas[key]['stream_data']
    else:
        json_str = live_core_sdk_data['pull_data']['stream_data']
    json_data = json.loads(json_str)
    if 'origin' not in json_data['data']:
        return

    stream_data = live_core_sdk_data['pull_data']['stream_data']
    origin_data = json.loads(stream_data)['data']['origin']['main']
    sdk_params = json.loads(origin_data['sdk_params'])
    origin_hls_codec = sdk_params.get('VCodec') or ''

    origin_url_list = json_data['data']['origin']['main']
    origin_m3u8 = {'ORIGIN': origin_url_list["hls"] + '&codec=' + origin_hls_codec}
    origin_flv = {'ORIGIN': origin_url_list["flv"] + '&codec=' + origin_hls_codec}
    hls_pull_url_map = room_data['stream_url']['hls_pull_url_map']
    flv_pull_url = room_data['stream_url']['flv_pull_url']
    room_data['stream_url']['hls_pull_url_map'] = {**origin_m3u8, **hls_pull_url_map}
    room_data['stream_url']['flv_pull_url'] = {**origin_flv, **flv_pull_url}


async def get_douyin_app_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://live.douyin.com/',
        'Cookie': ''
    }
    if cookies:
        headers['Cookie'] = cookies

    try:
        web_rid = url.split('?')[0].split('live.douyin.com/')
        if len(web_rid) > 1:
            return await get_douyin_web_stream_data(url, proxy_addr, cookies)

        try:
            data = await get_sec_user_id(url, proxy_addr=proxy_addr)
            _room_id, _sec_uid = data
            room_data = await _douyin_get_app_data(_room_id, _sec_uid, proxy_addr, headers, url)
        except UnsupportedUrlError:
            unique_id = await get_unique_id(url, proxy_addr=proxy_addr)
            return await get_douyin_stream_data(f'https://live.douyin.com/{unique_id}')

        if room_data['status'] == 2:
            if 'stream_url' not in room_data:
                raise RuntimeError(
                    "The live streaming type or gameplay is not supported on the computer side yet, please use the "
                    "app to share the link for recording."
                )
            _douyin_process_origin_stream(room_data)
    except Exception as e:
        print(f"Error message: {e} Error line: {e.__traceback__.tb_lineno}")
        room_data = {'anchor_name': ""}
    return room_data


@trace_error_decorator
async def get_douyin_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://live.douyin.com/',
        'Cookie': ''
    }
    if cookies:
        headers['Cookie'] = cookies

    try:
        origin_url_list = None
        html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
        match_json_str = re.search(r'(\{\\"state\\":.*?)]\\n"]\)', html_str)
        if not match_json_str:
            match_json_str = re.search(r'(\{\\"common\\":.*?)]\\n"]\)</script><div hidden', html_str)
        json_str = match_json_str.group(1)
        cleaned_string = json_str.replace('\\', '').replace(r'u0026', r'&')
        room_store = re.search('"roomStore":(.*?),"linkmicStore"', cleaned_string, re.DOTALL).group(1)
        anchor_name = re.search('"nickname":"(.*?)","avatar_thumb', room_store, re.DOTALL).group(1)
        room_store = room_store.split(',"has_commerce_goods"')[0] + '}}}'
        json_data = json.loads(room_store)['roomInfo']['room']
        json_data['anchor_name'] = anchor_name
        if 'status' in json_data and json_data['status'] == 4:
            return json_data
        stream_orientation = json_data['stream_url']['stream_orientation']
        match_json_str2 = re.findall(r'"(\{\\"common\\":.*?)"]\)</script><script nonce=', html_str)
        if match_json_str2:
            json_str = match_json_str2[0] if stream_orientation == 1 else match_json_str2[1]
            json_data2 = json.loads(
                json_str.replace('\\', '').replace('"{', '{').replace('}"', '}').replace('u0026', '&'))
            if 'origin' in json_data2['data']:
                origin_url_list = json_data2['data']['origin']['main']

        else:
            html_str = html_str.replace('\\', '').replace('u0026', '&')
            match_json_str3 = re.search('"origin":\\{"main":(.*?),"dash"', html_str, re.DOTALL)
            if match_json_str3:
                origin_url_list = json.loads(match_json_str3.group(1) + '}')

        if origin_url_list:
            origin_hls_codec = origin_url_list['sdk_params'].get('VCodec') or ''
            origin_m3u8 = {'ORIGIN': origin_url_list["hls"] + '&codec=' + origin_hls_codec}
            origin_flv = {'ORIGIN': origin_url_list["flv"] + '&codec=' + origin_hls_codec}
            hls_pull_url_map = json_data['stream_url']['hls_pull_url_map']
            flv_pull_url = json_data['stream_url']['flv_pull_url']
            json_data['stream_url']['hls_pull_url_map'] = {**origin_m3u8, **hls_pull_url_map}
            json_data['stream_url']['flv_pull_url'] = {**origin_flv, **flv_pull_url}
        return json_data

    except Exception as e:
        print(f"First data retrieval failed: {url} Preparing to switch parsing methods due to {e}")
        return await get_douyin_app_stream_data(url=url, proxy_addr=proxy_addr, cookies=cookies)

