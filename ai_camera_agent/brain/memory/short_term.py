# brain/memory/short_term.py
"""
短期记忆 - 存储最近的对话历史和上下文
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from collections import deque
import json
import logging


@dataclass
class MemoryItem:
    """记忆项"""
    role: str
    content: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ShortTermMemory:
    """
    短期记忆类
    用于存储和管理最近的对话历史
    """

    def __init__(self, max_items: int = 10):
        self.max_items = max_items
        self.memory: deque = deque(maxlen=max_items)
        self.logger = logging.getLogger(__name__)

    def add(self, role: str, content: str, timestamp: float, metadata: Dict[str, Any] = None):
        """
        添加记忆项
        
        Args:
            role: 角色 (user/assistant/system)
            content: 内容
            timestamp: 时间戳
            metadata: 元数据
        """
        item = MemoryItem(
            role=role,
            content=content,
            timestamp=timestamp,
            metadata=metadata or {}
        )
        self.memory.append(item)
        self.logger.debug(f"添加记忆项: {role} - {content[:50]}...")

    def get_recent(self, count: int = None) -> List[Dict[str, str]]:
        """
        获取最近的记忆项
        
        Args:
            count: 获取数量，默认返回所有
            
        Returns:
            List[Dict[str, str]]: 消息列表
        """
        if count is None:
            count = len(self.memory)
        
        items = list(self.memory)[-count:]
        return [
            {"role": item.role, "content": item.content}
            for item in items
        ]

    def get_context(self) -> List[Dict[str, str]]:
        """
        获取上下文消息
        
        Returns:
            List[Dict[str, str]]: 上下文消息列表
        """
        return self.get_recent()

    def clear(self):
        """清空记忆"""
        self.memory.clear()
        self.logger.debug("清空短期记忆")

    def __len__(self) -> int:
        return len(self.memory)

    def __str__(self) -> str:
        return f"ShortTermMemory(items={len(self.memory)}, max_items={self.max_items})"