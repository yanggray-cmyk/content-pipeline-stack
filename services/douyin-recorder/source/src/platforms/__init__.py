# -*- encoding: utf-8 -*-

"""
平台策略模块

将 start_record 的 51 elif 分支重构为策略模式
"""

from .base import PlatformStrategy, PlatformRegistry, registry
from .domestic import DOMESTIC_PLATFORMS
from .overseas import OVERSEAS_PLATFORMS
from .special import (
    DouyinStrategy, HuyaStrategy, SOOPStrategy, FlexTVStrategy,
    PopkonTVStrategy, TwitCastingStrategy, ShopeeStrategy,
    TaobaoStrategy, CustomStrategy
)

__all__ = [
    'PlatformStrategy',
    'PlatformRegistry',
    'registry',
]


def _register_all_platforms():
    """注册所有平台策略"""
    
    # 特殊平台（有复杂逻辑）
    special = [
        DouyinStrategy(),
        HuyaStrategy(),
        SOOPStrategy(),
        FlexTVStrategy(),
        PopkonTVStrategy(),
        TwitCastingStrategy(),
        ShopeeStrategy(),
        TaobaoStrategy(),
        CustomStrategy(),  # 兜底放最后
    ]
    
    for p in special:
        registry.register(p)
    
    # 国内简单平台
    for p in DOMESTIC_PLATFORMS:
        registry.register(p)
    
    # 海外简单平台
    for p in OVERSEAS_PLATFORMS:
        registry.register(p)


# 首次导入时自动注册
_register_all_platforms()
