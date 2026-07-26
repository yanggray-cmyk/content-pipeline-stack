# -*- encoding: utf-8 -*-

"""
平台策略基类 + 注册表
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PlatformStrategy(ABC):
    """平台策略基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def url_patterns(self) -> List[str]:
        pass
    
    @property
    def requires_proxy(self) -> bool:
        return False
    
    def match(self, url: str) -> bool:
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
        pass


class PlatformRegistry:
    """平台注册表"""
    
    def __init__(self):
        self._strategies: List[PlatformStrategy] = []
    
    def register(self, strategy: PlatformStrategy) -> None:
        self._strategies.append(strategy)
    
    def match(self, url: str) -> Optional[PlatformStrategy]:
        for s in self._strategies:
            if s.match(url):
                return s
        return None


registry = PlatformRegistry()
