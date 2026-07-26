# -*- encoding: utf-8 -*-

"""
Author: Hmily
GitHub: https://github.com/ihmily
Date: 2023-07-15 23:15:00
Update: 2025-02-06 02:28:00
Copyright (c) 2023-2025 by Hmily, All Rights Reserved.
Function: Get live stream data.
"""
import base64
import hashlib
import json
import time
import random
import re
from operator import itemgetter
import urllib.parse
import urllib.request
from .utils import trace_error_decorator
from .spider import (
    get_douyu_stream_data, get_bilibili_stream_data
)
from .http_clients.async_http import get_response_status

QUALITY_MAPPING = {"OD": 0, "BD": 0, "UHD": 1, "HD": 2, "SD": 3, "LD": 4}


def get_quality_index(quality) -> tuple:
    if not quality:
        return list(QUALITY_MAPPING.items())[0]

    quality_str = str(quality).upper()
    if quality_str.isdigit():
        quality_int = int(quality_str[0])
        quality_str = list(QUALITY_MAPPING.keys())[quality_int]
    return quality_str, QUALITY_MAPPING.get(quality_str, 0)


def _pad_to_five(url_list: list) -> list:
    """不足 5 项时用最后一项填充（质量索引固定 0-4）"""
    while len(url_list) < 5:
        url_list.append(url_list[-1])
    return url_list


def _tiktok_get_video_quality_url(stream: dict, q_key: str) -> list:
    """解析 TikTok 流地址，按码率+分辨率降序"""
    play_list = []
    for key in stream:
        url_info = stream[key]['main']
        sdk_params = json.loads(url_info['sdk_params'])
        vbitrate = int(sdk_params['vbitrate'])
        v_codec = sdk_params.get('VCodec', '')

        play_url = ''
        if url_info.get(q_key):
            if url_info[q_key].endswith(".flv") or url_info[q_key].endswith(".m3u8"):
                play_url = url_info[q_key] + '?codec=' + v_codec
            else:
                play_url = url_info[q_key] + '&codec=' + v_codec

        resolution = sdk_params['resolution']
        if vbitrate != 0 and resolution:
            width, height = map(int, resolution.split('x'))
            play_list.append({'url': play_url, 'vbitrate': vbitrate, 'resolution': (width, height)})

    play_list.sort(key=itemgetter('vbitrate'), reverse=True)
    play_list.sort(key=lambda x: (-x['vbitrate'], -x['resolution'][0], -x['resolution'][1]))
    return play_list


def _huya_get_anti_code(old_anti_code: str, stream_name: str) -> str:
    """生成虎牙 anti_code 签名

    js地址：https://hd.huya.com/cdn_libs/mobile/hysdk-m-202402211431.js
    """
    params_t = 100
    sdk_version = 2403051612

    t13 = int(time.time()) * 1000
    sdk_sid = t13

    init_uuid = (int(t13 % 10 ** 10 * 1000) + int(1000 * random.random())) % 4294967295
    uid = random.randint(1400000000000, 1400009999999)
    seq_id = uid + sdk_sid

    target_unix_time = (t13 + 110624) // 1000
    ws_time = f"{target_unix_time:x}".lower()

    url_query = urllib.parse.parse_qs(old_anti_code)
    ws_secret_pf = base64.b64decode(urllib.parse.unquote(url_query['fm'][0]).encode()).decode().split("_")[0]
    ws_secret_hash = hashlib.md5(f'{seq_id}|{url_query["ctype"][0]}|{params_t}'.encode()).hexdigest()
    ws_secret = f'{ws_secret_pf}_{uid}_{stream_name}_{ws_secret_hash}_{ws_time}'
    ws_secret_md5 = hashlib.md5(ws_secret.encode()).hexdigest()

    return (
        f'wsSecret={ws_secret_md5}&wsTime={ws_time}&seqid={seq_id}&ctype={url_query["ctype"][0]}&ver=1'
        f'&fs={url_query["fs"][0]}&uuid={init_uuid}&u={uid}&t={params_t}&sv={sdk_version}'
        f'&sdk_sid={sdk_sid}&codec=264'
    )


