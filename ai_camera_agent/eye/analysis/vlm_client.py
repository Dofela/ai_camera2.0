# eye/analysis/vlm_client.py
"""
VLM 客户端 - 视觉语言模型调用

基于原 app/infrastructure/vlm_client.py 重构
保持完整功能
"""
import base64
import cv2
import asyncio
import httpx
import logging
import numpy as np
from typing import List, Dict, Any, Optional

from config.settings import MonitorLLMConfig, ChatLLMConfig, VideoConfig, VLMConfig


def _process_frames_sync(frames: List[np.ndarray], target_count: int = 5) -> List[str]:
    """
    同步执行的 CPU 密集型任务：抽帧、缩放、编码

    Args:
        frames: 帧列表
        target_count: 目标帧数

    Returns:
        Base64编码的图片列表
    """
    total_frames = len(frames)
    if total_frames <= 0:
        return []

    # 简单的均匀抽帧
    if total_frames <= target_count:
        indices = range(total_frames)
    else:
        indices = np.linspace(0, total_frames - 1, target_count, dtype=int)

    data_image = []
    target_width = 640  # 限制宽度以提升速度

    for i in indices:
        idx = int(i)
        frame = frames[idx]
        if frame is None:
            continue

        # 1. 缩放 (CPU操作)
        height, width = frame.shape[:2]
        if width > target_width:
            scaling_factor = target_width / float(width)
            new_height = int(height * scaling_factor)
            frame = cv2.resize(frame, (target_width, new_height), interpolation=cv2.INTER_AREA)

        # 2. 编码 (CPU操作 - 最耗时)
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), VideoConfig.JPEG_QUALITY])

        # 3. Base64 (CPU操作)
        image_base64 = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')
        data_image.append(image_base64)

    return data_image


async def video_chat_async_limit_frame(
        text: str,
        frames: List[np.ndarray],
        timestamps: List[str] = None,
        fps: int = 20,
        client: httpx.AsyncClient = None,
        config: VLMConfig = None
) -> str:
    """
    异步发送视频帧给 VLM，且不阻塞主线程。

    Args:
        text: 提示词
        frames: 帧列表
        timestamps: 时间戳列表（可选）
        fps: 帧率
        client: HTTP客户端（可选）
        config: VLM配置（可选，默认使用MonitorLLMConfig）

    Returns:
        VLM响应内容
    """
    # 如果未传入 config，默认使用 MonitorLLMConfig
    if config is None:
        config = MonitorLLMConfig

    # 1. 将图片处理放入线程池运行
    try:
        data_image = await asyncio.to_thread(_process_frames_sync, frames)
    except Exception as e:
        logging.error(f"❌ 图片预处理失败: {e}")
        return "{}"

    if not data_image:
        return "{}"

    # 2. 补全 Prompt
    if "json" not in text.lower():
        text += "\n Please output the result in JSON format."

    # 3. 构建消息
    content = [{"type": "text", "text": text}]
    for img_b64 in data_image:
        content.append({"type": "image_url", "image_url": {"url": img_b64}})

    # 4. 组装请求
    url = config.API_URL
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.API_KEY}"
    }

    # 处理可能不存在的字段
    top_p = getattr(config, 'TOP_P', 0.8)

    data = {
        "model": config.MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "top_p": top_p,
        "stream": False,
        "response_format": {"type": "json_object"}
    }

    # 获取超时设置
    timeout_val = getattr(config, 'REQUEST_TIMEOUT', 30.0)

    # 5. 发送请求
    if client is None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_val)) as temp_client:
            return await _send_request(temp_client, url, headers, data)
    else:
        return await _send_request(client, url, headers, data)


async def _send_request(
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        data: Dict[str, Any]
) -> str:
    """
    辅助发送函数，带重试机制

    Args:
        client: HTTP客户端
        url: 请求URL
        headers: 请求头
        data: 请求数据

    Returns:
        响应内容
    """
    max_retries = 3
    base_delay = 2

    for attempt in range(max_retries):
        try:
            response = await client.post(url, headers=headers, json=data)

            if response.status_code == 200:
                response_data = response.json()
                return response_data['choices'][0]['message']['content']
            elif 400 <= response.status_code < 500:
                logging.error(f"❌ API 客户端错误: {response.status_code} - {response.text}")
                return f'{{"error": "API Error {response.status_code}"}}'
            else:
                logging.warning(f"⚠️ API 服务端错误: {response.status_code}")

        except Exception as e:
            logging.error(f"❌ 网络异常: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(base_delay * (2 ** attempt))

    return '{"error": "Request timed out"}'


class VLMClient:
    """
    VLM客户端封装类

    提供更便捷的接口
    """

    def __init__(self, config: VLMConfig = None):
        self.config = config or MonitorLLMConfig
        self.client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self):
        """确保HTTP客户端已初始化"""
        if self.client is None:
            timeout_val = getattr(self.config, 'REQUEST_TIMEOUT', 30.0)
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_val),
                limits=httpx.Limits(max_keepalive_connections=10)
            )

    async def analyze_frames(
            self,
            frames: List[np.ndarray],
            prompt: str,
            timestamps: List[str] = None
    ) -> str:
        """
        分析帧序列

        Args:
            frames: 帧列表
            prompt: 分析提示词
            timestamps: 时间戳（可选）

        Returns:
            分析结果（JSON字符串）
        """
        await self._ensure_client()
        return await video_chat_async_limit_frame(
            text=prompt,
            frames=frames,
            timestamps=timestamps,
            client=self.client,
            config=self.config
        )

    async def close(self):
        """关闭客户端"""
        if self.client:
            await self.client.aclose()
            self.client = None