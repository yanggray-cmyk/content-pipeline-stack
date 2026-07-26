# -*- encoding: utf-8 -*-

"""
平台策略基类 + 注册表

重构目标：将 start_record 的 51 elif 分支替换为策略模式
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PlatformStrategy(ABC):
    """平台策略基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """平台显示名称"""
        pass
    
    @property
    @abstractmethod
    def url_patterns(self) -> List[str]:
        """URL 匹配模式列表"""
        pass
    
    @property
    def requires_proxy(self) -> bool:
        """是否需要代理（海外平台）"""
        return False
    
    def match(self, url: str) -> bool:
        """检查 URL 是否匹配"""
        return any(p in url for p in self.url_patterns)
    
    @abstractmethod
    async def fetch_stream(
        self,
        url: str,
        quality: str,
        proxy: Optional[str],
        semaphore: asyncio.Semaphore,
        **context
    ) -> Optional[Dict[str, Any]]:
        """获取流信息"""
        pass
    
    def on_stream_fetched(
        self,
        port_info: Optional[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """流获取后的钩子（更新 cookie/token 等）"""
        return port_info


class PlatformRegistry:
    """平台注册表"""
    
    def __init__(self):
        self._strategies: List[PlatformStrategy] = []
        self._by_name: Dict[str, PlatformStrategy] = {}
    
    def register(self, strategy: PlatformStrategy) -> None:
        """注册策略"""
        self._strategies.append(strategy)
        self._by_name[strategy.name] = strategy
    
    def match(self, url: str) -> Optional[PlatformStrategy]:
        """根据 URL 匹配平台"""
        for s in self._strategies:
            if s.match(url):
                return s
        return None
    
    def list_platforms(self) -> List[str]:
        """列出所有平台"""
        return [s.name for s in self._strategies]


# 全局注册表
registry = PlatformRegistry()
