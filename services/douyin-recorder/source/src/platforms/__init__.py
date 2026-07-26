# -*- encoding: utf-8 -*-

"""平台策略模块"""

from .base import PlatformStrategy, PlatformRegistry, registry
from .domestic import DOMESTIC_PLATFORMS
from .overseas import OVERSEAS_PLATFORMS
from .special import (
    DouyinStrategy, HuyaStrategy, SOOPStrategy, FlexTVStrategy,
    PopkonTVStrategy, TwitCastingStrategy, ShopeeStrategy,
    TaobaoStrategy, CustomStrategy
)

__all__ = ['PlatformStrategy', 'PlatformRegistry', 'registry']


def _register_all_platforms():
    special = [
        DouyinStrategy(), HuyaStrategy(), SOOPStrategy(), FlexTVStrategy(),
        PopkonTVStrategy(), TwitCastingStrategy(), ShopeeStrategy(),
        TaobaoStrategy(), CustomStrategy(),
    ]
    for p in special:
        registry.register(p)
    for p in DOMESTIC_PLATFORMS:
        registry.register(p)
    for p in OVERSEAS_PLATFORMS:
        registry.register(p)


_register_all_platforms()
