# -*- encoding: utf-8 -*-

"""
国内平台策略（声明式注册）

大部分国内平台逻辑相同：spider 获取数据 → stream 解析 URL
"""

import asyncio
from typing import Any, Dict, Optional

from .base import PlatformStrategy


class SimpleDomesticPlatform(PlatformStrategy):
    """简单国内平台（通用实现）"""
    
    def __init__(
        self,
        name: str,
        url_patterns: list,
        spider_func: str,
        stream_func: Optional[str] = None,
        cookie_key: str = '',
        extra_params: dict = None
    ):
        self._name = name
        self._url_patterns = url_patterns
        self._spider_func = spider_func
        self._stream_func = stream_func
        self._cookie_key = cookie_key
        self._extra_params = extra_params or {}
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def url_patterns(self) -> list:
        return self._url_patterns
    
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        from src import spider, stream
        
        cookie = context.get(self._cookie_key, '') if self._cookie_key else ''
        
        with semaphore:
            spider_func = getattr(spider, self._spider_func)
            
            if self._stream_func:
                json_data = await spider_func(url=url, proxy_addr=proxy, cookies=cookie)
                stream_func = getattr(stream, self._stream_func)
                
                kwargs = {'json_data': json_data, 'video_quality': quality}
                if self._extra_params.get('pass_proxy'):
                    kwargs['proxy_addr'] = proxy
                if self._extra_params.get('pass_cookie'):
                    kwargs['cookies'] = cookie
                    
                port_info = await stream_func(**kwargs)
            else:
                port_info = await spider_func(url=url, proxy_addr=proxy, cookies=cookie)
        
        return port_info


# 国内平台列表
DOMESTIC_PLATFORMS = [
    SimpleDomesticPlatform('快手直播', ['https://live.kuaishou.com/'], 
                          'get_kuaishou_stream_data', 'get_kuaishou_stream_url', 'ks_cookie'),
    SimpleDomesticPlatform('斗鱼直播', ['https://www.douyu.com/'],
                          'get_douyu_info_data', 'get_douyu_stream_url', 'douyu_cookie',
                          {'pass_proxy': True, 'pass_cookie': True}),
    SimpleDomesticPlatform('YY直播', ['https://www.yy.com/'],
                          'get_yy_stream_data', 'get_yy_stream_url', 'yy_cookie'),
    SimpleDomesticPlatform('B站直播', ['https://live.bilibili.com/'],
                          'get_bilibili_room_info', 'get_bilibili_stream_url', 'bili_cookie',
                          {'pass_proxy': True, 'pass_cookie': True}),
    SimpleDomesticPlatform('小红书直播', ['http://xhslink.com/', 'https://www.xiaohongshu.com/'],
                          'get_xhs_stream_url', None, 'xhs_cookie'),
    SimpleDomesticPlatform('Bigo直播', ['www.bigo.tv/', 'slink.bigovideo.tv/'],
                          'get_bigo_stream_url', None, 'bigo_cookie'),
    SimpleDomesticPlatform('Blued直播', ['https://app.blued.cn/'],
                          'get_blued_stream_url', None, 'blued_cookie'),
    SimpleDomesticPlatform('网易CC直播', ['cc.163.com/'],
                          'get_netease_stream_data', 'get_netease_stream_url', 'netease_cookie'),
    SimpleDomesticPlatform('千度热播', ['qiandurebo.com/'],
                          'get_qiandurebo_stream_data', None, 'qiandurebo_cookie'),
    SimpleDomesticPlatform('猫耳FM直播', ['fm.missevan.com/'],
                          'get_maoerfm_stream_url', None, 'maoerfm_cookie'),
    SimpleDomesticPlatform('Look直播', ['look.163.com/'],
                          'get_looklive_stream_url', None, 'look_cookie'),
    SimpleDomesticPlatform('百度直播', ['live.baidu.com/'],
                          'get_baidu_stream_data', 'get_stream_url', 'baidu_cookie'),
    SimpleDomesticPlatform('微博直播', ['weibo.com/'],
                          'get_weibo_stream_data', 'get_stream_url', 'weibo_cookie'),
    SimpleDomesticPlatform('酷狗直播', ['kugou.com/'],
                          'get_kugou_stream_url', None, 'kugou_cookie'),
    SimpleDomesticPlatform('花椒直播', ['www.huajiao.com/'],
                          'get_huajiao_stream_url', None, 'huajiao_cookie'),
    SimpleDomesticPlatform('流星直播', ['7u66.com/'],
                          'get_liuxing_stream_url', None, 'liuxing_cookie'),
    SimpleDomesticPlatform('ShowRoom', ['showroom-live.com/'],
                          'get_showroom_stream_data', 'get_stream_url', 'showroom_cookie'),
    SimpleDomesticPlatform('Acfun', ['live.acfun.cn/', 'm.acfun.cn/'],
                          'get_acfun_stream_data', 'get_stream_url', 'acfun_cookie'),
    SimpleDomesticPlatform('畅聊直播', ['live.tlclw.com/'],
                          'get_changliao_stream_url', None, 'changliao_cookie'),
    SimpleDomesticPlatform('音播直播', ['ybw1666.com/'],
                          'get_yinbo_stream_url', None, 'yinbo_cookie'),
    SimpleDomesticPlatform('映客直播', ['www.inke.cn/'],
                          'get_yingke_stream_url', None, 'yingke_cookie'),
    SimpleDomesticPlatform('知乎直播', ['www.zhihu.com/'],
                          'get_zhihu_stream_url', None, 'zhihu_cookie'),
    SimpleDomesticPlatform('CHZZK', ['chzzk.naver.com/'],
                          'get_chzzk_stream_data', 'get_stream_url', 'chzzk_cookie'),
    SimpleDomesticPlatform('嗨秀直播', ['www.haixiutv.com/'],
                          'get_haixiu_stream_url', None, 'haixiu_cookie'),
    SimpleDomesticPlatform('VV星球', ['vvxqiu.com/'],
                          'get_vvxqiu_stream_url', None, 'vvxqiu_cookie'),
    SimpleDomesticPlatform('17Live', ['17.live/'],
                          'get_17live_stream_url', None, 'yiqilive_cookie'),
    SimpleDomesticPlatform('浪Live', ['www.lang.live/'],
                          'get_langlive_stream_url', None, 'langlive_cookie'),
    SimpleDomesticPlatform('漂漂直播', ['m.pp.weimipopo.com/'],
                          'get_pplive_stream_url', None, 'pplive_cookie'),
    SimpleDomesticPlatform('六间房直播', ['.6.cn/'],
                          'get_6room_stream_url', None, 'six_room_cookie'),
    SimpleDomesticPlatform('乐嗨直播', ['lehaitv.com/'],
                          'get_haixiu_stream_url', None, 'haixiu_cookie'),
    SimpleDomesticPlatform('花猫直播', ['h.catshow168.com/'],
                          'get_pplive_stream_url', None, 'huamao_cookie'),
    SimpleDomesticPlatform('咪咕直播', ['www.miguvideo.com', 'm.miguvideo.com'],
                          'get_migu_stream_url', None, 'migu_cookie'),
    SimpleDomesticPlatform('连接直播', ['show.lailianjie.com'],
                          'get_lianjie_stream_url', None, 'lianjie_cookie'),
    SimpleDomesticPlatform('来秀直播', ['www.imkktv.com'],
                          'get_laixiu_stream_url', None, 'laixiu_cookie'),
    SimpleDomesticPlatform('Picarto', ['www.picarto.tv'],
                          'get_picarto_stream_url', None, 'picarto_cookie'),
]
