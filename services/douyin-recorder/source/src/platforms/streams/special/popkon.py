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
def _popkon_build_cast_data(room_info: tuple, room_password: OptionalStr,
                            username: OptionalStr, code: OptionalStr) -> dict:
    """构建 castwatch 请求体"""
    cast_start_date_code, cast_partner_code, mc_sign_id, cast_type, is_private = room_info
    return {
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


async def _popkon_request_cast(data: dict, headers: dict, proxy_addr: OptionalStr) -> str:
    """请求 castwatch API"""
    play_api = 'https://www.popkontv.com/api/proxy/broadcast/v1/castwatchonoffguest'
    return await async_req(play_api, proxy_addr=proxy_addr, json_data=data, headers=headers, abroad=True)


async def _popkon_relogin(username: str, password: str, partner_code: str,
                          proxy_addr: OptionalStr) -> tuple:
    """token 过期后重新登录，返回 (bearer_token, new_partner_code)"""
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
        return f'Bearer {new_access_token}', new_partner_code
    raise RuntimeError("popkontv login failed, please check if the account and password are correct")


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

        data = _popkon_build_cast_data(room_info, room_password, username, partner_code)
        json_str = await _popkon_request_cast(data, headers, proxy_addr)

        if 'HTTP Error 400' in json_str or 'statusCd":"E5000' in json_str:
            print("Failed to retrieve popkontv live stream [token does not exist or has expired]: Please log in to "
                  "watch.")
            new_token, new_partner_code = await _popkon_relogin(username, password, partner_code, proxy_addr)
            headers['Authorization'] = new_token
            data = _popkon_build_cast_data(room_info, room_password, username, new_partner_code)
            json_str = await _popkon_request_cast(data, headers, proxy_addr)

        json_data = json.loads(json_str)
        status_msg = json_data["statusMsg"]
        if json_data['statusCd'] == "L000A":
            print("Failed to retrieve live stream source,", status_msg)
            raise RuntimeError("You are an unverified member. After logging into the popkontv official website, "
                               "please verify your mobile phone at the bottom of the 'My Page' > 'Edit My "
                               "Information' to use the service.")
        elif json_data['statusCd'] == "L0001":
            data['castCode'] = f'{mc_sign_id}-{int(cast_start_date_code) - 1}'
            json_str = await _popkon_request_cast(data, headers, proxy_addr)
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

