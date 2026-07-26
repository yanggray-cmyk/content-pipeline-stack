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
        except Exception as e:
            raise Exception(f"Douyin web data fetch error, because {e}.")

        if room_data['status'] == 2:
            if 'stream_url' not in room_data:
                raise RuntimeError(
                    "The live streaming type or gameplay is not supported on the computer side yet, please use the "
                    "app to share the link for recording."
                )
            live_core_sdk_data = room_data['stream_url']['live_core_sdk_data']
            pull_datas = room_data['stream_url']['pull_datas']
            if live_core_sdk_data:
                if pull_datas:
                    key = list(pull_datas.keys())[0]
                    json_str = pull_datas[key]['stream_data']
                else:
                    json_str = live_core_sdk_data['pull_data']['stream_data']
                json_data = json.loads(json_str)
                if 'origin' in json_data['data']:
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
    except Exception as e:
        print(f"Error message: {e} Error line: {e.__traceback__.tb_lineno}")
        room_data = {'anchor_name': ""}
    return room_data


@trace_error_decorator
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

    async def get_app_data(room_id: str, sec_uid: str) -> dict:
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

    try:
        web_rid = url.split('?')[0].split('live.douyin.com/')
        if len(web_rid) > 1:
            return await get_douyin_web_stream_data(url, proxy_addr, cookies)
        else:
            try:
                data = await get_sec_user_id(url, proxy_addr=proxy_addr)
                _room_id, _sec_uid = data
                room_data = await get_app_data(_room_id, _sec_uid)
            except UnsupportedUrlError:
                unique_id = await get_unique_id(url, proxy_addr=proxy_addr)
                return await get_douyin_stream_data(f'https://live.douyin.com/{unique_id}')

        if room_data['status'] == 2:
            if 'stream_url' not in room_data:
                raise RuntimeError(
                    "The live streaming type or gameplay is not supported on the computer side yet, please use the "
                    "app to share the link for recording."
                )
            live_core_sdk_data = room_data['stream_url']['live_core_sdk_data']
            pull_datas = room_data['stream_url']['pull_datas']
            if live_core_sdk_data:
                if pull_datas:
                    key = list(pull_datas.keys())[0]
                    json_str = pull_datas[key]['stream_data']
                else:
                    json_str = live_core_sdk_data['pull_data']['stream_data']
                json_data = json.loads(json_str)
                if 'origin' in json_data['data']:
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
async def get_huya_app_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'xweb_xhr': '1',
        'referer': 'https://servicewechat.com/wx74767bf0b684f7d3/301/page-frame.html',
        'accept-language': 'zh-CN,zh;q=0.9',
    }

    if cookies:
        headers['Cookie'] = cookies
    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]

    if any(char.isalpha() for char in room_id):
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers)
        room_id = re.search('ProfileRoom":(.*?),"sPrivateHost', html_str)
        if room_id:
            room_id = room_id.group(1)
        else:
            raise Exception('Please use "https://www.huya.com/+room_number" for recording')

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
    else:
        base_steam_info_list = json_data['data']['stream']['baseSteamInfoList']
        play_url_list = []
        for i in base_steam_info_list:
            cdn_type = i['sCdnType']
            stream_name = i['sStreamName']
            s_flv_url = i['sFlvUrl']
            flv_anti_code = i['sFlvAntiCode']
            s_hls_url = i['sHlsUrl']
            hls_anti_code = i['sHlsAntiCode']
            m3u8_url = f'{s_hls_url}/{stream_name}.m3u8?{hls_anti_code}'
            flv_url = f'{s_flv_url}/{stream_name}.flv?{flv_anti_code}'
            play_url_list.append(
                {
                    'cdn_type': cdn_type,
                    'm3u8_url': m3u8_url,
                    'flv_url': flv_url,
                }
            )
        #print(json.dumps(play_url_list, indent=4, ensure_ascii=False))
        # flv_url = 'https://' + play_url_list[0]['flv_url'].split('://')[1]
        # record_url = flv_url

        # 设定优先级，优先选择 TX,2025/03/14时AL不可用
        priority_order = ["TX", "HW", "HS", "AL"]

        # 查找优先的 flv_url
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

        # 处理 flv_url，确保使用 https
        if selected_flv_url:
            flv_url = 'https://' + selected_flv_url.split('://')[1]

            # 如果选择的是 TX，执行额外的字符串替换
            if selected_cdn_type == "TX":
                flv_url = flv_url.replace("&ctype=tars_mp", "&ctype=huya_webh5").replace("&fs=bhct", "&fs=bgct")

            record_url = flv_url
        else:
            record_url = None

        return {
            'anchor_name': anchor_name,
            'is_live': True,
            'm3u8_url': play_url_list[0]['m3u8_url'],
            'flv_url': play_url_list[0]['flv_url'],
            'record_url': record_url,
            'title': live_title
        }