def _huya_apply_quality(flv_url: str, m3u8_url: str, flv_anti_code: str, video_quality: str) -> tuple:
    """虎牙按质量档位拼接 ratio 参数"""
    quality_list = flv_anti_code.split('&exsphd=')
    if len(quality_list) <= 1 or video_quality in ["OD", "BD"]:
        return flv_url, m3u8_url

    pattern = r"(?<=264_)\d+"
    quality_list = list(re.findall(pattern, quality_list[1]))[::-1]
    quality_list = _pad_to_five(quality_list)

    video_quality_options = {
        "UHD": quality_list[0],
        "HD": quality_list[1],
        "SD": quality_list[2],
        "LD": quality_list[3]
    }

    if video_quality not in video_quality_options:
        raise ValueError(
            f"Invalid video quality. Available options are: {', '.join(video_quality_options.keys())}")

    ratio = str(video_quality_options[video_quality])
    return flv_url + ratio, m3u8_url + ratio


@trace_error_decorator
async def get_douyin_stream_url(json_data: dict, video_quality: str, proxy_addr: str) -> dict:
    anchor_name = json_data.get('anchor_name')

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    status = json_data.get("status", 4)

    if status == 2:
        stream_url = json_data['stream_url']
        flv_url_dict = stream_url['flv_pull_url']
        flv_url_list: list = list(flv_url_dict.values())
        m3u8_url_dict = stream_url['hls_pull_url_map']
        m3u8_url_list: list = list(m3u8_url_dict.values())

        while len(flv_url_list) < 5:
            flv_url_list.append(flv_url_list[-1])
            m3u8_url_list.append(m3u8_url_list[-1])

        video_quality, quality_index = get_quality_index(video_quality)
        m3u8_url = m3u8_url_list[quality_index]
        flv_url = flv_url_list[quality_index]
        ok = await get_response_status(url=m3u8_url, proxy_addr=proxy_addr)
        if not ok:
            index = quality_index + 1 if quality_index < 4 else quality_index - 1
            m3u8_url = m3u8_url_list[index]
            flv_url = flv_url_list[index]
        result |= {
            'is_live': True,
            'title': json_data['title'],
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': m3u8_url or flv_url,
        }
    return result


@trace_error_decorator
async def get_tiktok_stream_url(json_data: dict, video_quality: str, proxy_addr: str) -> dict:
    if not json_data:
        return {"anchor_name": None, "is_live": False}

    live_room = json_data['LiveRoom']['liveRoomUserInfo']
    user = live_room['user']
    anchor_name = f"{user['nickname']}-{user['uniqueId']}"
    status = user.get("status", 4)

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    if status == 2:
        stream_data = live_room['liveRoom']['streamData']['pull_data']['stream_data']
        stream_data = json.loads(stream_data).get('data', {})
        flv_url_list = _pad_to_five(_tiktok_get_video_quality_url(stream_data, 'flv'))
        m3u8_url_list = _pad_to_five(_tiktok_get_video_quality_url(stream_data, 'hls'))

        video_quality, quality_index = get_quality_index(video_quality)
        flv_dict: dict = flv_url_list[quality_index]
        m3u8_dict: dict = m3u8_url_list[quality_index]

        check_url = m3u8_dict.get('url') or flv_dict.get('url')
        ok = await get_response_status(url=check_url, proxy_addr=proxy_addr, http2=False)

        if not ok:
            index = quality_index + 1 if quality_index < 4 else quality_index - 1
            flv_dict: dict = flv_url_list[index]
            m3u8_dict: dict = m3u8_url_list[index]

        flv_url = flv_dict['url']
        m3u8_url = m3u8_dict['url']
        result |= {
            'is_live': True,
            'title': live_room['liveRoom']['title'],
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': m3u8_url or flv_url,
        }
    return result


