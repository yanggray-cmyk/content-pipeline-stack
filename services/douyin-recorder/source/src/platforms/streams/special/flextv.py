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
async def login_flextv(username: str, password: str, proxy_addr: OptionalStr = None) -> OptionalStr:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'content-type': 'application/json;charset=UTF-8',
        'referer': 'https://www.ttinglive.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }

    data = {
        'loginId': username,
        'password': password,
        'loginKeep': True,
        'saveId': True,
        'device': 'PCWEB',
    }

    url = 'https://www.ttinglive.com/v2/api/auth/signin'

    try:
        print("Logging into FlexTV platform...")
        cookie_dict = await async_req(url, proxy_addr=proxy_addr, headers=headers, json_data=data,
                                      return_cookies=True, timeout=20)

        if cookie_dict and 'flx_oauth_access' in cookie_dict:
            cookie_str = '; '.join([f"{k}={v}" for k, v in cookie_dict.items()])
            return cookie_str
        else:
            print("Please check if the FlexTV account and password in the configuration file are correct.")
            return None

    except Exception as e:
        print(f"FlexTV login request exception: {e}")
        raise Exception(
            "FlexTV login failed, please check if the account and password in the configuration file are correct."
        )


async def get_flextv_stream_url(
        url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None
) -> str:
    async def fetch_data(cookie) -> dict:
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'referer': 'https://www.ttinglive.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        }
        user_id = url.split('/live')[0].rsplit('/', maxsplit=1)[-1]
        if cookie:
            headers['Cookie'] = cookie
        play_api = f'https://www.ttinglive.com/api/channels/{user_id}/stream?option=all'
        json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers, abroad=True)
        if 'HTTP Error 400: Bad Request' in json_str:
            raise ConnectionError(
                "Failed to retrieve FlexTV live streaming data, please switch to a different proxy and try again."
            )
        return json.loads(json_str)

    json_data = await fetch_data(cookies)
    if 'sources' in json_data and len(json_data['sources']) > 0:
        play_url = json_data['sources'][0]['url']
        return play_url


@trace_error_decorator
async def get_flextv_stream_data(
        url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None,
        username: OptionalStr = None, password: OptionalStr = None
) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://www.ttinglive.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies
    user_id = url.split('/live')[0].rsplit('/', maxsplit=1)[-1]
    result = {"anchor_name": '', "is_live": False}
    new_cookies = None
    try:
        url2 = f'https://www.ttinglive.com/channels/{user_id}/live'
        html_str = await async_req(url2, proxy_addr=proxy_addr, headers=headers, abroad=True)
        json_str = re.search('<script id="__NEXT_DATA__" type=".*">(.*?)</script>', html_str).group(1)
        json_data = json.loads(json_str)
        channel_data = json_data['props']['pageProps']['channel']
        login_need = 'message' in channel_data and '로그인후 이용이 가능합니다.' in channel_data.get('message')
        if login_need:
            print("FlexTV live stream retrieval failed [not logged in]: 19+ live streams are only available for "
                  "logged-in adults.")
            print("Attempting to log in to the FlexTV live streaming platform, please ensure your account and "
                  "password are correctly filled in the configuration file.")
            if len(username) < 6 or len(password) < 8:
                raise RuntimeError("FlexTV登录失败！请在config.ini配置文件中填写正确的FlexTV平台的账号和密码")
            new_cookies = await login_flextv(username, password, proxy_addr=proxy_addr)
            if new_cookies:
                print("Logged into FlexTV platform successfully! Starting to fetch live streaming data...")
            else:
                raise RuntimeError("FlexTV login failed")
            cookies = new_cookies if new_cookies else cookies
            headers['Cookie'] = cookies
            html_str = await async_req(url2, proxy_addr=proxy_addr, headers=headers, abroad=True)
            json_str = re.search('<script id="__NEXT_DATA__" type=".*">(.*?)</script>', html_str).group(1)
            json_data = json.loads(json_str)
            channel_data = json_data['props']['pageProps']['channel']

        live_status = 'message' not in channel_data
        if live_status:
            anchor_id = channel_data['owner']['loginId']
            anchor_name = f"{channel_data['owner']['nickname']}-{anchor_id}"
            result["anchor_name"] = anchor_name
            play_url = await get_flextv_stream_url(url=url, proxy_addr=proxy_addr, cookies=cookies)
            if play_url:
                result['is_live'] = True
                if '.m3u8' in play_url:
                    play_url_list = await get_play_url_list(m3u8=play_url, proxy=proxy_addr, header=headers, abroad=True)
                    if play_url_list:
                        result['m3u8_url'] = play_url
                        result['play_url_list'] = play_url_list
                else:
                    result['flv_url'] = play_url
                    result['record_url'] = play_url
        else:
            url2 = f'https://www.ttinglive.com/channels/{user_id}'
            html_str = await async_req(url2, proxy_addr=proxy_addr, headers=headers, abroad=True)
            anchor_name = re.search('<meta name="twitter:title" content="(.*?)의', html_str).group(1)
            result["anchor_name"] = anchor_name
    except Exception as e:
        print("Failed to retrieve data from FlexTV live room", e)
    result['new_cookies'] = new_cookies
    return result