@trace_error_decorator
async def login_sooplive(username: str, password: str, proxy_addr: OptionalStr = None) -> OptionalStr:
    if len(username) < 6 or len(password) < 10:
        raise RuntimeError("sooplive login failed! Please enter the correct account and password for the sooplive "
                           "platform in the config.ini file.")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin': 'https://play.sooplive.co.kr',
        'Referer': 'https://play.sooplive.co.kr/superbsw123/277837074',
    }

    data = {
        'szWork': 'login',
        'szType': 'json',
        'szUid': username,
        'szPassword': password,
        'isSaveId': 'true',
        'isSavePw': 'true',
        'isSaveJoin': 'true',
        'isLoginRetain': 'Y',
    }

    url = 'https://login.sooplive.co.kr/app/LoginAction.php'

    try:
        cookie_dict = await async_req(url, proxy_addr=proxy_addr, headers=headers,
                                      data=data, return_cookies=True, timeout=20)
        cookie_str = '; '.join([f"{k}={v}" for k, v in cookie_dict.items()])
        return cookie_str
    except Exception as e:
        print(f"An error occurred during login: {e}")
        raise Exception(
            "sooplive login failed, please check if the account password in the configuration file is correct."
        )


@trace_error_decorator
async def get_sooplive_cdn_url(broad_no: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Origin': 'https://play.sooplive.co.kr',
        'Referer': 'https://play.sooplive.co.kr/oul282/249469582',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    if cookies:
        headers['Cookie'] = cookies

    params = {
        'return_type': 'gcp_cdn',
        'use_cors': 'false',
        'cors_origin_url': 'play.sooplive.co.kr',
        'broad_key': f'{broad_no}-common-master-hls',
        'time': '8361.086329376785',
    }

    url2 = 'http://livestream-manager.sooplive.co.kr/broad_stream_assign.html?' + urllib.parse.urlencode(params)
    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)

    return json_data


@trace_error_decorator
async def get_sooplive_tk(url: str, rtype: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> str | tuple:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Origin': 'https://play.sooplive.co.kr',
        'Referer': 'https://play.sooplive.co.kr/secretx/250989857',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    if cookies:
        headers['Cookie'] = cookies

    split_url = url.split('/')
    bj_id = split_url[3] if len(split_url) < 6 else split_url[5]
    room_password = get_params(url, "pwd")
    if not room_password:
        room_password = ''
    data = {
        'bid': bj_id,
        'bno': '',
        'type': rtype,
        'pwd': room_password,
        'player_type': 'html5',
        'stream_type': 'common',
        'quality': 'master',
        'mode': 'landing',
        'from_api': '0',
        'is_revive': 'false',
    }

    url2 = f'https://live.sooplive.co.kr/afreeca/player_live_api.php?bjid={bj_id}'
    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers, data=data, abroad=True)
    json_data = json.loads(json_str)

    if rtype == 'aid':
        token = json_data["CHANNEL"]["AID"]
        return token
    else:
        bj_name = json_data['CHANNEL']['BJNICK']
        bj_id = json_data['CHANNEL']['BJID']
        return f"{bj_name}-{bj_id}", json_data['CHANNEL']['BNO']


def get_soop_headers(cookies):
    headers = {
        'client-id': str(uuid.uuid4()),
        'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, '
                      'like Gecko) Version/18.5 Mobile/15E148 Safari/604.1 Edg/141.0.0.0',
    }
    if cookies:
        headers['cookie'] = cookies
    return headers


