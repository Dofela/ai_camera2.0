# eye/analysis/scene_analyzer.py
"""
场景分析器 - 使用VLM进行场景理解

基于原 app/services/analysis_service.py 中的 VLM 调用逻辑重构
"""
import json
import asyncio
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import numpy as np

from common.types import AnalysisResult
from eye.analysis.vlm_client import VLMClient, video_chat_async_limit_frame
from config.settings import MonitorLLMConfig, EyeConfig

class AnalysisPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

@dataclass
class AnalysisRequest:
    frames: List[np.ndarray]
    detections: List[str]
    security_policy: str
    priority: AnalysisPriority
    callback: callable


class SceneAnalyzer:
    """
    场景分析器

    功能:
    - 调用VLM分析视频帧
    - 解析VLM返回的JSON结果
    - 判断是否存在异常行为

    工作原理:
    1. 接收帧序列和检测结果
    2. 构建包含安防策略的Prompt
    3. 调用VLM进行分析
    4. 解析返回结果判断是否异常
    """

    def __init__(self):
        self.vlm_client = VLMClient(config=MonitorLLMConfig)
        
        # 允许最多3个并发分析
        from asyncio import Semaphore
        self.semaphore = Semaphore(3)
        
        # 请求队列
        from asyncio import Queue
        self.request_queue = Queue()
        
        # 启动后台工作器
        asyncio.create_task(self._analysis_worker())
        
        logging.info("🧠 [SceneAnalyzer] 初始化完成")
    
    async def _analysis_worker(self):
        """后台工作器处理分析请求"""
        while True:
            request = await self.request_queue.get()
            
            # 获取信号量（限制并发）
            async with self.semaphore:
                try:
                    result = await self._do_analysis(
                        request.frames,
                        request.detections,
                        request.security_policy
                    )
                    request.callback(result)
                except Exception as e:
                    logging.error(f"分析失败: {e}")
                    request.callback(None)

    async def analyze(
            self,
            frames: List[np.ndarray],
            detections: List[str],
            security_policy: str = "标准模式",
            priority=AnalysisPriority.NORMAL
    ) -> Optional[AnalysisResult]:
        """
        非阻塞分析请求

        Args:
            frames: 帧序列
            detections: 检测到的目标类别列表
            security_policy: 当前安防策略
            priority: 分析优先级

        Returns:
            分析结果，如果分析失败返回None
        """
        future = asyncio.Future()
        
        request = AnalysisRequest(
            frames=frames,
            detections=detections,
            security_policy=security_policy,
            priority=priority,
            callback=lambda result: future.set_result(result)
        )
        
        await self.request_queue.put(request)
        
        try:
            # 等待结果（带超时）
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            logging.error("VLM分析超时")
            return None
    
    async def _do_analysis(
            self,
            frames: List[np.ndarray],
            detections: List[str],
            security_policy: str
    ) -> Optional[AnalysisResult]:
        """实际执行分析"""
        try:
            # 1. 构建Prompt
            prompt = self._build_analysis_prompt(detections, security_policy)

            # 2. 调用VLM
            json_response = await self.vlm_client.analyze_frames(
                frames=frames,
                prompt=prompt
            )

            # 3. 解析结果
            if not json_response or json_response == "{}":
                return None

            result = self._parse_response(json_response)
            return result
            
        except Exception as e:
            logging.error(f"❌ [SceneAnalyzer] 分析出错: {e}")
            return None

    async def close(self):
        """关闭分析器资源"""
        # 关闭VLM客户端
        if hasattr(self.vlm_client, 'close'):
            await self.vlm_client.close()
        
        logging.info("🧠 [SceneAnalyzer] 已关闭")
    
    async def analyze_single_frame(
            self,
            frame: np.ndarray,
            instruction: str = "请描述当前画面"
    ) -> Optional[AnalysisResult]:
        """
        分析单帧（用于即时查询）

        Args:
            frame: 单帧图像
            instruction: 分析指令

        Returns:
            分析结果
        """
        try:
            prompt = f"""
            你是一个视觉助手。请根据用户指令分析画面。

            【用户指令】
            {instruction}

            【输出格式】(仅输出JSON):
            {{
                "description": "对画面的描述",
                "is_abnormal": false,
                "reason": "判断依据"
            }}
            """

            json_response = await self.vlm_client.analyze_frames(
                frames=[frame],
                prompt=prompt
            )

            return self._parse_response(json_response)

        except Exception as e:
            logging.error(f"❌ [SceneAnalyzer] 单帧分析出错: {e}")
            return None

    def _build_analysis_prompt(
            self,
            detections: List[str],
            security_policy: str
    ) -> str:
        """
        构建分析Prompt

        Args:
            detections: 检测到的目标
            security_policy: 安防策略

        Returns:
            完整的Prompt
        """
        yolo_hint = json.dumps(detections, ensure_ascii=False)

        prompt = f"""
        你是一个后台安防监控程序。请依据以下【视觉法典】分析画面。

        【当前安防策略 (Policy)】:
        "{security_policy}"

        【传感器数据】:
        - YOLO检测: {yolo_hint}

        【判断标准】:
        1. 如果画面中的行为违反了上述策略 (如离家模式出现人)，必须标记 is_abnormal=true。
        2. 对于 Fire, Smoke, Knife, Blood, Fall，必须标记 is_abnormal=true。
        3. 如果只是正常活动且符合策略，标记 false。

        【输出格式】(仅输出JSON):
        {{
            "description": "客观简短的画面描述",
            "is_abnormal": true/false,
            "reason": "判断依据"
        }}
        """

        return prompt

    def _parse_response(self, json_response: str) -> Optional[AnalysisResult]:
        """
        解析VLM响应

        Args:
            json_response: JSON格式的响应字符串

        Returns:
            解析后的AnalysisResult
        """
        try:
            # 清理JSON字符串
            clean_json = json_response.replace("```json", "").replace("```", "").strip()

            # 提取JSON部分
            if "{" in clean_json:
                clean_json = clean_json[clean_json.find("{"):clean_json.rfind("}") + 1]

            # 解析JSON
            res = json.loads(clean_json)

            return AnalysisResult(
                description=res.get("description", "分析完成"),
                is_abnormal=bool(res.get("is_abnormal", False)),
                reason=res.get("reason", ""),
                raw_response=json_response
            )

        except json.JSONDecodeError as e:
            logging.warning(f"⚠️ [SceneAnalyzer] JSON解析失败: {e}")
            return AnalysisResult(
                description=json_response[:100] if json_response else "解析失败",
                is_abnormal=False,
                raw_response=json_response
            )
        except Exception as e:
            logging.error(f"❌ [SceneAnalyzer] 响应解析错误: {e}")
            return None

    async def close(self):
        """关闭分析器"""
        await self.vlm_client.close()
        logging.info("🧠 [SceneAnalyzer] 已关闭")