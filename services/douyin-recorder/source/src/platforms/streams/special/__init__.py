# -*- encoding: utf-8 -*-

"""特殊平台流媒体获取函数 — 按平台拆分为子模块"""

from .douyin import (
    get_douyin_web_stream_data,
    get_douyin_app_stream_data,
    get_douyin_stream_data,
)
from .huya import (
    get_huya_stream_data,
    get_huya_app_stream_url,
)
from .soop import (
    login_sooplive,
    get_sooplive_cdn_url,
    get_sooplive_tk,
    get_soop_headers,
    get_sooplive_stream_data,
)
from .flextv import (
    login_flextv,
    get_flextv_stream_url,
    get_flextv_stream_data,
)
from .popkon import (
    login_popkontv,
    get_popkontv_stream_data,
    get_popkontv_stream_url,
)
from .twitcasting import (
    login_twitcasting,
    get_twitcasting_stream_url,
)
from .taobao_jd import (
    get_taobao_stream_url,
    get_jd_stream_url,
)

__all__ = [
    "get_douyin_web_stream_data",
    "get_douyin_app_stream_data",
    "get_douyin_stream_data",
    "get_huya_stream_data",
    "get_huya_app_stream_url",
    "login_sooplive",
    "get_sooplive_cdn_url",
    "get_sooplive_tk",
    "get_soop_headers",
    "get_sooplive_stream_data",
    "login_flextv",
    "get_flextv_stream_url",
    "get_flextv_stream_data",
    "login_popkontv",
    "get_popkontv_stream_data",
    "get_popkontv_stream_url",
    "login_twitcasting",
    "get_twitcasting_stream_url",
    "get_taobao_stream_url",
    "get_jd_stream_url",
]