async def _get_soop_channel_info_global(bj_id, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> str:
    headers = get_soop_headers(cookies)
    api = 'https://api.sooplive.com/v2/channel/info/' + str(bj_id)
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    nickname = json_data['data']['streamerChannelInfo']['nickname']
    channelId = json_data['data']['streamerChannelInfo']['channelId']
    anchor_name = f"{nickname}-{channelId}"
    return anchor_name


async def _get_soop_stream_info_global(bj_id, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> tuple:
    headers = get_soop_headers(cookies)
    api = 'https://api.sooplive.com/v2/stream/info/' + str(bj_id)
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    status = json_data['data']['isStream']
    title = json_data['data']['title']
    return status, title


async def _fetch_web_stream_data_global(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    split_url = url.split('/')
    bj_id = split_url[3] if len(split_url) < 6 else split_url[5]
    anchor_name = await _get_soop_channel_info_global(bj_id)
    result = {"anchor_name": anchor_name or '', "is_live": False, "live_url": url}
    status, title = await _get_soop_stream_info_global(bj_id)
    if not status:
        return result
    else:
        async def _get_url_list(m3u8: str) -> list[str]:
            headers = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0',
            }
            if cookies:
                headers['cookie'] = cookies
            resp = await async_req(url=m3u8, proxy_addr=proxy_addr, headers=headers)
            play_url_list = []
            url_prefix = '/'.join(m3u8.split('/')[0:3])
            for i in resp.split('\n'):
                if not i.startswith('#') and i.strip():
                    play_url_list.append(url_prefix + i.strip())
            bandwidth_pattern = re.compile(r'BANDWIDTH=(\d+)')
            bandwidth_list = bandwidth_pattern.findall(resp)
            url_to_bandwidth = {purl: int(bandwidth) for bandwidth, purl in zip(bandwidth_list, play_url_list)}
            play_url_list = sorted(play_url_list, key=lambda purl: url_to_bandwidth[purl], reverse=True)
            return play_url_list

        m3u8_url = 'https://global-media.sooplive.com/live/' + str(bj_id) + '/master.m3u8'
        result |= {
            'is_live': True,
            'title': title,
            'm3u8_url': m3u8_url,
            'play_url_list': await _get_url_list(m3u8_url)
        }
    return result


@trace_error_decorator
async def get_sooplive_stream_data(
        url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None,
        username: OptionalStr = None, password: OptionalStr = None
) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://m.sooplive.co.kr/',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    if cookies:
        headers['Cookie'] = cookies

    if "sooplive.com" in url:
        return await _fetch_web_stream_data_global(url, proxy_addr, cookies)

    split_url = url.split('/')
    bj_id = split_url[3] if len(split_url) < 6 else split_url[5]

    data = {
        'bj_id': bj_id,
        'broad_no': '',
        'agent': 'web',
        'confirm_adult': 'true',
        'player_type': 'webm',
        'mode': 'live',
    }

    url2 = 'http://api.m.sooplive.co.kr/broad/a/watch'

    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers, data=data, abroad=True)
    json_data = json.loads(json_str)

    if 'user_nick' in json_data['data']:
        anchor_name = json_data['data']['user_nick']
        if "bj_id" in json_data['data']:
            anchor_name = f"{anchor_name}-{json_data['data']['bj_id']}"
    else:
        anchor_name = ''

    result = {"anchor_name": anchor_name or '' ,"is_live": False}

    async def get_url_list(m3u8: str) -> List[str]:
        resp = await async_req(url=m3u8, proxy_addr=proxy_addr, headers=headers, abroad=True)
        play_url_list = []
        url_prefix = m3u8.rsplit('/', maxsplit=1)[0] + '/'
        for i in resp.split('\n'):
            if i.startswith('auth_playlist'):
                play_url_list.append(url_prefix + i.strip())
        bandwidth_pattern = re.compile(r'BANDWIDTH=(\d+)')
        bandwidth_list = bandwidth_pattern.findall(resp)
        url_to_bandwidth = {purl: int(bandwidth) for bandwidth, purl in zip(bandwidth_list, play_url_list)}
        play_url_list = sorted(play_url_list, key=lambda purl: url_to_bandwidth[purl], reverse=True)
        return play_url_list

    if not anchor_name:
        async def handle_login() -> OptionalStr:
            cookie = await login_sooplive(username, password, proxy_addr=proxy_addr)
            if 'AuthTicket=' in cookie:
                print("sooplive platform login successful! Starting to fetch live streaming data...")
                return cookie

        async def fetch_data(cookie, _result) -> dict:
            aid_token = await get_sooplive_tk(url, rtype='aid', proxy_addr=proxy_addr, cookies=cookie)
            _anchor_name, _broad_no = await get_sooplive_tk(url, rtype='info', proxy_addr=proxy_addr, cookies=cookie)
            _view_url_data = await get_sooplive_cdn_url(_broad_no, proxy_addr=proxy_addr)
            _view_url = _view_url_data['view_url']
            _m3u8_url = _view_url + '?aid=' + aid_token
            _result |= {
                "anchor_name": _anchor_name,
                "is_live": True,
                "m3u8_url": _m3u8_url,
                'play_url_list': await get_url_list(_m3u8_url),
                'new_cookies': cookie
            }
            return _result

        if json_data['data']['code'] == -3001:
            print("sooplive live stream failed to retrieve, the live stream just ended.")
            return result

        elif json_data['data']['code'] == -3002:
            print("sooplive live stream retrieval failed, the live needs 19+, you are not logged in.")
            print("Attempting to log in to the sooplive live streaming platform with your account and password, "
                  "please ensure it is configured.")
            new_cookie = await handle_login()
            if new_cookie and len(new_cookie) > 0:
                return await fetch_data(new_cookie, result)
            raise RuntimeError("sooplive login failed, please check if the account and password are correct")

        elif json_data['data']['code'] == -3004:
            if cookies and len(cookies) > 0:
                return await fetch_data(cookies, result)
            else:
                raise RuntimeError("sooplive login failed, please check if the account and password are correct")
        elif json_data['data']['code'] == -6001:
            print("error message：Please check if the input sooplive live room address "
                  "is correct.")
            return result
    if json_data['result'] == 1 and anchor_name:
        broad_no = json_data['data']['broad_no']
        hls_authentication_key = json_data['data']['hls_authentication_key']
        view_url_data = await get_sooplive_cdn_url(broad_no, proxy_addr=proxy_addr)
        view_url = view_url_data['view_url']
        m3u8_url = view_url + '?aid=' + hls_authentication_key
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'play_url_list': await get_url_list(m3u8_url)}
    result['new_cookies'] = None
    return result


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


