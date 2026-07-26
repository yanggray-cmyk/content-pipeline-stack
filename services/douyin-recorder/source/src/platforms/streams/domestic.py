# -*- encoding: utf-8 -*-

"""国内平台流媒体获取函数"""

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
async def get_kuaishou_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    }
    if cookies:
        headers['Cookie'] = cookies
    try:
        html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    except Exception as e:
        print(f"Failed to fetch data from {url}.{e}")
        return {"type": 1, "is_live": False}

    try:
        json_str = re.search('<script>window.__INITIAL_STATE__=(.*?);\\(function\\(\\)\\{var s;', html_str).group(1)
        play_list = re.findall('(\\{"liveStream".*?),"gameInfo', json_str)[0] + "}"
        play_list = json.loads(play_list)
    except (AttributeError, IndexError, json.JSONDecodeError) as e:
        print(f"Failed to parse JSON data from {url}. Error: {e}")
        return {"type": 1, "is_live": False}

    result = {"type": 2, "is_live": False}

    if 'errorType' in play_list or 'liveStream' not in play_list:
        error_msg = play_list['errorType']['title'] + play_list['errorType']['content']
        print(f"Failed URL: {url} Error message: {error_msg}")
        return result

    if not play_list.get('liveStream'):
        print("IP banned. Please change device or network.")
        return result

    anchor_name = play_list['author'].get('name', '')
    result.update({"anchor_name": anchor_name})

    if play_list['liveStream'].get("playUrls"):
        if 'h264' in play_list['liveStream']['playUrls']:
            if 'adaptationSet' not in play_list['liveStream']['playUrls']['h264']:
                return result
            play_url_list = play_list['liveStream']['playUrls']['h264']['adaptationSet']['representation']
        else:
            # TODO: Old version which not working at 20241128, could be removed if not working confirmed
            play_url_list = play_list['liveStream']['playUrls'][0]['adaptationSet']['representation']
        result.update({"flv_url_list": play_url_list, "is_live": True})

    return result


@trace_error_decorator
async def get_kuaishou_stream_data2(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict | None:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': "https://www.kuaishou.com/short-video/3x224rwabjmuc9y?fid=1712760877&cc=share_copylink&followRefer=151&shareMethod=TOKEN&docId=9&kpn=KUAISHOU&subBiz=BROWSE_SLIDE_PHOTO&photoId=3x224rwabjmuc9y&shareId=17144298796566&shareToken=X-6FTMeYTsY97qYL&shareResourceType=PHOTO_OTHER&userId=3xtnuitaz2982eg&shareType=1&et=1_i/2000048330179867715_h3052&shareMode=APP&originShareId=17144298796566&appType=21&shareObjectId=5230086626478274600&shareUrlOpened=0&timestamp=1663833792288&utm_source=app_share&utm_medium=app_share&utm_campaign=app_share&location=app_share",
        'content-type': 'application/json',
        'Cookie': '',
    }
    if cookies:
        headers['Cookie'] = cookies
    try:
        eid = url.split('/u/')[1].strip()
        data = {"source": 5, "eid": eid, "shareMethod": "card", "clientType": "WEB_OUTSIDE_SHARE_H5"}
        app_api = 'https://livev.m.chenzhongtech.com/rest/k/live/byUser?kpn=GAME_ZONE&captchaToken='
        json_str = await async_req(url=app_api, proxy_addr=proxy_addr, headers=headers, data=data)
        json_data = json.loads(json_str)
        live_stream = json_data['liveStream']
        anchor_name = live_stream['user']['user_name']
        result = {
            "type": 2,
            "anchor_name": anchor_name,
            "is_live": False,
        }
        live_status = live_stream['living']
        if live_status:
            result['is_live'] = True
            backup_m3u8_url = live_stream['hlsPlayUrl']
            backup_flv_url = live_stream['playUrls'][0]['url']
            if 'multiResolutionHlsPlayUrls' in live_stream:
                m3u8_url_list = live_stream['multiResolutionHlsPlayUrls'][0]['urls']
                result['m3u8_url_list'] = m3u8_url_list
            if 'multiResolutionPlayUrls' in live_stream:
                flv_url_list = live_stream['multiResolutionPlayUrls'][0]['urls']
                result['flv_url_list'] = flv_url_list
            result['backup'] = {'m3u8_url': backup_m3u8_url, 'flv_url': backup_flv_url}
        if result['anchor_name']:
            return result
    except Exception as e:
        print(f"{e}, Failed URL: {url}, preparing to switch to a backup plan for re-parsing.")
    return await get_kuaishou_stream_data(url, cookies=cookies, proxy_addr=proxy_addr)


@trace_error_decorator
async def get_douyu_info_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Referer': 'https://m.douyu.com/3125893?rid=3125893&dyshid=0-96003918aa5365bc6dcb4933000316p1&dyshci=181',
        'Cookie': ''
    }
    if cookies:
        headers['Cookie'] = cookies

    match_rid = re.search('rid=(.*?)(?=&|$)', url)
    if match_rid:
        rid = match_rid.group(1)
    else:
        rid = re.search('douyu.com/(.*?)(?=\\?|$)', url).group(1)
        html_str = await async_req(url=f'https://m.douyu.com/{rid}', proxy_addr=proxy_addr, headers=headers)
        json_str = re.findall('<script id="vike_pageContext" type="application/json">(.*?)</script>', html_str)[0]
        json_data = json.loads(json_str)
        rid = json_data['pageProps']['room']['roomInfo']['roomInfo']['rid']

    headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'
    url2 = f'https://www.douyu.com/betard/{rid}'
    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    result = {
        "anchor_name": json_data['room']['nickname'],
        "is_live": False
    }
    if json_data['room']['videoLoop'] == 0 and json_data['room']['show_status'] == 1:
        result["title"] = json_data['room']['room_name'].replace('&nbsp;', '')
        result["is_live"] = True
        result["room_id"] = json_data['room']['room_id']
    return result


@trace_error_decorator
async def get_douyu_stream_data(rid: str, rate: str = '-1', proxy_addr: OptionalStr = None,
                          cookies: OptionalStr = None) -> dict:
    did = '10000000000000000000000000003306'
    params_list = await get_token_js(rid, did, proxy_addr=proxy_addr)
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Referer': 'https://m.douyu.com/3125893?rid=3125893&dyshid=0-96003918aa5365bc6dcb4933000316p1&dyshci=181',
        'Cookie': ''
    }
    if cookies:
        headers['Cookie'] = cookies

    data = {
        'v': params_list[0],
        'did': params_list[1],
        'tt': params_list[2],
        'sign': params_list[3],  # 10分钟有效期
        'ver': '22011191',
        'rid': rid,
        'rate': rate,  # 0蓝光、3超清、2高清、-1默认
    }

    # app_api = 'https://m.douyu.com/hgapi/livenc/room/getStreamUrl'
    app_api = f'https://www.douyu.com/lapi/live/getH5Play/{rid}'
    json_str = await async_req(url=app_api, proxy_addr=proxy_addr, headers=headers, data=data)
    json_data = json.loads(json_str)
    return json_data


