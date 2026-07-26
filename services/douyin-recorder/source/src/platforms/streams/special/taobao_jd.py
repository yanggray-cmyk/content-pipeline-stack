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
def _taobao_build_params(live_id: str) -> dict:
    """构建 mtop API 请求参数"""
    return {
        'jsv': '2.7.0',
        'appKey': '12574478',
        't': '1733104933120',
        'sign': '',
        'AntiFlood': 'true',
        'AntiCreep': 'true',
        'api': 'mtop.mediaplatform.live.livedetail',
        'v': '4.0',
        'preventFallback': 'true',
        'type': 'jsonp',
        'dataType': 'jsonp',
        'callback': 'mtopjsonp1',
        'data': '{"liveId":"' + live_id + '","creatorId":null}',
    }


async def _taobao_sign_and_fetch(params: dict, headers: dict, proxy_addr: OptionalStr) -> tuple:
    """生成 mtop 签名并请求 API，返回 (json_data, new_cookie)"""
    app_key = '12574478'
    _m_h5_tk = re.findall('_m_h5_tk=(.*?);', headers['Cookie'])[0]
    t13 = int(time.time() * 1000)
    pre_sign_str = f'{_m_h5_tk.split("_")[0]}&{t13}&{app_key}&' + params['data']
    sign = execjs.compile(open(f'{JS_SCRIPT_PATH}/taobao-sign.js').read()).call('sign', pre_sign_str)
    params |= {'sign': sign, 't': t13}
    api = f'https://h5api.m.taobao.com/h5/mtop.mediaplatform.live.livedetail/4.0/?{urllib.parse.urlencode(params)}'
    jsonp_str, new_cookie = await async_req(url=api, proxy_addr=proxy_addr, headers=headers, timeout=20,
                                            return_cookies=True, include_cookies=True)
    return utils.jsonp_to_json(jsonp_str), new_cookie


def _taobao_parse_result(json_data: dict, live_id: str) -> dict:
    """解析直播详情，按清晰度降序排序播放列表"""
    anchor_name = json_data['data']['broadCaster']['accountName']
    result = {"anchor_name": anchor_name, "is_live": False}
    if json_data['data']['streamStatus'] == '1':
        definition_priority = {"lld": 0, "ld": 1, "md": 2, "hd": 3, "ud": 4}
        play_url_list = sorted(
            json_data['data']['liveUrlList'],
            key=lambda item: definition_priority.get(item.get('definition') or item.get('newDefinition'), -1),
            reverse=True
        )
        result |= {"is_live": True, "title": json_data['data']['title'],
                   "play_url_list": play_url_list, 'live_id': live_id}
    return result


async def get_taobao_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Referer': 'https://huodong.m.taobao.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Cookie': '',
    }

    if cookies:
        headers['Cookie'] = cookies

    if '_m_h5_tk' not in headers['Cookie']:
        print('Error: Cookies is empty! please input correct cookies')

    live_id = get_params(url, 'id')
    if not live_id:
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers)
        redirect_url = re.findall("var url = '(.*?)';", html_str)[0]
        live_id = get_params(redirect_url, 'id')

    params = _taobao_build_params(live_id)

    for i in range(2):
        json_data, new_cookie = await _taobao_sign_and_fetch(params, headers, proxy_addr)

        ret_msg = json_data['ret']
        if ret_msg == ['SUCCESS::调用成功']:
            return _taobao_parse_result(json_data, live_id)
        else:
            print(f'Error: Taobao live data fetch failed, {ret_msg[0]}')

        if '_m_h5_tk' in new_cookie and '_m_h5_tk_enc' in new_cookie:
            headers['Cookie'] = re.sub('_m_h5_tk=(.*?);', new_cookie['_m_h5_tk'], headers['Cookie'])
            headers['Cookie'] = re.sub('_m_h5_tk_enc=(.*?);', new_cookie['_m_h5_tk_enc'], headers['Cookie'])
        else:
            print('Error: Try to update cookie failed, please update the cookies in the configuration file')


@trace_error_decorator
async def get_jd_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'origin': 'https://lives.jd.com',
        'referer': 'https://lives.jd.com/',
        'x-referer-page': 'https://lives.jd.com/',
    }

    if cookies:
        headers['Cookie'] = cookies

    redirect_url = await async_req(url, proxy_addr=proxy_addr, headers=headers, redirect_url=True)
    author_id = get_params(redirect_url, 'authorId')
    result = {"anchor_name": '', "is_live": False}
    if not author_id:
        live_id = re.search('#/(.*?)\\?origin', redirect_url)
        if not live_id:
            return result
        live_id = live_id.group(1)
        result['anchor_name'] = f'jd_{live_id}'
    else:
        data = {
            'functionId': 'talent_head_findTalentMsg',
            'appid': 'dr_detail',
            'body': '{"authorId":"' + author_id + '","monitorSource":"1","userId":""}',
        }
        info_api = 'https://api.m.jd.com/talent_head_findTalentMsg'
        json_str = await async_req(info_api, data=data, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        anchor_name = json_data['result']['talentName']
        result['anchor_name'] = anchor_name
        if 'livingRoomJump' not in json_data['result']:
            return result
        live_id = json_data['result']['livingRoomJump']['params']['id']
    params = {
        "body": '{"liveId": "' + live_id + '"}',
        "functionId": "getImmediatePlayToM",
        "appid": "h5-live"
    }

    api = f'https://api.m.jd.com/client.action?{urllib.parse.urlencode(params)}'
    # backup_api: https://api.m.jd.com/api
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    live_status = json_data['data']['status']
    if live_status == 1:
        if author_id:
            data = {
                'functionId': 'jdTalentContentList',
                'appid': 'dr_detail',
                'body': '{"authorId":"' + author_id + '","type":1,"userId":"","page":1,"offset":"-1",'
                                                      '"monitorSource":"1","pageSize":1}',
            }
            json_str2 = await async_req('https://api.m.jd.com/jdTalentContentList', data=data,
                                proxy_addr=proxy_addr, headers=headers)
            json_data2 = json.loads(json_str2)
            result['title'] = json_data2['result']['content'][0]['title']

        flv_url = json_data['data']['videoUrl']
        m3u8_url = json_data['data']['h5VideoUrl']
        result |= {"is_live": True, "m3u8_url": m3u8_url, "flv_url": flv_url, "record_url": m3u8_url}
    return result

