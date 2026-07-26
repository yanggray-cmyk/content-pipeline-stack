# -*- encoding: utf-8 -*-

"""海外平台流媒体获取函数"""

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
async def get_tiktok_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict | None:
    headers = {
        'referer': 'https://www.tiktok.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/141.0.0.0 Safari/537.36',
        'cookie': cookies or ''
                             '5177d5d53bbd822e1bf66128887d942c9c3e2f'
    }

    for i in range(3):
        html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers, abroad=True, http2=False)
        time.sleep(1)
        if "We regret to inform you that we have discontinued operating TikTok" in html_str:
            msg = re.search('<p>\n\\s+(We regret to inform you that we have discontinu.*?)\\.\n\\s+</p>', html_str)
            raise ConnectionError(
                "Your proxy node's regional network is blocked from accessing TikTok; please switch to a node in "
                f"another region to access. {msg.group(1) if msg else ''}"
            )
        if 'UNEXPECTED_EOF_WHILE_READING' not in html_str:
            try:
                json_str = re.findall(
                    '<script id="SIGI_STATE" type="application/json">(.*?)</script>',
                    html_str, re.DOTALL)[0]
            except Exception:
                raise ConnectionError("Please check if your network can access the TikTok website normally")
            json_data = json.loads(json_str)
            return json_data


@trace_error_decorator
async def get_bigo_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Referer': 'https://www.bigo.tv/',
    }
    if cookies:
        headers['Cookie'] = cookies

    if 'bigo.tv' not in url:
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers)
        web_url = re.search(
            '<meta data-n-head="ssr" data-hid="al:web:url" property="al:web:url" content="(.*?)">',
            html_str).group(1)
        room_id = web_url.split('&amp;h=')[-1]
    else:
        if '&h=' in url:
            room_id = url.split('&h=')[-1]
        else:
            room_id = url.split("?")[0].rsplit("/", maxsplit=1)[-1]

    data = {'siteId': room_id}  # roomId
    url2 = 'https://ta.bigo.tv/official_website/studio/getInternalStudioInfo'
    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers, data=data)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['nick_name']
    live_status = json_data['data']['alive']
    result = {"anchor_name": anchor_name, "is_live": False}

    if live_status == 1:
        live_title = json_data['data']['roomTopic']
        m3u8_url = json_data['data']['hls_src']
        result['m3u8_url'] = m3u8_url
        result['record_url'] = m3u8_url
        result |= {"title": live_title, "is_live": True, "m3u8_url": m3u8_url, 'record_url': m3u8_url}
    elif result['anchor_name'] == '':
        html_str = await async_req(url=f'https://www.bigo.tv/{url.split("/")[3]}/{room_id}',
                                   proxy_addr=proxy_addr, headers=headers)
        match_anchor_name = re.search('<title>欢迎来到(.*?)的直播间</title>', html_str, re.DOTALL)
        if match_anchor_name:
            anchor_name = match_anchor_name.group(1)
        else:
            match_anchor_name = re.search('<meta data-n-head="ssr" data-hid="og:title" property="og:title" '
                                          'content="(.*?) - BIGO LIVE">', html_str, re.DOTALL)
            anchor_name = match_anchor_name.group(1)
        result['anchor_name'] = anchor_name

    return result


@trace_error_decorator
async def get_blued_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    }
    if cookies:
        headers['Cookie'] = cookies

    html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    json_str = re.search('decodeURIComponent\\(\"(.*?)\"\\)\\),window\\.Promise', html_str, re.DOTALL).group(1)
    json_str = urllib.parse.unquote(json_str)
    json_data = json.loads(json_str)
    anchor_name = json_data['userInfo']['name']
    live_status = json_data['userInfo']['onLive']
    result = {"anchor_name": anchor_name, "is_live": False}

    if live_status:
        m3u8_url = json_data['liveInfo']['liveUrl']
        result |= {"is_live": True, "m3u8_url": m3u8_url, 'record_url': m3u8_url}
    return result