@trace_error_decorator
async def get_yy_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://www.yy.com/',
        'Cookie': ''
    }
    if cookies:
        headers['Cookie'] = cookies

    html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    anchor_name = re.search('nick: "(.*?)",\n\\s+logo', html_str).group(1)
    cid = re.search('sid : "(.*?)",\n\\s+ssid', html_str, re.DOTALL).group(1)

    data = '{"head":{"seq":1701869217590,"appidstr":"0","bidstr":"121","cidstr":"' + cid + '","sidstr":"' + cid + '","uid64":0,"client_type":108,"client_ver":"5.17.0","stream_sys_ver":1,"app":"yylive_web","playersdk_ver":"5.17.0","thundersdk_ver":"0","streamsdk_ver":"5.17.0"},"client_attribute":{"client":"web","model":"web0","cpu":"","graphics_card":"","os":"chrome","osversion":"0","vsdk_version":"","app_identify":"","app_version":"","business":"","width":"1920","height":"1080","scale":"","client_type":8,"h265":0},"avp_parameter":{"version":1,"client_type":8,"service_type":0,"imsi":0,"send_time":1701869217,"line_seq":-1,"gear":4,"ssl":1,"stream_format":0}}'
    data_bytes = data.encode('utf-8')
    params = {
        "uid": "0",
        "cid": cid,
        "sid": cid,
        "appid": "0",
        "sequence": "1701869217590",
        "encode": "json"
    }
    url2 = f'https://stream-manager.yy.com/v3/channel/streams?{urllib.parse.urlencode(params)}'
    json_str = await async_req(url=url2, data=data_bytes, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    json_data['anchor_name'] = anchor_name

    params = {
        'uid': '',
        'sid': cid,
        'ssid': cid,
        '_': int(time.time() * 1000),
    }
    detail_api = f'https://www.yy.com/live/detail?{urllib.parse.urlencode(params)}'
    json_str2 = await async_req(detail_api, proxy_addr=proxy_addr, headers=headers)
    json_data2 = json.loads(json_str2)
    json_data['title'] = json_data2['data']['roomName']
    return json_data


@trace_error_decorator
async def get_bilibili_room_info_h5(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> str:
    headers = {
        'user-agent': 'Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile Safari/537.36',
        'accept-language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'cookie': '',
        'origin': 'https://live.bilibili.com',
        'referer': 'https://live.bilibili.com/26066074',
    }
    if cookies:
        headers['cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    api = f'https://api.live.bilibili.com/xlive/web-room/v1/index/getH5InfoByRoom?room_id={room_id}'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    room_info = json.loads(json_str)
    title = room_info['data']['room_info'].get('title') if room_info.get('data') else ''
    return title


@trace_error_decorator
async def get_bilibili_room_info(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    }
    if cookies:
        headers['Cookie'] = cookies

    try:
        room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
        json_str = await async_req(f'https://api.live.bilibili.com/room/v1/Room/room_init?id={room_id}',
                           proxy_addr=proxy_addr, headers=headers)
        room_info = json.loads(json_str)
        uid = room_info['data']['uid']
        live_status = True if room_info['data']['live_status'] == 1 else False

        api = f'https://api.live.bilibili.com/live_user/v1/Master/info?uid={uid}'
        json_str2 = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
        anchor_info = json.loads(json_str2)
        anchor_name = anchor_info['data']['info']['uname']

        title = await get_bilibili_room_info_h5(url, proxy_addr, cookies)
        return {"anchor_name": anchor_name, "live_status": live_status, "room_url": url, "title": title}
    except Exception as e:
        print(e)
        return {"anchor_name": '', "live_status": False, "room_url": url}


@trace_error_decorator
async def get_bilibili_stream_data(url: str, qn: str = '10000', platform: str = 'web', proxy_addr: OptionalStr = None,
                             cookies: OptionalStr = None) -> OptionalStr:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'origin': 'https://live.bilibili.com',
        'referer': 'https://live.bilibili.com/26066074',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    params = {
        'cid': room_id,
        'qn': qn,
        'platform': platform,
    }
    play_api = f'https://api.live.bilibili.com/room/v1/Room/playUrl?{urllib.parse.urlencode(params)}'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    if json_data and json_data['code'] == 0:
        for i in json_data['data']['durl']:
            if 'd1--cn-gotcha' in i['url']:
                return i['url']
        return json_data['data']['durl'][-1]['url']
    else:
        params = {
            "room_id": room_id,
            "protocol": "0,1",
            "format": "0,1,2",
            "codec": "0,1,2",
            "qn": qn,
            "platform": "web",
            "ptype": "8",
            "dolby": "5",
            "panorama": "1",
            "hdr_type": "0,1"
        }

        # 此接口因网页上有限制, 需要配置登录后的cookie才能获取最高画质
        api = f'https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo?{urllib.parse.urlencode(params)}'
        json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        if json_data['data']['live_status'] == 0:
            print("The anchor did not start broadcasting.")
            return
        playurl_info = json_data['data']['playurl_info']
        format_list = playurl_info['playurl']['stream'][0]['format']
        stream_data_list = format_list[0]['codec']
        sorted_stream_list = sorted(stream_data_list, key=itemgetter("current_qn"), reverse=True)
        # qn: 30000=杜比 20000=4K 10000=原画 400=蓝光 250=超清 150=高清 80=流畅
        video_quality_options = {'10000': 0, '400': 1, '250': 2, '150': 3, '80': 4}
        qn_count = len(sorted_stream_list)
        select_stream_index = min(video_quality_options[qn], qn_count - 1)
        stream_data: dict = sorted_stream_list[select_stream_index]
        base_url = stream_data['base_url']
        host = stream_data['url_info'][0]['host']
        extra = stream_data['url_info'][0]['extra']
        m3u8_url = host + base_url + extra
        return m3u8_url


@trace_error_decorator
async def get_xhs_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'xy-common-params': 'platform=iOS&sid=session.1722166379345546829388',
        'referer': 'https://app.xhs.cn/',
    }
    if cookies:
        headers['Cookie'] = cookies

    if "xhslink.com" in url:
        url = await async_req(url, proxy_addr=proxy_addr, headers=headers, redirect_url=True)

    host_id = get_params(url, "host_id")
    user_id = re.search("/user/profile/(.*?)(?=/|\\?|$)", url)
    user_id = user_id.group(1) if user_id else host_id
    result = {"anchor_name": '', "is_live": False}
    html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers)
    match_data = re.search("<script>window.__INITIAL_STATE__=(.*?)</script>", html_str)

    if match_data:
        json_str = match_data.group(1).replace("undefined", "null")
        json_data = json.loads(json_str)

        if json_data.get("liveStream"):
            stream_data = json_data["liveStream"]
            if stream_data.get("liveStatus") == "success":
                room_info = stream_data["roomData"]["roomInfo"]
                title = room_info.get("roomTitle")
                if title and "回放" not in title:
                    live_link = room_info["deeplink"]
                    anchor_name = get_params(live_link, "host_nickname")
                    flv_url = get_params(live_link, "flvUrl")
                    room_id = flv_url.split('live/')[1].split('.')[0]
                    flv_url = f"http://live-source-play.xhscdn.com/live/{room_id}.flv"
                    m3u8_url = flv_url.replace('.flv', '.m3u8')
                    result |= {
                        "anchor_name": anchor_name,
                        "is_live": True,
                        "title": title,
                        "flv_url": flv_url,
                        "m3u8_url": m3u8_url,
                        'record_url': flv_url
                    }
                    return result

    profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
    html_str = await async_req(profile_url, proxy_addr=proxy_addr, headers=headers)
    anchor_name = re.search("<title>@(.*?) 的个人主页</title>", html_str)
    if anchor_name:
        result["anchor_name"] = anchor_name.group(1)

    return result


@trace_error_decorator
async def get_netease_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://cc.163.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies
    url = url + '/' if url[-1] != '/' else url

    html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    json_str = re.search('<script id="__NEXT_DATA__" .* crossorigin="anonymous">(.*?)</script></body>',
                         html_str, re.DOTALL).group(1)
    json_data = json.loads(json_str)
    room_data = json_data['props']['pageProps']['roomInfoInitData']
    live_data = room_data['live']
    result = {"is_live": False}
    live_status = live_data.get('status') == 1
    result["anchor_name"] = live_data.get('nickname', room_data.get('nickname'))
    if live_status:
        result |= {
            'is_live': True,
            'title': live_data['title'],
            'stream_list': live_data.get('quickplay'),
            'm3u8_url': live_data.get('sharefile')
        }
    return result


@trace_error_decorator
async def get_qiandurebo_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,'
                  'application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://qiandurebo.com/web/index.php',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    html_str = await async_req(url=url, proxy_addr=proxy_addr, headers=headers)
    data = re.search('var user = (.*?)\r\n\\s+user\\.play_url', html_str, re.DOTALL).group(1)
    anchor_name = re.findall('"zb_nickname": "(.*?)",\r\n', data)

    result = {"anchor_name": "", "is_live": False}
    if len(anchor_name) > 0:
        result['anchor_name'] = anchor_name[0]
        play_url = re.findall('"play_url": "(.*?)",\r\n', data)

        if len(play_url) > 0 and 'common-text-center" style="display:block' not in html_str:
            result |= {
                'anchor_name': anchor_name[0],
                'is_live': True,
                'flv_url': play_url[0],
                'record_url': play_url[0]
            }
    return result


@trace_error_decorator
async def get_maoerfm_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://fm.missevan.com/live/868895007',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    url2 = f'https://fm.missevan.com/api/v2/live/{room_id}'

    json_str = await async_req(url=url2, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    anchor_name = json_data['info']['creator']['username']
    live_status = False
    if 'room' in json_data['info']:
        live_status = json_data['info']['room']['status']['broadcasting']

    result = {"anchor_name": anchor_name, "is_live": live_status}
    if live_status:
        stream_list = json_data['info']['room']['channel']
        m3u8_url = stream_list['hls_pull_url']
        flv_url = stream_list['flv_pull_url']
        title = json_data['info']['room']['name']
        result |= {'is_live': True, 'title': title, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': flv_url}
    return result


def get_looklive_secret_data(text) -> tuple:
    # 本算法参考项目：https://github.com/785415581/MusicBox/blob/b8f716d43d/doc/analysis/analyze_captured_data.md

    modulus = '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee' \
              '341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe487' \
              '5d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7'
    nonce = b'0CoJUm6Qyw8W8jud'
    public_key = '010001'
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    import base64
    import binascii
    import secrets

    def create_secret_key(size: int) -> bytes:
        charset = '1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()_+-=[]{}|;:,.<>?'
        return ''.join(secrets.choice(charset) for _ in range(size)).encode('utf-8')

    def aes_encrypt(_text: str | bytes, _sec_key: str | bytes) -> bytes:
        if isinstance(_text, str):
            _text = _text.encode('utf-8')
        if isinstance(_sec_key, str):
            _sec_key = _sec_key.encode('utf-8')
        _sec_key = _sec_key[:16]  # 16 (AES-128), 24 (AES-192), or 32 (AES-256) bytes
        iv = bytes('0102030405060708', 'utf-8')
        encryptor = AES.new(_sec_key, AES.MODE_CBC, iv)
        padded_text = pad(_text, AES.block_size)
        ciphertext = encryptor.encrypt(padded_text)
        encoded_ciphertext = base64.b64encode(ciphertext)
        return encoded_ciphertext

    def rsa_encrypt(_text: str | bytes, pub_key: str, mod: str) -> str:
        if isinstance(_text, str):
            _text = _text.encode('utf-8')
        text_reversed = _text[::-1]
        text_int = int(binascii.hexlify(text_reversed), 16)
        encrypted_int = pow(text_int, int(pub_key, 16), int(mod, 16))
        return format(encrypted_int, 'x').zfill(256)

    sec_key = create_secret_key(16)
    enc_text = aes_encrypt(aes_encrypt(json.dumps(text), nonce), sec_key)
    enc_sec_key = rsa_encrypt(sec_key, public_key, modulus)
    return enc_text.decode(), enc_sec_key


async def get_looklive_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    """
    通过PC网页端的接口获取完整直播源，只有params和encSecKey这两个加密请求参数。
    params: 由两次AES加密完成
    ncSecKey: 由一次自写的加密函数完成，值可固定
    """

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Accept': 'application/json, text/javascript',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://look.163.com/',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = re.search('live\\?id=(.*?)&', url).group(1)
    params, secretkey = get_looklive_secret_data({"liveRoomNo": room_id})
    request_data = {'params': params, 'encSecKey': secretkey}
    api = 'https://api.look.163.com/weapi/livestream/room/get/v3'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers, data=request_data)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['anchor']['nickName']
    live_status = json_data['data']['liveStatus']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        result["is_live"] = True
        if json_data['data']['roomInfo']['liveType'] == 1:
            print("Look live currently only supports audio live streaming, not video live streaming!")
        else:
            play_url_list = json_data['data']['roomInfo']['liveUrl']
            live_title = json_data['data']['roomInfo']['title']
            result |= {
                "title": live_title,
                "flv_url": play_url_list['httpPullUrl'],
                "m3u8_url": play_url_list['hlsPullUrl'],
                "record_url": play_url_list['hlsPullUrl'],
            }
    return result


@trace_error_decorator
async def get_baidu_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Connection': 'keep-alive',
        'Referer': 'https://live.baidu.com/',
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }
    if cookies:
        headers['Cookie'] = cookies

    uid = random.choice([
        'h5-683e85bdf741bf2492586f7ca39bf465',
        'h5-c7c6dc14064a136be4215b452fab9eea',
        'h5-4581281f80bb8968bd9a9dfba6050d3a'
    ])
    room_id = re.search('room_id=(.*?)&', url).group(1)
    params = {
        'cmd': '371',
        'action': 'star',
        'service': 'bdbox',
        'osname': 'baiduboxapp',
        'data': '{"data":{"room_id":"' + room_id + '","device_id":"h5-683e85bdf741bf2492586f7ca39bf465",'
                                                   '"source_type":0,"osname":"baiduboxapp"},"replay_slice":0,'
                                                   '"nid":"","schemeParams":{"src_pre":"pc","src_suf":"other",'
                                                   '"bd_vid":"","share_uid":"","share_cuk":"","share_ecid":"",'
                                                   '"zb_tag":"","shareTaskInfo":"{\\"room_id\\":\\"9175031377\\"}",'
                                                   '"share_from":"","ext_params":"","nid":""}}',
        'ua': '360_740_ANDROID_0',
        'bd_vid': '',
        'uid': uid,
        '_': str(int(time.time() * 1000)),
    }
    app_api = f'https://mbd.baidu.com/searchbox?{urllib.parse.urlencode(params)}'
    json_str = await async_req(url=app_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    key = list(json_data['data'].keys())[0]
    data = json_data['data'][key]
    anchor_name = data['host']['name']
    result = {"anchor_name": anchor_name, "is_live": False}
    if data['status'] == "0":
        result["is_live"] = True
        live_title = data['video']['title']
        play_url_list = data['video']['url_clarity_list']
        url_list = []
        prefix = 'https://hls.liveshow.bdstatic.com/live/'
        if play_url_list:
            for i in play_url_list:
                url_list.append(
                    prefix + i['urls']['flv'].rsplit('.', maxsplit=1)[0].rsplit('/', maxsplit=1)[1] + '.m3u8')
        else:
            play_url_list = data['video']['url_list']
            for i in play_url_list:
                url_list.append(prefix + i['urls'][0]['hls'].rsplit('?', maxsplit=1)[0].rsplit('/', maxsplit=1)[1])

        if url_list:
            result |= {"is_live": True, "title": live_title, 'play_url_list': url_list}
    return result


@trace_error_decorator
async def get_weibo_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Cookie': '',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        'Referer': 'https://weibo.com/u/5885340893'
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = ''
    if 'show/' in url:
        room_id = url.split('?')[0].split('show/')[1]
    else:
        uid = url.split('?')[0].rsplit('/u/', maxsplit=1)[1]
        web_api = f'https://weibo.com/ajax/statuses/mymblog?uid={uid}&page=1&feature=0'
        json_str = await async_req(web_api, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        for i in json_data['data']['list']:
            if 'page_info' in i and i['page_info']['object_type'] == 'live':
                room_id = i['page_info']['object_id']
                break

    result = {"anchor_name": '', "is_live": False}
    if room_id:
        app_api = f'https://weibo.com/l/pc/anchor/live?live_id={room_id}'
        # app_api = f'https://weibo.com/l/!/2/wblive/room/show_pc_live.json?live_id={room_id}'
        json_str = await async_req(url=app_api, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        anchor_name = json_data['data']['user_info']['name']
        result["anchor_name"] = anchor_name
        live_status = json_data['data']['item']['status']
        if live_status == 1:
            result["is_live"] = True
            live_title = json_data['data']['item']['desc']
            play_url_list = json_data['data']['item']['stream_info']['pull']
            m3u8_url = play_url_list['live_origin_hls_url']
            flv_url = play_url_list['live_origin_flv_url']
            result['title'] = live_title
            result['play_url_list'] = [
                {"m3u8_url": m3u8_url, "flv_url": flv_url},
                {"m3u8_url": m3u8_url.split('_')[0] + '.m3u8', "flv_url": flv_url.split('_')[0] + '.flv'}
            ]
    return result


@trace_error_decorator
async def get_kugou_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
        'Accept': 'application/json',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://fanxing2.kugou.com/',
    }
    if cookies:
        headers['Cookie'] = cookies

    if 'roomId' in url:
        room_id = re.search('roomId=(\\d+)', url).group(1)
    else:
        room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]

    app_api = f'https://service2.fanxing.kugou.com/roomcen/room/web/cdn/getEnterRoomInfo?roomId={room_id}'
    json_str = await async_req(url=app_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['normalRoomInfo']['nickName']
    result = {"anchor_name": anchor_name, "is_live": False}
    if not anchor_name:
        raise RuntimeError(
            "Music channel live rooms are not supported for recording, please switch to a different live room."
        )
    live_status = json_data['data']['liveType']
    if live_status != -1:
        params = {
            'std_rid': room_id,
            'std_plat': '7',
            'std_kid': '0',
            'streamType': '1-2-4-5-8',
            'ua': 'fx-flash',
            'targetLiveTypes': '1-5-6',
            'version': '1000',
            'supportEncryptMode': '1',
            'appid': '1010',
            '_': str(int(time.time() * 1000)),
        }
        api = f'https://fx1.service.kugou.com/video/pc/live/pull/mutiline/streamaddr?{urllib.parse.urlencode(params)}'
        json_str2 = await async_req(api, proxy_addr=proxy_addr, headers=headers)
        json_data2 = json.loads(json_str2)
        stream_data = json_data2['data']['lines']
        if stream_data:
            flv_url = stream_data[-1]['streamProfiles'][0]['httpsFlv'][0]
            result |= {"is_live": True, "flv_url": flv_url, "record_url": flv_url}
    return result


async def get_huajiao_sn(url: str, cookies: OptionalStr = None, proxy_addr: OptionalStr = None) -> tuple | None:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://www.huajiao.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }

    if cookies:
        headers['Cookie'] = cookies

    live_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    api = f'https://www.huajiao.com/l/{live_id}'
    try:
        html_str = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
        json_str = re.search('var feed = (.*?});', html_str).group(1)
        json_data = json.loads(json_str)
        sn = json_data['feed']['sn']
        uid = json_data['author']['uid']
        nickname = json_data['author']['nickname']
        live_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
        return nickname, sn, uid, live_id
    except Exception:
        utils.replace_url(f'{script_path}/config/URL_config.ini', old=url, new='#' + url)
        raise RuntimeError("Failed to retrieve live room data, the Huajiao live room address is not fixed, please use "
                           "the anchor's homepage address for recording.")


async def get_huajiao_user_info(url: str, cookies: OptionalStr = None, proxy_addr: OptionalStr = None) -> OptionalDict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://www.huajiao.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }

    if cookies:
        headers['Cookie'] = cookies

    if 'user' in url:
        uid = url.split('?')[0].split('user/')[1]
        params = {
            'uid': uid,
            'fmt': 'json',
            '_': str(int(time.time() * 1000)),
        }

        api = f'https://webh.huajiao.com/User/getUserFeeds?{urllib.parse.urlencode(params)}'
        json_str = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)

        html_str = await async_req(url=f'https://www.huajiao.com/user/{uid}', proxy_addr=proxy_addr, headers=headers)
        anchor_name = re.search('<title>(.*?)的主页.*</title>', html_str).group(1)
        if json_data['data'] and 'sn' in json_data['data']['feeds'][0]['feed']:
            feed = json_data['data']['feeds'][0]['feed']
            return {
                "anchor_name": anchor_name,
                "title": feed['title'],
                "is_live": True,
                "sn": feed['sn'],
                "liveid": feed['relateid'],
                "uid": uid
            }
        else:
            return {"anchor_name": anchor_name, "is_live": False}


async def get_huajiao_stream_url_app(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> OptionalDict:
    headers = {
        'User-Agent': 'living/9.4.0 (com.huajiao.seeding; build:2410231746; iOS 17.0.0) Alamofire/9.4.0',
        'accept-language': 'zh-Hans-US;q=1.0',
        'sdk_version': '1',
    }
    if cookies:
        headers['Cookie'] = cookies
    room_id = url.rsplit('/', maxsplit=1)[1]
    api = f'https://live.huajiao.com/feed/getFeedInfo?relateid={room_id}'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    if json_data['errmsg'] or not json_data['data'].get('creatime'):
        print("Failed to retrieve live room data, the Huajiao live room address is not fixed, please manually change "
              "the address for recording.")
        return
    data = json_data['data']
    return {
        "anchor_name": data['author']['nickname'],
        "title": data['feed']['title'],
        "is_live": True,
        "sn": data['feed']['sn'],
        "liveid": data['feed']['relateid'],
        "uid": data['author']['uid']
    }


@trace_error_decorator
async def get_huajiao_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://www.huajiao.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    result = {"anchor_name": "", "is_live": False}

    if 'user/' in url:
        if not cookies:
            return result
        room_data = await get_huajiao_user_info(url, cookies, proxy_addr)
    else:
        url = await async_req(url, proxy_addr=proxy_addr, headers=headers, redirect_url=True)
        if url.rstrip('/') == 'https://www.huajiao.com':
            print(
                "Failed to retrieve live room data, the Huajiao live room address is not fixed, please manually change "
                "the address for recording.")
            return result
        room_data = await get_huajiao_stream_url_app(url, proxy_addr)

    if room_data:
        result["anchor_name"] = room_data.pop("anchor_name")
        live_status = room_data.pop("is_live")

        if live_status:
            result["title"] = room_data.pop("title")
            params = {
                "time": int(time.time() * 1000),
                "version": "1.0.0",
                **room_data,
                "encode": "h265"
            }

            api = f'https://live.huajiao.com/live/substream?{urllib.parse.urlencode(params)}'
            json_str = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
            json_data = json.loads(json_str)
            result |= {
                'is_live': True,
                'flv_url': json_data['data']['h264_url'],
                'record_url': json_data['data']['h264_url'],
            }
    return result


@trace_error_decorator
async def get_liuxing_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Referer': 'https://wap.7u66.com/198189?promoters=0',
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',

    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    params = {
        "promoters": "0",
        "roomidx": room_id,
        "currentUrl": f"https://www.7u66.com/{room_id}?promoters=0"
    }
    api = f'https://wap.7u66.com/api/ui/room/v1.0.0/live.ashx?{urllib.parse.urlencode(params)}'
    json_str = await async_req(url=api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    room_info = json_data['data']['roomInfo']
    anchor_name = room_info['nickname']
    live_status = room_info["live_stat"]
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        idx = room_info['idx']
        live_id = room_info['liveId1']
        flv_url = f'https://txpull1.5see.com/live/{idx}/{live_id}.flv'
        result |= {'is_live': True, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_showroom_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    if '/room/profile' in url:
        room_id = url.split('room_id=')[-1]
    else:
        html_str = await async_req(url, proxy_addr=proxy_addr, headers=headers, abroad=True)
        room_id = re.search('href="/room/profile\\?room_id=(.*?)"', html_str).group(1)
    info_api = f'https://www.showroom-live.com/api/live/live_info?room_id={room_id}'
    json_str = await async_req(info_api, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)
    anchor_name = json_data['room_name']
    result = {"anchor_name": anchor_name, "is_live": False}
    live_status = json_data['live_status']
    if live_status == 2:
        result["is_live"] = True
        web_api = f'https://www.showroom-live.com/api/live/streaming_url?room_id={room_id}&abr_available=1'
        json_str = await async_req(web_api, proxy_addr=proxy_addr, headers=headers, abroad=True)
        if json_str:
            json_data = json.loads(json_str)
            streaming_url_list = json_data['streaming_url_list']

            for i in streaming_url_list:
                if i['type'] == 'hls_all':
                    m3u8_url = i['url']
                    result['m3u8_url'] = m3u8_url
                    if m3u8_url:
                        m3u8_url_list = await get_play_url_list(m3u8_url, proxy=proxy_addr, header=headers, abroad=True)
                        if m3u8_url_list:
                            result['play_url_list'] = [f"{m3u8_url.rsplit('/', maxsplit=1)[0]}/{i}" for i in
                                                       m3u8_url_list]
                        else:
                            result['play_url_list'] = [m3u8_url]
                        result['play_url_list'] = [i.replace('https://', 'http://') for i in result['play_url_list']]
                        break
    return result


@trace_error_decorator
async def get_acfun_sign_params(proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> tuple:
    did = f'web_{utils.generate_random_string(16)}'
    headers = {
        'referer': 'https://live.acfun.cn/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'cookie': f'_did={did};',
    }
    if cookies:
        headers['Cookie'] = cookies
    data = {
        'sid': 'acfun.api.visitor',
    }
    api = 'https://id.app.acfun.cn/rest/app/visitor/login'
    json_str = await async_req(api, data=data, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    user_id = json_data["userId"]
    visitor_st = json_data["acfun.api.visitor_st"]
    return user_id, did, visitor_st


@trace_error_decorator
async def get_acfun_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'referer': 'https://live.acfun.cn/live/17912421',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    author_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    user_info_api = f'https://live.acfun.cn/rest/pc-direct/user/userInfo?userId={author_id}'
    json_str = await async_req(user_info_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['profile']['name']
    status = 'liveId' in json_data['profile']
    result = {"anchor_name": anchor_name, "is_live": False}
    if status:
        result["is_live"] = True
        user_id, did, visitor_st = await get_acfun_sign_params(proxy_addr=proxy_addr, cookies=cookies)
        params = {
            'subBiz': 'mainApp',
            'kpn': 'ACFUN_APP',
            'kpf': 'PC_WEB',
            'userId': user_id,
            'did': did,
            'acfun.api.visitor_st': visitor_st,
        }

        data = {
            'authorId': author_id,
            'pullStreamType': 'FLV',
        }
        play_api = f'https://api.kuaishouzt.com/rest/zt/live/web/startPlay?{urllib.parse.urlencode(params)}'
        json_str = await async_req(play_api, data=data, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        live_title = json_data['data']['caption']
        videoPlayRes = json_data['data']['videoPlayRes']
        play_url_list = json.loads(videoPlayRes)['liveAdaptiveManifest'][0]['adaptationSet']['representation']
        play_url_list = sorted(play_url_list, key=itemgetter('bitrate'), reverse=True)
        result |= {'play_url_list': play_url_list, 'title': live_title}
    return result


@trace_error_decorator
async def get_changliao_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://wap.tlclw.com/phone/15777?promoters=0',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    params = {
        'roomidx': room_id,
        'currentUrl': f'https://wap.tlclw.com/{room_id}',
    }
    play_api = f'https://wap.tlclw.com/api/ui/room/v1.0.0/live.ashx?{urllib.parse.urlencode(params)}'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['roomInfo']['nickname']
    live_status = json_data['data']['roomInfo']['live_stat']

    async def get_live_domain(page_url):
        html_str = await async_req(page_url, proxy_addr=proxy_addr, headers=headers)
        config_json_str = re.findall("var config = (.*?)config.webskins",
                                     html_str, re.DOTALL)[0].rsplit(";", maxsplit=1)[0].strip()
        config_json_data = json.loads(config_json_str)
        stream_flv_domain = config_json_data['domainpullstream_flv']
        stream_hls_domain = config_json_data['domainpullstream_hls']
        return stream_flv_domain, stream_hls_domain

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        flv_domain, hls_domain = await get_live_domain(url)
        live_id = json_data['data']['roomInfo']['liveID']
        flv_url = f'{flv_domain}/{live_id}.flv'
        m3u8_url = f'{hls_domain}/{live_id}.m3u8'
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_yingke_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Referer': 'https://www.inke.cn/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    parsed_url = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    uid = query_params['uid'][0]
    live_id = query_params['id'][0]
    params = {
        'uid': uid,
        'id': live_id,
        '_t': str(int(time.time())),
    }

    api = f'https://webapi.busi.inke.cn/web/live_share_pc?{urllib.parse.urlencode(params)}'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['media_info']['nick']
    live_status = json_data['data']['status']

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        m3u8_url = json_data['data']['live_addr'][0]['hls_stream_addr']
        flv_url = json_data['data']['live_addr'][0]['stream_addr']
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': m3u8_url}
    return result


@trace_error_decorator
async def get_yinbo_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        'Referer': 'https://live.ybw1666.com/800005143?promoters=0',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    params = {
        'roomidx': room_id,
        'currentUrl': f'https://wap.ybw1666.com/{room_id}',
    }
    play_api = f'https://wap.ybw1666.com/api/ui/room/v1.0.0/live.ashx?{urllib.parse.urlencode(params)}'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    room_data = json_data['data']['roomInfo']
    anchor_name = room_data['nickname']
    live_status = room_data['live_stat']

    async def get_live_domain(page_url):
        html_str = await async_req(page_url, proxy_addr=proxy_addr, headers=headers)
        config_json_str = re.findall("var config = (.*?)config.webskins",
                                     html_str, re.DOTALL)[0].rsplit(";", maxsplit=1)[0].strip()
        config_json_data = json.loads(config_json_str)
        stream_flv_domain = config_json_data['domainpullstream_flv']
        stream_hls_domain = config_json_data['domainpullstream_hls']
        return stream_flv_domain, stream_hls_domain

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        flv_domain, hls_domain = await get_live_domain(url)
        live_id = room_data['liveID']
        flv_url = f'{flv_domain}/{live_id}.flv'
        m3u8_url = f'{hls_domain}/{live_id}.m3u8'
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_zhihu_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    if 'people/' in url:
        user_id = url.split('people/')[1]
        api = f'https://api.zhihu.com/people/{user_id}/profile?profile_new_version='
        json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
        json_data = json.loads(json_str)
        live_page_url = json_data['drama']['living_theater']['theater_url']
    else:
        live_page_url = url

    web_id = live_page_url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    html_str = await async_req(live_page_url, proxy_addr=proxy_addr, headers=headers)
    json_str2 = re.findall('<script id="js-initialData" type="text/json">(.*?)</script>', html_str)[0]
    json_data2 = json.loads(json_str2)
    live_data = json_data2['initialState']['theater']['theaters'][web_id]
    anchor_name = live_data['actor']['name']
    live_status = live_data['drama']['status']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        live_title = live_data['theme']
        play_url = live_data['drama']['playInfo']
        result |= {
            'is_live': True,
            'title': live_title,
            'm3u8_url': play_url['hlsUrl'],
            'flv_url': play_url['playUrl'],
            'record_url': play_url['hlsUrl']
        }
    return result


@trace_error_decorator
async def get_chzzk_stream_data(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'origin': 'https://chzzk.naver.com',
        'referer': 'https://chzzk.naver.com/live/458f6ec20b034f49e0fc6d03921646d2',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    play_api = f'https://api.chzzk.naver.com/service/v3/channels/{room_id}/live-detail'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)
    live_data = json_data['content']
    anchor_name = live_data['channel']['channelName']
    live_status = live_data['status']

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 'OPEN':
        play_data = json.loads(live_data['livePlaybackJson'])
        m3u8_url = play_data['media'][0]['path']
        m3u8_url_list = await get_play_url_list(m3u8_url, proxy=proxy_addr, header=headers, abroad=True)
        prefix = m3u8_url.split('?')[0].rsplit('/', maxsplit=1)[0]
        m3u8_url_list = [prefix + '/' + i for i in m3u8_url_list]
        result |= {"is_live": True, "m3u8_url": m3u8_url, "play_url_list": m3u8_url_list}
    return result


@trace_error_decorator
async def get_haixiu_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'origin': 'https://www.haixiutv.com',
        'referer': 'https://www.haixiutv.com/',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }
    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split("?")[0].rsplit('/', maxsplit=1)[-1]
    if 'haixiutv' in url:
        access_token = "pLXSC%252FXJ0asc1I21tVL5FYZhNJn2Zg6d7m94umCnpgL%252BuVm31GQvyw%253D%253D"
    else:
        access_token = "s7FUbTJ%252BjILrR7kicJUg8qr025ZVjd07DAnUQd8c7g%252Fo4OH9pdSX6w%253D%253D"

    params = {
        "accessToken": access_token,
        "tku": "3000006",
        "c": "10138100100000",
        "_st1": int(time.time() * 1000)
    }
    ajax_data = execjs.compile(open(f'{JS_SCRIPT_PATH}/haixiu.js').read()).call('sign', params,
                                                                                f'{JS_SCRIPT_PATH}/crypto-js.min.js')

    params["accessToken"] = urllib.parse.unquote(urllib.parse.unquote(access_token))
    params['_ajaxData1'] = ajax_data
    params['_'] = int(time.time() * 1000)

    if 'haixiutv' in url:
        api = f'https://service.haixiutv.com/v2/room/{room_id}/media/advanceInfoRoom?{urllib.parse.urlencode(params)}'
    else:
        headers['origin'] = 'https://www.lehaitv.com'
        headers['referer'] = 'https://www.lehaitv.com'
        api = f'https://service.lehaitv.com/v2/room/{room_id}/media/advanceInfoRoom?{urllib.parse.urlencode(params)}'

    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)

    stream_data = json_data['data']
    anchor_name = stream_data['nickname']
    live_status = stream_data['live_status']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        flv_url = stream_data['media_url_web']
        result |= {'is_live': True, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_vvxqiu_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
        'Access-Control-Request-Method': 'GET',
        'Origin': 'https://h5webcdn-pro.vvxqiu.com',
        'Referer': 'https://h5webcdn-pro.vvxqiu.com/',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = get_params(url, "roomId")
    api_1 = f'https://h5p.vvxqiu.com/activity-center/fanclub/activity/captain/banner?roomId={room_id}&product=vvstar'
    json_str = await async_req(api_1, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data['data']['anchorName']
    if not anchor_name:
        params = {
            'sessionId': '',
            'userId': '',
            'product': 'vvstar',
            'tickToken': '',
            'roomId': room_id,
        }
        json_str = await async_req(
            f'https://h5p.vvxqiu.com/activity-center/halloween2023/banner?{urllib.parse.urlencode(params)}',
            proxy_addr=proxy_addr, headers=headers
        )
        json_data = json.loads(json_str)
        anchor_name = json_data['data']['memberVO']['memberName']

    result = {"anchor_name": anchor_name, "is_live": False}
    m3u8_url = f'https://liveplay-pro.wasaixiu.com/live/1400442770_{room_id}_{room_id[2:]}_single.m3u8'
    resp = await async_req(m3u8_url, proxy_addr=proxy_addr, headers=headers)
    if 'Not Found' not in resp:
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'record_url': m3u8_url}
    return result


@trace_error_decorator
async def get_17live_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'origin': 'https://17.live',
        'referer': 'https://17.live/',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    api_1 = f'https://wap-api.17app.co/api/v1/user/room/{room_id}'
    json_str = await async_req(api_1, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    anchor_name = json_data["displayName"]
    result = {"anchor_name": anchor_name, "is_live": False}
    json_data = {
        'liveStreamID': room_id,
    }
    api_1 = f'https://wap-api.17app.co/api/v1/lives/{room_id}/viewers/alive'
    json_str = await async_req(api_1, json_data=json_data, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    live_status = json_data.get("status")
    if live_status and live_status == 2:
        flv_url = json_data['pullURLsInfo']['rtmpURLs'][0]['urlHighQuality']
        result |= {'is_live': True, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_langlive_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'origin': 'https://www.lang.live',
        'referer': 'https://www.lang.live/',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[-1]
    api_1 = f'https://api.lang.live/langweb/v1/room/liveinfo?room_id={room_id}'
    json_str = await async_req(api_1, proxy_addr=proxy_addr, headers=headers, abroad=True)
    json_data = json.loads(json_str)
    live_info = json_data['data']['live_info']
    anchor_name = live_info['nickname']
    live_status = live_info['live_status']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        flv_url = json_data['data']['live_info']['liveurl']
        m3u8_url = json_data['data']['live_info']['liveurl_hls']
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': m3u8_url}
    return result


@trace_error_decorator
async def get_pplive_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'Content-Type': 'application/json',
        'Origin': 'https://m.pp.weimipopo.com',
        'Referer': 'https://m.pp.weimipopo.com/',
        'User-Agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = get_params(url, 'anchorUid')
    json_data = {
        'inviteUuid': '',
        'anchorUuid': room_id,
    }

    if 'catshow' in url:
        api = 'https://api.catshow168.com/live/preview'
        headers['Origin'] = 'https://h.catshow168.com'
        headers['Referer'] = 'https://h.catshow168.com'
    else:
        api = 'https://api.pp.weimipopo.com/live/preview'
    json_str = await async_req(api, json_data=json_data, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    live_info = json_data['data']
    anchor_name = live_info['name']
    live_status = live_info['living']
    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status:
        m3u8_url = live_info['pullUrl']
        result |= {'is_live': True, 'm3u8_url': m3u8_url, 'record_url': m3u8_url}
    return result


@trace_error_decorator
async def get_6room_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'referer': 'https://ios.6.cn/?ver=8.0.3&build=4',
        'user-agent': 'ios/7.830 (ios 17.0; ; iPhone 15 (A2846/A3089/A3090/A3092))',
    }

    if cookies:
        headers['Cookie'] = cookies

    room_id = url.split('?')[0].rsplit('/', maxsplit=1)[1]
    html_str = await async_req(f'https://v.6.cn/{room_id}', proxy_addr=proxy_addr, headers=headers)
    room_id = re.search('rid: \'(.*?)\',\n\\s+roomid', html_str).group(1)
    data = {
        'av': '3.1',
        'encpass': '',
        'logiuid': '',
        'project': 'v6iphone',
        'rate': '1',
        'rid': '',
        'ruid': room_id,
    }
    api = 'https://v.6.cn/coop/mobile/index.php?padapi=coop-mobile-inroom.php'
    json_str = await async_req(api, data=data, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    flv_title = json_data['content']['liveinfo']['flvtitle']
    anchor_name = json_data['content']['roominfo']['alias']
    result = {"anchor_name": anchor_name, "is_live": False}
    if flv_title:
        flv_url = f'https://wlive.6rooms.com/httpflv/{flv_title}.flv'
        result |= {'is_live': True, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_migu_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
            'origin': 'https://www.miguvideo.com',
            'referer': 'https://www.miguvideo.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
            'appCode': 'miguvideo_default_www',
            'appId': 'miguvideo',
            'channel': 'H5',
        }

    if cookies:
        headers['Cookie'] = cookies

    web_id = url.split('?')[0].rsplit('/')[-1]
    api = f'https://vms-sc.miguvideo.com/vms-match/v6/staticcache/basic/basic-data/{web_id}/miguvideo'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    anchor_name = json_data['body']['title']
    live_title = json_data['body'].get('title') + '-' + json_data['body'].get('detailPageTitle', '')
    room_id = json_data['body'].get('pId')

    result = {"anchor_name": anchor_name, "is_live": False}
    if not room_id:
        return result

    params = {
        'contId': room_id,
        'rateType': '3',
        'clientId': str(uuid.uuid4()),
        'timestamp': int(time.time() * 1000),
        'flvEnable': 'true',
        'xh265': 'false',
        'chip': 'mgwww',
        'channelId': '',
    }

    api = f'https://webapi.miguvideo.com/gateway/playurl/v3/play/playurl?{urllib.parse.urlencode(params)}'
    json_str = await async_req(api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)
    live_status = json_data['body']['content']['currentLive']
    if live_status != '1':
        return result
    else:
        result['title'] = live_title
        source_url = json_data['body']['urlInfo']['url']

        async def _get_dd_calcu(url):
            try:
                result = subprocess.run(
                    ["node", f"{JS_SCRIPT_PATH}/migu.js", url],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result.stdout.strip()
            except execjs.ProgramError:
                raise execjs.ProgramError('Failed to execute JS code. Please check if the Node.js environment')

        ddCalcu = await _get_dd_calcu(source_url)
        real_source_url = f'{source_url}&ddCalcu={ddCalcu}&sv=10010'
        if '.m3u8' in real_source_url:
            m3u8_url = await async_req(
                real_source_url, proxy_addr=proxy_addr, headers=headers, redirect_url=True)
            result['m3u8_url'] = m3u8_url
            result['record_url'] = m3u8_url
        else:
            result['flv_url'] = real_source_url
            result['record_url'] = real_source_url
        result['is_live'] = True
    return result


@trace_error_decorator
async def get_lianjie_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
            'accept-language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
        }

    if cookies:
        headers['cookie'] = cookies

    room_id = url.split('?')[0].rsplit('lailianjie.com/', maxsplit=1)[-1]
    play_api = f'https://api.lailianjie.com/ApiServices/service/live/getRoomInfo?&_$t=&_sign=&roomNumber={room_id}'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    room_data = json_data['data']
    anchor_name = room_data['nickname']
    live_status = room_data['isonline']

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status == 1:
        title = room_data['defaultRoomTitle']
        webrtc_url = room_data['videoUrl']
        https_url = "https://" + webrtc_url.split('webrtc://')[1]
        flv_url = https_url.replace('?', '.flv?')
        m3u8_url = https_url.replace('?', '.m3u8?')
        result |= {'is_live': True, 'title': title, 'm3u8_url': m3u8_url, 'flv_url': flv_url, 'record_url': flv_url}
    return result


@trace_error_decorator
async def get_laixiu_stream_url(url: str, proxy_addr: OptionalStr = None, cookies: OptionalStr = None) -> dict:
    def generate_uuid(ua_type: str):
        if ua_type == "mobile":
            return str(uuid.uuid4())
        return str(uuid.uuid4()).replace('-', '')

    def calculate_sign(ua_type: str = 'pc'):
        a = int(time.time() * 1000)
        s = generate_uuid(ua_type)
        u = 'kk792f28d6ff1f34ec702c08626d454b39pro'

        input_str = f"web{s}{a}{u}"
        md5_hash = hashlib.md5(input_str.encode('utf-8')).hexdigest()

        return {
            'timestamp': a,
            'imei': s,
            'requestId': md5_hash,
            'inputString': input_str
        }

    sign_data = calculate_sign(ua_type='pc')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0',
        'mobileModel': 'web',
        'timestamp': str(sign_data['timestamp']),
        'loginType': '2',
        'versionCode': '10003',
        'imei': sign_data['imei'],
        'requestId': sign_data['requestId'],
        'channel': '9',
        'version': '1.0.0',
        'os': 'web',
        'platform': 'WEB',
        'Origin': 'https://www.imkktv.com',
        'Referer': 'https://www.imkktv.com/',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    }

    if cookies:
        headers['cookie'] = cookies

    pattern = r"(?:roomId|anchorId)=(.*?)(?=&|$)"
    match = re.search(pattern, url)
    room_id = match.group(1) if match else ''
    play_api = f'https://api.imkktv.com/liveroom/getShareLiveVideo?roomId={room_id}'
    json_str = await async_req(play_api, proxy_addr=proxy_addr, headers=headers)
    json_data = json.loads(json_str)

    room_data = json_data['data']
    anchor_name = room_data['nickname']
    live_status = room_data['playStatus'] == 0

    result = {"anchor_name": anchor_name, "is_live": False}
    if live_status:
        flv_url = room_data['playUrl']
        result |= {'is_live': True, 'flv_url': flv_url, 'record_url': flv_url}
    return result


def get_params(url: str, params: str) -> OptionalStr:
    parsed_url = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed_url.query)

    if params in query_params:
        return query_params[params][0]


async def get_play_url_list(m3u8: str, proxy: OptionalStr = None, header: OptionalDict = None,
                            abroad: bool = False) -> List[str]:
    resp = await async_req(url=m3u8, proxy_addr=proxy, headers=header, abroad=abroad)
    play_url_list = []
    for i in resp.split('\n'):
        if i.startswith('https://'):
            play_url_list.append(i.strip())
    if not play_url_list:
        for i in resp.split('\n'):
            if i.strip().endswith('m3u8'):
                play_url_list.append(i.strip())
    bandwidth_pattern = re.compile(r'BANDWIDTH=(\d+)')
    bandwidth_list = bandwidth_pattern.findall(resp)
    url_to_bandwidth = {url: int(bandwidth) for bandwidth, url in zip(bandwidth_list, play_url_list)}
    play_url_list = sorted(play_url_list, key=lambda url: url_to_bandwidth[url], reverse=True)
    return play_url_list


def md5(data) -> str:
    return hashlib.md5(data.encode('utf-8')).hexdigest()


async def get_token_js(rid: str, did: str, proxy_addr: OptionalStr = None) -> List[str]:

    url = f'https://www.douyu.com/{rid}'
    html_str = await async_req(url=url, proxy_addr=proxy_addr)
    result = re.search(r'(vdwdae325w_64we[\s\S]*function ub98484234[\s\S]*?)function', html_str).group(1)
    func_ub9 = re.sub(r'eval.*?;}', 'strc;}', result)
    js = execjs.compile(func_ub9)
    res = js.call('ub98484234')

    t10 = str(int(time.time()))
    v = re.search(r'v=(\d+)', res).group(1)
    rb = md5(rid + did + t10 + v)

    func_sign = re.sub(r'return rt;}\);?', 'return rt;}', res)
    func_sign = func_sign.replace('(function (', 'function sign(')
    func_sign = func_sign.replace('CryptoJS.MD5(cb).toString()', '"' + rb + '"')

    js = execjs.compile(func_sign)
    params = js.call('sign', rid, did, t10)
    params_list = re.findall('=(.*?)(?=&|$)', params)
    return params_list