@trace_error_decorator
async def login_popkontv(
        username: str, password: str, proxy_addr: OptionalStr = None, code: OptionalStr = 'P-00001'
) -> tuple:
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Authorization': 'Basic FpAhe6mh8Qtz116OENBmRddbYVirNKasktdXQiuHfm88zRaFydTsFy63tzkdZY0u',
        'Content-Type': 'application/json',
        'Origin': 'https://www.popkontv.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }

    data = {
        'partnerCode': code,
        'signId': username,
        'signPwd': password,
    }

    url = 'https://www.popkontv.com/api/proxy/member/v1/login'

    try:
        proxy_addr = utils.handle_proxy_addr(proxy_addr)
        async with httpx.AsyncClient(proxy=proxy_addr, timeout=20, verify=False) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

            json_data = response.json()
            login_status_code = json_data.get("statusCd")

            if login_status_code == 'E4010':
                raise Exception("popkontv login failed, please reconfigure the correct login account or password!")
            elif login_status_code == 'S2000':
                token = json_data['data'].get("token")
                partner_code = json_data['data'].get("partnerCode")
                return token, partner_code
            else:
                raise Exception(f"popkontv login failed, {json_data.get('statusMsg', 'unknown error')}")
    except httpx.HTTPStatusError as e:
        print(f"HTTP status error occurred during login: {e.response.status_code}")
        raise
    except Exception as e:
        print(f"An exception occurred during popkontv login: {e}")
        raise