@trace_error_decorator
async def get_pandatv_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'origin': 'https://www.pandalive.co.kr',
        'referer': 'https://www.pandalive.co.kr/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    user_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    url2 = 'https://api.pandalive.co.kr/v1/live/play'
    data = {
        'userId': user_id,
        'info': 'media fanGrade',
    }
    room_password = get_params(url, "pwd")
    if not room_password:
        room_password = ''
    data2 = {
        'action': 'watch',
        'userId': user_id,
        'password': room_password,
        'shareLinkType': '',
    }

    result = {"anchor_name": "", "is_live": False}
    json_str = await async_req('https://api.pandalive.co.kr/v1/member/bj',
                       proxy_addr=proxy_addr, headers=headers, data=data, abroad=True)
    json_data = json.loads(json_str)
    if "bjInfo" not in json_data:
        raise RuntimeError(json_data.get("message", 'Unknown error'))
    anchor_id = json_data['bjInfo']['id']
    anchor_name = f"{json_data['bjInfo']['nick']}-{anchor_id}"
    result['anchor_name'] = anchor_name
    live_status = 'media' in json_data

    if live_status:
        json_str = await async_req(url2, proxy_addr=proxy_addr, headers=headers, data=data2, abroad=True)
        json_data = json.loads(json_str)
        if 'errorData' in json_data:
            if json_data['errorData']['code'] == 'needAdult':
                raise RuntimeError(f"{url} The live room requires login and is only accessible to adults. Please "
                                   f"correctly fill in the login cookie in the configuration file.")
            else:
                raise RuntimeError(json_data['errorData']['code'], json_data['message'])
        play_url = json_data['PlayList']['hls'][0]['url']
        play_url_list = await get_play_url_list(m3u8=play_url, proxy=proxy_addr, header=headers, abroad=True)
        result |= {'is_live': True, 'm3u8_url': play_url, 'play_url_list': play_url_list}
    return result


@trace_error_decorator
async def get_winktv_bj_info(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> tuple:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'content-type': 'application/x-www-form-urlencoded',
        'referer': 'https://www.winktv.co.kr/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies
    user_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    data = {
        'userId': user_id,
        'info': 'media',
    }

    info_api = 'https://api.winktv.co.kr/v1/member/bj'
    json_str = await async_req(url=info_api, proxy_addr=proxy_addr, headers=headers, data=data, abroad=True)
    json_data = json.loads(json_str)
    live_status = 'media' in json_data
    anchor_id = json_data['bjInfo']['id']
    anchor_name = f"{json_data['bjInfo']['nick']}-{anchor_id}"
    return anchor_name, live_status


@trace_error_decorator
async def get_winktv_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'content-type': 'application/x-www-form-urlencoded',
        'referer': 'https://www.winktv.co.kr',
        'origin': 'https://www.winktv.co.kr',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',

    }
    if cookies:
        headers['Cookie'] = cookies
    user_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    room_password = get_params(url, "pwd")
    if not room_password:
        room_password = ''
    data = {
        'action': 'watch',
        'userId': user_id,
        'password': room_password,
        'shareLinkType': '',
    }

    anchor_name, live_status = await get_winktv_bj_info(url=url, proxy_addr=proxy_addr, cookies=cookies)
    result = {"anchor_name": anchor_name, "is_live": live_status}
    if live_status:
        play_api = 'https://api.winktv.co.kr/v1/live/play'
        json_str = await async_req(url=play_api, proxy_addr=proxy_addr, headers=headers, data=data, abroad=True)
        if '403: Forbidden' in json_str:
            raise ConnectionError(f"Your network has been banned from accessing WinkTV ({json_str})")
        json_data = json.loads(json_str)
        if 'errorData' in json_data:
            if json_data['errorData']['code'] == 'needAdult':
                raise RuntimeError(f"{url} The live stream is only accessible to logged-in adults. Please ensure that "
                                   f"the cookie is correctly filled in the configuration file after logging in.")
            else:
                raise RuntimeError(json_data['errorData']['code'], json_data['message'])
        m3u8_url = json_data['PlayList']['hls'][0]['url']
        play_url_list = await get_play_url_list(m3u8=m3u8_url, proxy=proxy_addr, header=headers, abroad=True)
        result['m3u8_url'] = m3u8_url
        result['play_url_list'] = play_url_list
    return result


async def get_twitchtv_room_info(url: str, token: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> tuple:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        'Accept-Language': 'zh-CN',
        'Referer': 'https://www.twitch.tv/',
        'Client-Id': 'kimne78kx3ncx6brgo4mv6wki5h1ko',
        'Client-Integrity': token,
        'Content-Type': 'text/plain;charset=UTF-8',
    }
    if cookies:
        headers['Cookie'] = cookies
    uid = url.split('?')[0].rsplit('/', maxsplit=1)[-1]

    data = [
        {
            "operationName": "ChannelShell",
            "variables": {
                "login": uid
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "580ab410bcd0c1ad194224957ae2241e5d252b2c5173d8e0cce9d32d5bb14efe"
                }
            }
        },
    ]

    json_str = await async_req('https://gql.twitch.tv/gql', proxy_addr=proxy_addr, headers=headers,
                               json_data=data, abroad=True)
    json_data = json.loads(json_str)
    user_data = json_data[0]['data']['userOrError']
    login_name = user_data["login"]
    nickname = f"{user_data['displayName']}-{login_name}"
    status = True if user_data['stream'] else False
    return nickname, status


