# eye/capture/video_capture.py
"""
视频采集器 - 负责从视频源获取帧
"""
import cv2
import asyncio
import logging
import time
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

from config.settings import VideoConfig, VIDEO_SOURCE


class VideoCapture:
    """
    视频采集器

    功能:
    - 从摄像头/RTSP/文件获取视频帧
    - 异步非阻塞采集
    - 自动重连
    """

    def __init__(self, source: str = None):
        self.source = source or VIDEO_SOURCE

        # 转换源类型
        if str(self.source).isdigit():
            self.source = int(self.source)

        # 视频属性
        self.width: int = 0
        self.height: int = 0
        self.fps: float = 0.0

        # 运行状态
        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None
        self._executor = ThreadPoolExecutor(max_workers=2)

        # 最新帧
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_timestamp: float = 0.0
        self._frame_lock = asyncio.Lock()

        # 初始化视频源信息
        self._init_source_info()

        logging.info(f"📹 [VideoCapture] 初始化完成 | 源: {self.source}")

    def _init_source_info(self):
        """初始化视频源信息"""
        cap = cv2.VideoCapture(self.source)
        if cap.isOpened():
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.release()
        else:
            logging.warning(f"⚠️ 无法打开视频源: {self.source}，使用默认值")
            self.width, self.height, self.fps = 1920, 1080, 30.0

        logging.info(f"📹 视频信息: {self.width}x{self.height} @ {self.fps}fps")

    async def start(self):
        """启动视频采集"""
        self._running = True
        logging.info("📹 [VideoCapture] 开始采集...")

        loop = asyncio.get_running_loop()
        self._cap = cv2.VideoCapture(self.source)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, VideoConfig.BUFFER_SIZE)

        while self._running:
            try:
                # 在线程池中读取帧（避免阻塞）
                ret, frame = await loop.run_in_executor(
                    self._executor,
                    self._cap.read
                )

                if not ret:
                    logging.warning("⚠️ 视频源断开，尝试重连...")
                    await self._reconnect()
                    continue

                # 确保帧格式正确
                if frame.dtype != np.uint8:
                    frame = frame.astype(np.uint8)

                # 更新最新帧
                async with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_timestamp = time.time()

                await asyncio.sleep(0)

            except Exception as e:
                logging.error(f"❌ [VideoCapture] 采集错误: {e}")
                await asyncio.sleep(1)

        self._cap.release()

    async def stop(self):
        """停止视频采集"""
        self._running = False
        if self._cap:
            self._cap.release()
        logging.info("📹 [VideoCapture] 已停止")

    async def _reconnect(self):
        """重连视频源"""
        await asyncio.sleep(VideoConfig.WS_RETRY_INTERVAL)
        if self._cap:
            self._cap.release()
        self._cap = cv2.VideoCapture(self.source)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, VideoConfig.BUFFER_SIZE)

    async def get_frame(self) -> Optional[Dict[str, Any]]:
        """获取最新帧"""
        async with self._frame_lock:
            if self._latest_frame is None:
                return None
            return {
                "frame": self._latest_frame.copy(),
                "timestamp": self._latest_timestamp,
                "timestamp_str": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

    @property
    def is_running(self) -> bool:
        return self._running