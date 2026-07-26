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
async def login_twitcasting(
        account_type: str, username: str, password: str, proxy_addr: OptionalStr = None,
        cookies: OptionalStr = None
) -> OptionalStr:
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://twitcasting.tv/indexcaslogin.php?redir=%2Findexloginwindow.php%3Fnext%3D%252F&keep=1',
        'Cookie': '',
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    if account_type == "twitter":
        login_url = 'https://twitcasting.tv/indexpasswordlogin.php'
        login_api = 'https://twitcasting.tv/indexpasswordlogin.php?redir=/indexloginwindow.php?next=%2F&keep=1'
    else:
        login_url = 'https://twitcasting.tv/indexcaslogin.php?redir=%2F&keep=1'
        login_api = 'https://twitcasting.tv/indexcaslogin.php?redir=/indexloginwindow.php?next=%2F&keep=1'

    html_str = await async_req(login_url, proxy_addr=proxy_addr, headers=headers)
    cs_session_id = re.search('<input type="hidden" name="cs_session_id" value="(.*?)">', html_str).group(1)

    data = {
        'username': username,
        'password': password,
        'action': 'login',
        'cs_session_id': cs_session_id,
    }
    try:
        cookie_dict = await async_req(login_api, proxy_addr=proxy_addr, headers=headers,
                                      data=data, return_cookies=True, timeout=20)
        if 'tc_ss' in cookie_dict:
            cookie = utils.dict_to_cookie_str(cookie_dict)
            return cookie
    except Exception as e:
        print("TwitCasting login error,", e)


@trace_error_decorator
async def get_twitcasting_stream_url(
        url: str,
        proxy_addr: OptionalStr = None,
        cookies: OptionalStr = None,
        account_type: OptionalStr = None,
        username: OptionalStr = None,
        password: OptionalStr = None,
) -> dict:
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Referer': 'https://twitcasting.tv/?ch0',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }

    anchor_id = url.split('/')[3]
    if cookies:
        headers['Cookie'] = cookies

    async def get_data(header) -> tuple:
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=header)
        anchor = re.search("<title>(.*?) \\(@(.*?)\\)  的直播 - Twit", html_str)
        title = re.search('<meta name="twitter:title" content="(.*?)">\n\\s+<meta', html_str)
        status = re.search('data-is-onlive="(.*?)"\n\\s+data-view-mode', html_str)
        movie_id = re.search('data-movie-id="(.*?)" data-audience-id', html_str)
        return f'{anchor.group(1).strip()}-{anchor.group(2)}-{movie_id.group(1)}', status.group(1), title.group(1)

    result = {"anchor_name": '', "is_live": False}
    new_cookie = None
    try:
        to_login = get_params(url, "login")
        if to_login == 'true':
            print("Attempting to log in to TwitCasting...")
            new_cookie = await login_twitcasting(
                account_type=account_type, username=username, password=password, proxy_addr=proxy_addr, cookies=cookies)
            if not new_cookie:
                raise RuntimeError("TwitCasting login failed, please check if the account password in the "
                                   "configuration file is correct")
            print("TwitCasting login successful! Starting to fetch data...")
            headers['Cookie'] = new_cookie
        anchor_name, live_status, live_title = await get_data(headers)
    except AttributeError:
        print("Failed to retrieve TwitCasting data, attempting to log in...")
        new_cookie = await login_twitcasting(
            account_type=account_type, username=username, password=password, proxy_addr=proxy_addr, cookies=cookies)
        if not new_cookie:
            raise RuntimeError("TwitCasting login failed, please check if the account and password in the "
                               "configuration file are correct")
        print("TwitCasting login successful! Starting to fetch data...")
        headers['Cookie'] = new_cookie
        anchor_name, live_status, live_title = await get_data(headers)

    result["anchor_name"] = anchor_name
    if live_status == 'true':
        url_streamserver = f"https://twitcasting.tv/streamserver.php?target={anchor_id}&mode=client&player=pc_web"
        stream_data = await async_req(url_streamserver, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(stream_data)
        if not json_data.get('tc-hls') or not json_data['tc-hls'].get("streams"):
            raise RuntimeError("No m3u8_url,please check the url")

        stream_dict = json_data['tc-hls']["streams"]
        quality_order = {"high": 0, "medium": 1, "low": 2}
        sorted_streams = sorted(stream_dict.items(), key=lambda item: quality_order[item[0]])
        play_url_list = [url for quality, url in sorted_streams]
        result |= {'title': live_title, 'is_live': True, "play_url_list": play_url_list}
    result['new_cookies'] = new_cookie
    return result