@trace_error_decorator
async def get_kuaishou_stream_url(json_data: dict, video_quality: str) -> dict:
    if json_data['type'] == 1 and not json_data["is_live"]:
        return json_data
    live_status = json_data['is_live']

    result = {
        "type": 2,
        "anchor_name": json_data['anchor_name'],
        "is_live": live_status,
    }

    if live_status:
        if video_quality in QUALITY_MAPPING:
            quality, quality_index = get_quality_index(video_quality)
            if 'm3u8_url_list' in json_data:
                m3u8_url_list = _pad_to_five(json_data['m3u8_url_list'][::-1])
                result['m3u8_url'] = m3u8_url_list[quality_index]['url']

            if 'flv_url_list' in json_data:
                if 'bitrate' in json_data['flv_url_list'][0]:
                    flv_url, video_quality = _kuaishou_select_flv_by_bitrate(
                        json_data['flv_url_list'], video_quality)
                    result['flv_url'] = flv_url
                    result['record_url'] = flv_url
                else:
                    flv_url_list = _pad_to_five(json_data['flv_url_list'][::-1])
                    flv_url = flv_url_list[quality_index]['url']
                    result |= {'flv_url': flv_url, 'record_url': flv_url}
            result['is_live'] = True
            result['quality'] = video_quality
    return result


def _kuaishou_select_flv_by_bitrate(flv_url_list: list, video_quality: str) -> tuple:
    """快手按 bitrate 选择最接近的质量档位，返回 (flv_url, video_quality)"""
    quality_mapping_bit = {'OD': 99999, 'BD': 4000, 'UHD': 2000, 'HD': 1000, 'SD': 800, 'LD': 600}
    flv_url_list = sorted(flv_url_list, key=lambda x: x['bitrate'], reverse=True)
    quality_str = str(video_quality).upper()
    if quality_str.isdigit():
        video_quality, quality_index_bitrate_value = list(quality_mapping_bit.items())[int(quality_str)]
    else:
        quality_index_bitrate_value = quality_mapping_bit.get(quality_str, 99999)
        video_quality = quality_str
    quality_index = next(
        (i for i, x in enumerate(flv_url_list) if x['bitrate'] <= quality_index_bitrate_value), None)
    if quality_index is None:
        quality_index = len(flv_url_list) - 1
    return flv_url_list[quality_index]['url'], video_quality


@trace_error_decorator
async def get_huya_stream_url(json_data: dict, video_quality: str) -> dict:
    game_live_info = json_data['data'][0]['gameLiveInfo']
    live_title = game_live_info['introduction']
    stream_info_list = json_data['data'][0]['gameStreamInfoList']
    anchor_name = game_live_info.get('nick', '')

    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }

    if stream_info_list:
        select_cdn = stream_info_list[0]
        stream_name = select_cdn.get('sStreamName')
        flv_anti_code = select_cdn.get('sFlvAntiCode')

        new_anti_code = _huya_get_anti_code(flv_anti_code, stream_name)
        flv_url = f"{select_cdn.get('sFlvUrl')}/{stream_name}.{select_cdn.get('sFlvUrlSuffix')}?{new_anti_code}&ratio="
        m3u8_url = f"{select_cdn.get('sHlsUrl')}/{stream_name}.{select_cdn.get('sHlsUrlSuffix')}?{new_anti_code}&ratio="

        flv_url, m3u8_url = _huya_apply_quality(flv_url, m3u8_url, flv_anti_code, video_quality)

        result |= {
            'is_live': True,
            'title': live_title,
            'quality': video_quality,
            'm3u8_url': m3u8_url,
            'flv_url': flv_url,
            'record_url': flv_url or m3u8_url
        }
    return result


@trace_error_decorator
async def get_douyu_stream_url(json_data: dict, video_quality: str, cookies: str, proxy_addr: str) -> dict:
    if not json_data["is_live"]:
        return json_data

    video_quality_options = {
        "OD": '0',
        "BD": '0',
        "UHD": '3',
        "HD": '2',
        "SD": '1',
        "LD": '1'
    }

    rid = str(json_data["room_id"])
    json_data.pop("room_id")
    rate = video_quality_options.get(video_quality, '0')
    flv_data = await get_douyu_stream_data(rid, rate, cookies=cookies, proxy_addr=proxy_addr)
    rtmp_url = flv_data['data'].get('rtmp_url')
    rtmp_live = flv_data['data'].get('rtmp_live')
    if rtmp_live:
        flv_url = f'{rtmp_url}/{rtmp_live}'
        json_data |= {'quality': video_quality, 'flv_url': flv_url, 'record_url': flv_url}
    return json_data


