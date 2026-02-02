# eye/detection/object_detector.py
"""
目标检测器 - YOLO检测的高层封装
"""
import logging
import asyncio
from typing import List, Set, Optional
import numpy as np

from common.types import DetectionResult, Detection, BoundingBox
from eye.detection.yolo_client import create_yolo_client, BaseYoloClient
from config.settings import YoloConfig


class ObjectDetector:
    """
    目标检测器

    功能:
    - 封装YOLO检测
    - 支持动态更新检测目标
    - 统一检测结果格式
    """

    def __init__(self):
        self._client: Optional[BaseYoloClient] = None
        self._targets: List[str] = YoloConfig.DEFAULT_TARGETS.copy()
        self._initialized = False

        logging.info("🎯 [ObjectDetector] 初始化...")

    async def _ensure_initialized(self):
        """确保客户端已初始化"""
        if not self._initialized:
            self._client = create_yolo_client()
            self._client.update_prompt(self._targets)
            self._initialized = True
            logging.info(f"🎯 [ObjectDetector] YOLO客户端就绪 | 目标: {self._targets}")

    async def detect(
            self,
            frame: np.ndarray,
            alert_targets: Set[str] = None
    ) -> DetectionResult:
        """
        执行目标检测

        Args:
            frame: 输入图像
            alert_targets: 需要标红的高危目标

        Returns:
            检测结果
        """
        await self._ensure_initialized()

        if alert_targets is None:
            alert_targets = set()

        try:
            # 调用YOLO检测
            raw_detections, plotted_frame = await self._client.detect_async(
                frame,
                alert_targets=alert_targets
            )

            # 转换为统一格式
            detections = []
            for det in raw_detections:
                box = det.get("box", [0, 0, 0, 0])
                detections.append(Detection(
                    class_name=det.get("class", "unknown"),
                    confidence=det.get("confidence", 0.0),
                    box=BoundingBox(
                        x1=box[0], y1=box[1],
                        x2=box[2], y2=box[3]
                    )
                ))

            return DetectionResult(
                detections=detections,
                frame=frame,
                plotted_frame=plotted_frame
            )

        except Exception as e:
            logging.error(f"❌ [ObjectDetector] 检测错误: {e}")
            return DetectionResult(frame=frame)

    def update_targets(self, targets: List[str]) -> bool:
        """更新检测目标"""
        self._targets = targets
        if self._client:
            success = self._client.update_prompt(targets)
            logging.info(f"🎯 [ObjectDetector] 目标更新: {targets} | 成功: {success}")
            return success
        return True

    def get_targets(self) -> List[str]:
        """获取当前检测目标"""
        return self._targets.copy()