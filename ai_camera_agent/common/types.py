# agent/types.py
"""
Agent 公共类型定义

这个模块包含了整个 AI Camera Agent 系统中使用的核心数据类型。
虽然这些类型主要用于 Eye（感知）模块，但作为公共类型定义放在 agent 包中，
方便所有模块共享使用，避免循环依赖。

主要类型：
- BoundingBox: 检测框
- Detection: 单个检测结果
- DetectionResult: 检测结果集合
- AnalysisResult: VLM分析结果
- PerceptionResult: 完整感知结果
- TrackedObject: 追踪对象
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
import numpy as np


@dataclass
class BoundingBox:
    """检测框（Bounding Box）"""
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> tuple:
        """返回边界框的中心点坐标"""
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        """返回边界框的面积"""
        return (self.x2 - self.x1) * (self.y2 - self.y1)

    def to_list(self) -> List[int]:
        """转换为列表格式 [x1, y1, x2, y2]"""
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass
class Detection:
    """单个检测结果"""
    class_name: str
    confidence: float
    box: BoundingBox

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "class": self.class_name,
            "confidence": self.confidence,
            "box": self.box.to_list()
        }


@dataclass
class DetectionResult:
    """检测结果集合"""
    detections: List[Detection] = field(default_factory=list)
    frame: Optional[np.ndarray] = None
    plotted_frame: Optional[np.ndarray] = None
    timestamp: str = ""

    @property
    def class_counts(self) -> Dict[str, int]:
        """统计各类别数量"""
        counts = {}
        for det in self.detections:
            counts[det.class_name] = counts.get(det.class_name, 0) + 1
        return counts

    @property
    def unique_classes(self) -> List[str]:
        """获取所有检测到的唯一类别"""
        return list(set(d.class_name for d in self.detections))

    def filter_by_class(self, class_names: Set[str]) -> 'DetectionResult':
        """按类别过滤检测结果"""
        filtered = [d for d in self.detections if d.class_name in class_names]
        return DetectionResult(
            detections=filtered,
            frame=self.frame,
            plotted_frame=self.plotted_frame,
            timestamp=self.timestamp
        )


@dataclass
class AnalysisResult:
    """VLM（Vision-Language Model）分析结果"""
    description: str = ""
    is_abnormal: bool = False
    reason: str = ""
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "description": self.description,
            "is_abnormal": self.is_abnormal,
            "reason": self.reason
        }


@dataclass
class PerceptionResult:
    """完整感知结果"""
    detection_result: Optional[DetectionResult] = None
    analysis_result: Optional[AnalysisResult] = None
    event_id: Optional[int] = None
    alert_tags: Set[str] = field(default_factory=set)
    timestamp: str = ""

    @property
    def has_targets(self) -> bool:
        """是否检测到目标"""
        return bool(self.detection_result and self.detection_result.detections)

    @property
    def is_abnormal(self) -> bool:
        """是否存在异常"""
        return bool(self.alert_tags) or (
                self.analysis_result and self.analysis_result.is_abnormal
        )

    def to_alert_dict(self) -> Dict[str, Any]:
        """转换为警报字典格式"""
        desc = ""
        if self.detection_result:
            desc = f"检测到: {self.detection_result.class_counts}"
        if self.analysis_result:
            desc += f" | {self.analysis_result.description}"

        return {
            "alert": "实时监控",
            "description": desc,
            "is_abnormal": self.is_abnormal,
            "row_id": self.event_id,
            "tags": list(self.alert_tags),
            "detections": self.detection_result.unique_classes if self.detection_result else []
        }


@dataclass
class TrackedObject:
    """追踪对象"""
    class_name: str
    box: BoundingBox
    last_check_time: float
    track_id: Optional[int] = None