@trace_error_decorator
async def get_yy_stream_url(json_data: dict) -> dict:
    anchor_name = json_data.get('anchor_name', '')
    result = {
        "anchor_name": anchor_name,
        "is_live": False,
    }
    if 'avp_info_res' in json_data:
        stream_line_addr = json_data['avp_info_res']['stream_line_addr']
        cdn_info = list(stream_line_addr.values())[0]
        flv_url = cdn_info['cdn_info']['url']
        result |= {
            'is_live': True,
            'title': json_data['title'],
            'quality': 'OD',
            'flv_url': flv_url,
            'record_url': flv_url
        }
    return result


@trace_error_decorator
async def get_bilibili_stream_url(json_data: dict, video_quality: str, proxy_addr: str, cookies: str) -> dict:
    anchor_name = json_data["anchor_name"]
    if not json_data["live_status"]:
        return {
            "anchor_name": anchor_name,
            "is_live": False
        }

    room_url = json_data['room_url']

    video_quality_options = {
        "OD": '10000',
        "BD": '400',
        "UHD": '250',
        "HD": '150',
        "SD": '80',
        "LD": '80'
    }

    select_quality = video_quality_options[video_quality]
    play_url = await get_bilibili_stream_data(
        room_url, qn=select_quality, platform='web', proxy_addr=proxy_addr, cookies=cookies)
    return {
        'anchor_name': json_data['anchor_name'],
        'is_live': True,
        'title': json_data['title'],
        'quality': video_quality,
        'record_url': play_url
    }


@trace_error_decorator
async def get_netease_stream_url(json_data: dict, video_quality: str) -> dict:
    if not json_data['is_live']:
        return json_data

    m3u8_url = json_data['m3u8_url']
    flv_url = None
    if json_data.get('stream_list'):
        stream_list = json_data['stream_list']['resolution']
        order = ['blueray', 'ultra', 'high', 'standard']
        sorted_keys = [key for key in order if key in stream_list]
        while len(sorted_keys) < 5:
            sorted_keys.append(sorted_keys[-1])
        video_quality, quality_index = get_quality_index(video_quality)
        selected_quality = sorted_keys[quality_index]
        flv_url_list = stream_list[selected_quality]['cdn']
        selected_cdn = list(flv_url_list.keys())[0]
        flv_url = flv_url_list[selected_cdn]

    return {
        "is_live": True,
        "anchor_name": json_data['anchor_name'],
        "title": json_data['title'],
        'quality': video_quality,
        "m3u8_url": m3u8_url,
        "flv_url": flv_url,
        "record_url": flv_url or m3u8_url
    }


async def get_stream_url(json_data: dict, video_quality: str, url_type: str = 'm3u8', spec: bool = False,
                         hls_extra_key: str | int = None, flv_extra_key: str | int = None) -> dict:
    if not json_data['is_live']:
        return json_data

    play_url_list = json_data['play_url_list']
    while len(play_url_list) < 5:
        play_url_list.append(play_url_list[-1])

    video_quality, selected_quality = get_quality_index(video_quality)
    data = {
        "anchor_name": json_data['anchor_name'],
        "is_live": True
    }

    def get_url(key):
        play_url = play_url_list[selected_quality]
        return play_url[key] if key else play_url

    if url_type == 'all':
        m3u8_url = get_url(hls_extra_key)
        flv_url = get_url(flv_extra_key)
        data |= {
            "m3u8_url": json_data['m3u8_url'] if spec else m3u8_url,
            "flv_url": json_data['flv_url'] if spec else flv_url,
            "record_url": m3u8_url
        }
    elif url_type == 'm3u8':
        m3u8_url = get_url(hls_extra_key)
        data |= {"m3u8_url": json_data['m3u8_url'] if spec else m3u8_url, "record_url": m3u8_url}
    else:
        flv_url = get_url(flv_extra_key)
        data |= {"flv_url": flv_url, "record_url": flv_url}
    data['title'] = json_data.get('title')
    data['quality'] = video_quality
    return data