@trace_error_decorator
async def get_twitchtv_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Accept-Language': 'en-US',
        'Referer': 'https://www.twitch.tv/',
        'Client-ID': 'kimne78kx3ncx6brgo4mv6wki5h1ko',
        'device-id': generate_random_string(16).lower(),
    }

    if cookies:
        headers['Cookie'] = cookies
    uid = url.split('?')[0].rsplit('/', maxsplit=1)[-1]

    data = {
        "operationName": "PlaybackAccessToken_Template",
        "query": "query PlaybackAccessToken_Template($login: String!, $isLive: Boolean!, $vodID: ID!, "
                 "$isVod: Boolean!, $playerType: String!) {  streamPlaybackAccessToken(channelName: $login, "
                 "params: {platform: \"web\", playerBackend: \"mediaplayer\", playerType: $playerType}) @include(if: "
                 "$isLive) {    value    signature   authorization { isForbidden forbiddenReasonCode }   __typename  "
                 "}  videoPlaybackAccessToken(id: $vodID, params: {platform: \"web\", playerBackend: \"mediaplayer\", "
                 "playerType: $playerType}) @include(if: $isVod) {    value    signature   __typename  }}",
        "variables": {
            "isLive": True,
            "login": uid,
            "isVod": False,
            "vodID": "",
            "playerType": "site"
        }
    }

    json_str = await async_req('https://gql.twitch.tv/gql', proxy_addr=proxy_addr, headers=headers,
                               json_data=data, abroad=True)
    json_data = json.loads(json_str)
    token = json_data['data']['streamPlaybackAccessToken']['value']
    sign = json_data['data']['streamPlaybackAccessToken']['signature']

    anchor_name, live_status = await get_twitchtv_room_info(url=url, token=token, proxy_addr=proxy_addr, cookies=cookies)
    result = {"anchor_name": anchor_name, "is_live": live_status}
    if live_status:
        play_session_id = random.choice(["bdd22331a986c7f1073628f2fc5b19da", "064bc3ff1722b6f53b0b5b8c01e46ca5"])
        params = {
            "acmb": "e30=",
            "allow_source": "true",
            "browser_family": "firefox",
            "browser_version": "124.0",
            "cdm": "wv",
            "fast_bread": "true",
            "os_name": "Windows",
            "os_version": "NT%2010.0",
            "p": "3553732",
            "platform": "web",
            "play_session_id": play_session_id,
            "player_backend": "mediaplayer",
            "player_version": "1.28.0-rc.1",
            "playlist_include_framerate": "true",
            "reassignments_supported": "true",
            "sig": sign,
            "token": token,
            "transcode_mode": "cbr_v1"
        }
        access_key = urllib.parse.urlencode(params)
        m3u8_url = f'https://usher.ttvnw.net/api/channel/hls/{uid}.m3u8?{access_key}'
        play_url_list = await get_play_url_list(m3u8=m3u8_url, proxy=proxy_addr, header=headers, abroad=True)
        result |= {'m3u8_url': m3u8_url, 'play_url_list': play_url_list}
    return result


@trace_error_decorator
async def get_liveme_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'origin': 'https://www.liveme.com',
        'referer': 'https://www.liveme.com',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }
    if cookies:
        headers['Cookie'] = cookies

    if 'index.html' not in url:
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers, abroad=True)
        match_url = re.search('<meta property="og:url" content="(.*?)">', html_str)
        if match_url:
            url = match_url.group(1)

    room_id = url.split("/index.html")[0].rsplit('/', maxsplit=1)[-1]
    sign_data = execjs.compile(open(f'{JS_SCRIPT_PATH}/liveme.js').read()).call('sign', room_id,
                                                                                f'{JS_SCRIPT_PATH}/crypto-js.min.js')
    lm_s_sign = sign_data.pop("lm_s_sign")
    tongdun_black_box = sign_data.pop("tongdun_black_box")
    platform = sign_data.pop("os")
    headers['lm-s-sign'] = lm_s_sign

    params = {
        'alias': 'liveme',
        'tongdun_black_box': tongdun_black_box,
        'os': platform,
    }

    api = f'https://live.liveme.com/live/queryinfosimple?{urllib.parse.urlencode(params)}'
    json_str = await async_req(api, data=sign_data, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)
    stream_data = json_data['data']['video_info']
    anchor_name = stream_data['uname']
    live_status = stream_data['status']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == "0":
        m3u8_url = stream_data['hlsvideosource']
        flv_url = stream_data['videosource']
        result |= {
            'is_live': True,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': m3u8_url or flv_url
        }
    return result


