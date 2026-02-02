# brain/context/context_manager.py
"""
上下文管理器 - 管理和维护对话上下文
"""

from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
import logging
from datetime import datetime


@dataclass
class Context:
    """上下文数据类"""
    user_id: str
    session_id: str
    created_at: datetime
    updated_at: datetime
    data: Dict[str, Any] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)


class ContextManager:
    """
    上下文管理器类
    负责管理和维护对话上下文
    """

    def __init__(self):
        self.contexts: Dict[str, Context] = {}
        self.logger = logging.getLogger(__name__)

    def get_context(self, user_id: str, session_id: str) -> Context:
        """
        获取或创建上下文
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            
        Returns:
            Context: 上下文对象
        """
        context_key = f"{user_id}:{session_id}"
        
        if context_key not in self.contexts:
            self.contexts[context_key] = Context(
                user_id=user_id,
                session_id=session_id,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.logger.debug(f"创建新上下文: {context_key}")
        
        return self.contexts[context_key]

    def update_context(self, user_id: str, session_id: str, 
                      data: Dict[str, Any] = None, tags: Set[str] = None):
        """
        更新上下文
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            data: 数据
            tags: 标签
        """
        context = self.get_context(user_id, session_id)
        context.updated_at = datetime.now()
        
        if data:
            context.data.update(data)
            
        if tags:
            context.tags.update(tags)
            
        self.logger.debug(f"更新上下文: {user_id}:{session_id}")

    def get_context_data(self, user_id: str, session_id: str) -> Dict[str, Any]:
        """
        获取上下文数据
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 上下文数据
        """
        context = self.get_context(user_id, session_id)
        return context.data

    def add_context_tag(self, user_id: str, session_id: str, tag: str):
        """
        添加上下文标签
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            tag: 标签
        """
        context = self.get_context(user_id, session_id)
        context.tags.add(tag)
        context.updated_at = datetime.now()
        self.logger.debug(f"添加上下文标签: {tag}")

    def has_context_tag(self, user_id: str, session_id: str, tag: str) -> bool:
        """
        检查是否存在上下文标签
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            tag: 标签
            
        Returns:
            bool: 是否存在标签
        """
        context = self.get_context(user_id, session_id)
        return tag in context.tags

    def clear_context(self, user_id: str, session_id: str):
        """
        清空上下文
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
        """
        context_key = f"{user_id}:{session_id}"
        if context_key in self.contexts:
            del self.contexts[context_key]
            self.logger.debug(f"清空上下文: {context_key}")

    def get_context_tags(self, user_id: str, session_id: str) -> Set[str]:
        """
        获取上下文标签
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            
        Returns:
            Set[str]: 标签集合
        """
        context = self.get_context(user_id, session_id)
        return context.tags.copy()