@trace_error_decorator
async def get_popkontv_stream_data(
        url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None,
        username: OptionalStr = None, code: OptionalStr = 'P-00001'
) -> tuple:
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Content-Type': 'application/json',
        'Origin': 'https://www.popkontv.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies
    if 'mcid' in url:
        anchor_id = re.search('mcid=(.*?)&', url).group(1)
    else:
        anchor_id = re.search('castId=(.*?)(?=&|$)', url).group(1)

    data = {
        'partnerCode': code,
        'searchKeyword': anchor_id,
        'signId': username,
    }

    api = 'https://www.popkontv.com/api/proxy/broadcast/v1/search/all'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers, json_data=data, abroad=True)
    json_data = json.loads(json_str)

    partner_code = ''
    anchor_name = 'Unknown'
    for item in json_data['data']['broadCastList']:
        if item['mcSignId'] == anchor_id:
            mc_name = item['nickName']
            anchor_name = f"{mc_name}-{anchor_id}"
            partner_code = item['mcPartnerCode']
            break

    if not partner_code:
        if 'mcPartnerCode' in url:
            regex_result = re.search('mcPartnerCode=(P-\\d+)', url)
        else:
            regex_result = re.search('partnerCode=(P-\\d+)', url)
        partner_code = regex_result.group(1) if regex_result else code
        notices_url = f'https://www.popkontv.com/channel/notices?mcid={anchor_id}&mcPartnerCode={partner_code}'
        notices_response = await async_req(notices_url, proxy_addr=proxy_addr, headers=headers, abroad=True)
        mc_name_match = re.search(r'"mcNickName":"([^"]+)"', notices_response)
        mc_name = mc_name_match.group(1) if mc_name_match else 'Unknown'
        anchor_name = f"{anchor_id}-{mc_name}"

    live_url = f"https://www.popkontv.com/live/view?castId={anchor_id}&partnerCode={partner_code}"
    html_str2 = await async_req(live_url, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_str2 = re.search('<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_str2).group(1)
    json_data2 = json.loads(json_str2)
    if 'mcData' in json_data2['props']['pageProps']:
        room_data = json_data2['props']['pageProps']['mcData']['data']
        is_private = room_data['mc_isPrivate']
        cast_start_date_code = room_data['mc_castStartDate']
        mc_sign_id = room_data['mc_signId']
        cast_type = room_data['castType']
        return anchor_name, [cast_start_date_code, partner_code, mc_sign_id, cast_type, is_private]
    else:
        return anchor_name, None


@trace_error_decorator
async def get_popkontv_stream_url(
        url: str,
        proxy_addr: OptionalStr = None,
        access_token: OptionalStr = None,
        username: OptionalStr = None,
        password: OptionalStr = None,
        partner_code: OptionalStr = 'P-00001'
) -> dict:
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'ClientKey': 'Client FpAhe6mh8Qtz116OENBmRddbYVirNKasktdXQiuHfm88zRaFydTsFy63tzkdZY0u',
        'Content-Type': 'application/json',
        'Origin': 'https://www.popkontv.com',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }

    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'

    anchor_name, room_info = await get_popkontv_stream_data(
        url, proxy_addr=proxy_addr, code=partner_code, username=username)
    result = {"anchor_name": anchor_name, "is_live": False}
    new_token = None
    if room_info:
        cast_start_date_code, cast_partner_code, mc_sign_id, cast_type, is_private = room_info
        result["is_live"] = True
        room_password = get_params(url, "pwd")
        if int(is_private) != 0 and not room_password:
            raise RuntimeError(f"Failed to retrieve live room data because {anchor_name}'s room is a private room. "
                               f"Please configure the room password and try again.")

        async def fetch_data(header: dict = None, code: str = None) -> str:
            data = {
                'androidStore': 0,
                'castCode': f'{mc_sign_id}-{cast_start_date_code}',
                'castPartnerCode': cast_partner_code,
                'castSignId': mc_sign_id,
                'castType': cast_type,
                'commandType': 0,
                'exePath': 5,
                'isSecret': is_private,
                'partnerCode': code,
                'password': room_password,
                'signId': username,
                'version': '4.6.2',
            }
            play_api = 'https://www.popkontv.com/api/proxy/broadcast/v1/castwatchonoffguest'
            return await async_req(play_api, proxy_addr=proxy_addr, json_data=data, headers=header, abroad=True)

        json_str = await fetch_data(headers, partner_code)

        if 'HTTP Error 400' in json_str or 'statusCd":"E5000' in json_str:
            print("Failed to retrieve popkontv live stream [token does not exist or has expired]: Please log in to "
                  "watch.")
            print("Attempting to log in to the popkontv live streaming platform, please ensure your account "
                  "and password are correctly filled in the configuration file.")
            if len(username) < 4 or len(password) < 10:
                raise RuntimeError("popkontv login failed! Please enter the correct account and password for the "
                                   "popkontv platform in the config.ini file.")
            print("Logging into popkontv platform...")
            new_access_token, new_partner_code = await login_popkontv(
                username=username, password=password, proxy_addr=proxy_addr, code=partner_code
            )
            if new_access_token and len(new_access_token) == 640:
                print("Logged into popkontv platform successfully! Starting to fetch live streaming data...")
                headers['Authorization'] = f'Bearer {new_access_token}'
                new_token = f'Bearer {new_access_token}'
                json_str = await fetch_data(headers, new_partner_code)
            else:
                raise RuntimeError("popkontv login failed, please check if the account and password are correct")
        json_data = json.loads(json_str)
        status_msg = json_data["statusMsg"]
        if json_data['statusCd'] == "L000A":
            print("Failed to retrieve live stream source,", status_msg)
            raise RuntimeError("You are an unverified member. After logging into the popkontv official website, "
                               "please verify your mobile phone at the bottom of the 'My Page' > 'Edit My "
                               "Information' to use the service.")
        elif json_data['statusCd'] == "L0001":
            cast_start_date_code = int(cast_start_date_code) - 1
            json_str = await fetch_data(headers, partner_code)
            json_data = json.loads(json_str)
            m3u8_url = json_data['data']['castHlsUrl']
            result |= {"m3u8_url": m3u8_url, "record_url": m3u8_url}
        elif json_data['statusCd'] == "L0000":
            m3u8_url = json_data['data']['castHlsUrl']
            result |= {"m3u8_url": m3u8_url, "record_url": m3u8_url}
        else:
            raise RuntimeError("Failed to retrieve live stream source,", status_msg)
    result['new_token'] = new_token
    return result


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


@trace_error_decorator
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

    params = {
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

    for i in range(2):
        app_key = '12574478'
        _m_h5_tk = re.findall('_m_h5_tk=(.*?);', headers['Cookie'])[0]
        t13 = int(time.time() * 1000)
        pre_sign_str = f'{_m_h5_tk.split("_")[0]}&{t13}&{app_key}&' + params['data']
        sign = execjs.compile(open(f'{JS_SCRIPT_PATH}/taobao-sign.js').read()).call('sign', pre_sign_str)
        params |= {'sign': sign, 't': t13}
        api = f'https://h5api.m.taobao.com/h5/mtop.mediaplatform.live.livedetail/4.0/?{urllib.parse.urlencode(params)}'
        jsonp_str, new_cookie = await async_req(url=api, proxy_addr=proxy_addr, headers=headers, timeout=20,
                                                return_cookies=True, include_cookies=True)
        json_data = utils.jsonp_to_json(jsonp_str)

        ret_msg = json_data['ret']
        if ret_msg == ['SUCCESS::调用成功']:
            anchor_name = json_data['data']['broadCaster']['accountName']
            result = {"anchor_name": anchor_name, "is_live": False}
            live_status = json_data['data']['streamStatus']
            if live_status == '1':
                live_title = json_data['data']['title']
                play_url_list = json_data['data']['liveUrlList']

                def get_sort_key(item):
                    definition_priority = {
                        "lld": 0, "ld": 1, "md": 2, "hd": 3, "ud": 4
                    }
                    def_value = item.get('definition') or item.get('newDefinition')
                    priority = definition_priority.get(def_value, -1)
                    return priority

                play_url_list = sorted(play_url_list, key=get_sort_key, reverse=True)
                result |= {"is_live": True, "title": live_title, "play_url_list": play_url_list, 'live_id': live_id}

            return result
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

