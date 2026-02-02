# eye/capture/frame_buffer.py
"""
帧缓冲区 - 管理视频帧的缓存
"""
import asyncio
import logging
from collections import deque
from typing import List, Dict, Any, Optional

from config.settings import VideoConfig


class FrameBuffer:
    """
    帧缓冲区

    功能:
    - 保存最近N秒的帧
    - 提供帧序列给分析器
    - 线程安全
    """

    def __init__(self, duration: float = None, fps: float = None):
        self.duration = duration or VideoConfig.CONTEXT_DURATION
        self.fps = fps or VideoConfig.TARGET_FPS

        # 计算缓冲区大小
        max_frames = int(self.fps * self.duration)

        # 上下文缓冲（保留最近N秒）
        self._context_buffer: deque = deque(maxlen=max_frames)

        # 触发缓冲（用于分析）
        self._trigger_buffer: deque = deque(maxlen=int(self.fps * 2))

        # 同步事件
        self._new_data_event = asyncio.Event()
        self._lock = asyncio.Lock()

        logging.info(f"📦 [FrameBuffer] 初始化 | 容量: {max_frames}帧 ({self.duration}秒)")

    async def add(self, frame_data: Dict[str, Any]):
        """添加帧到缓冲区（异步且线程安全）"""
        async with self._lock:
            self._context_buffer.append(frame_data)
            self._trigger_buffer.append(frame_data)
            self._new_data_event.set()

    async def wait_for_new_data(self, timeout: float = 1.0) -> bool:
        """等待新数据"""
        try:
            await asyncio.wait_for(self._new_data_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def get_frames(self, clear_trigger: bool = True) -> List[Dict[str, Any]]:
        """获取帧序列"""
        async with self._lock:
            frames = list(self._context_buffer)

            if clear_trigger:
                self._trigger_buffer.clear()
                self._new_data_event.clear()

            return frames

    async def get_latest(self) -> Optional[Dict[str, Any]]:
        """获取最新帧"""
        async with self._lock:
            if self._context_buffer:
                return self._context_buffer[-1]
            return None

    async def clear(self):
        """清空缓冲区"""
        async with self._lock:
            self._context_buffer.clear()
            self._trigger_buffer.clear()
            self._new_data_event.clear()

    @property
    def size(self) -> int:
        """当前缓冲区大小"""
        return len(self._context_buffer)

    @property
    def is_empty(self) -> bool:
        """缓冲区是否为空"""
        return len(self._context_buffer) == 0