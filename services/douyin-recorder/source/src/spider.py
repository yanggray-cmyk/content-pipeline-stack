# -*- encoding: utf-8 -*-

"""
spider.py - 向后兼容层

所有平台函数已拆分到 platforms/streams/ 模块：
- domestic.py: 国内平台 (39 个函数)
- overseas.py: 海外平台 (13 个函数)
- special.py: 特殊平台 (29 个函数)

此文件保留 re-export 以保持向后兼容。
"""

# Re-export all functions for backward compatibility
from .platforms.streams.domestic import *
from .platforms.streams.overseas import *
from .platforms.streams.special import *

__all__ = []
