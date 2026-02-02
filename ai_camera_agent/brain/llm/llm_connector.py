# brain/llm/llm_connector.py
"""
LLM连接器 - 与大语言模型交互的接口
"""

import json
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

import httpx
from config.settings import ChatLLMConfig


@dataclass
class LLMResponse:
    """LLM响应数据类"""
    content: str
    usage: Dict[str, int]
    model: str


class LLMConnector:
    """
    LLM连接器类
    负责与大语言模型进行交互
    """

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self._setup_client()

    def _setup_client(self):
        """设置HTTP客户端"""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20)
        )

    async def chat_completion(self, messages: List[Dict[str, str]], 
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> LLMResponse:
        """
        调用LLM聊天完成接口
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大令牌数
            
        Returns:
            LLMResponse: LLM响应
        """
        if not self.client:
            self._setup_client()

        try:
            # 构造请求数据
            payload = {
                "model": ChatLLMConfig.MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            # 发送请求
            response = await self.client.post(
                ChatLLMConfig.API_URL,
                headers={
                    "Authorization": f"Bearer {ChatLLMConfig.API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload
            )

            # 检查响应状态
            response.raise_for_status()

            # 解析响应
            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})

            return LLMResponse(
                content=choice["message"]["content"],
                usage=usage,
                model=data.get("model", ChatLLMConfig.MODEL)
            )

        except httpx.HTTPStatusError as e:
            logging.error(f"LLM API错误: {e}")
            raise Exception(f"LLM API错误: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logging.error(f"LLM调用失败: {e}")
            raise Exception(f"LLM调用失败: {str(e)}")

    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.aclose()
            self.client = None