@trace_error_decorator
async def get_youtube_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }

    if cookies:
        headers['Cookie'] = cookies

    html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_str = re.search('var ytInitialPlayerResponse = (.*?);var meta = document\\.createElement', html_str).group(1)
    json_data = json.loads(json_str)
    result = {"anchor_name": "", "is_live": False}
    if 'videoDetails' not in json_data:
        print("Error: Please log in to YouTube on your device's webpage and configure cookies in the config.ini")
        return result
    result['anchor_name'] = json_data['videoDetails']['author']
    live_status = json_data['videoDetails'].get('isLive')
    if live_status:
        live_title = json_data['videoDetails']['title']
        m3u8_url = json_data['streamingData']["hlsManifestUrl"]
        play_url_list = await get_play_url_list(m3u8_url, proxy=proxy_addr, header=headers, abroad=True)
        result |= {"is_live": True, "title": live_title, "m3u8_url": m3u8_url, "play_url_list": play_url_list}
    return result


@trace_error_decorator
async def get_shopee_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://live.shopee.sg/share?from=live&session=802458&share_user_id=',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    result = {"anchor_name": "", "is_live": False}
    is_living = False

    if 'live.shopee' not in url and 'uid' not in url:
        url = await async_req(url, proxy_addr=proxy_addr, headers=headers, redirect_url=True, abroad=True)

    if 'live.shopee' in url:
        host_suffix = url.split('/')[2].rsplit('.', maxsplit=1)[1]
        is_living = get_params(url, 'uid') is None
    else:
        host_suffix = url.split('/')[2].split('.', maxsplit=1)[0]

    uid = get_params(url, 'uid')
    api_host = f'https://live.shopee.{host_suffix}'
    session_id = get_params(url, 'session')
    if uid:
        json_str = await async_req(f'{api_host}/api/v1/shop_page/live/ongoing?uid={uid}',
                           proxy_addr=proxy_addr, headers=headers, abroad=True)
        json_data = json.loads(json_str)
        if json_data['data']['ongoing_live']:
            session_id = json_data['data']['ongoing_live']['session_id']
            is_living = True
        else:
            json_str = await async_req(f'{api_host}/api/v1/shop_page/live/replay_list?offset=0&limit=1&uid={uid}',
                               proxy_addr=proxy_addr, headers=headers, abroad=True)
            json_data = json.loads(json_str)
            if json_data['data']['replay']:
                result['anchor_name'] = json_data['data']['replay'][0]['nick_name']
                return result

    json_str = await async_req(f'{api_host}/api/v1/session/{session_id}', proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)
    if not json_data.get('data'):
        print("Fetch shopee live data failed, please update the address of the live broadcast room and try again.")
        return result
    uid = json_data['data']['session']['uid']
    anchor_name = json_data['data']['session']['nickname']
    live_status = json_data['data']['session']['status']
    result["anchor_name"] = anchor_name
    result['uid'] = f'uid={uid}&session={session_id}'
    if live_status == 1 and is_living:
        flv_url = json_data['data']['session']['play_url']
        title = json_data['data']['session']['title']
        result |= {'is_live': True, 'title': title, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_faceit_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Referer': 'https://www.faceit.com/zh/players/qpjzz/stream',
        'faceit-referer': 'web-next',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }

    if cookies:
        headers['Cookie'] = cookies
    nickname = re.findall('/players/(.*?)/stream', url)[0]
    api = f'https://www.faceit.com/api/users/v1/nicknames/{nickname}'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    user_id = json_data['payload']['id']
    api2 = f'https://www.faceit.com/api/stream/v1/streamings?userId={user_id}'
    json_str2 = await async_req(api2, proxy_addr=proxy_addr, headers=headers)
    json_data2 = json.loads(json_str2)
    platform_info = json_data2['payload'][0]
    anchor_name = platform_info.get('userNickname')
    anchor_id = platform_info.get('platformId')
    platform = platform_info.get('platform')
    if platform == 'twitch':
        result = await get_twitchtv_stream_data(f'https://www.twitch.tv/{anchor_id}')
        result['anchor_name'] = anchor_name
    else:
        result = {'anchor_name': anchor_name, 'is_live': False}
    return result


@trace_error_decorator
async def get_picarto_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
            'accept-language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        }

    if cookies:
        headers['cookie'] = cookies

    anchor_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    api = f'https://ptvintern.picarto.tv/api/channel/detail/{anchor_id}'

    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    anchor_name = json_data['channel']['name']
    live_status = json_data['channel']['online']

    result = {"anchor_name": anchor_name, "is_live": live_status}
    if live_status:
        title = json_data['channel']['title']
        m3u8_url = f"https://1-edge1-us-newyork.picarto.tv/stream/hls/golive+{anchor_name}/index.m3u8"
        result |= {'is_live': True, 'title': title, 'm3u8_url': m3u8_url, 'record_url': m3u8_url}
    return result

