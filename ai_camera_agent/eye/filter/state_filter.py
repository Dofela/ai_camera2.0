# eye/filter/state_filter.py
"""
视觉状态过滤器 - 决定什么东西需要由 VLM 二次确认

基于原 app/services/analysis_service.py 中的 VisualStateFilter 重构
"""
import time
import logging
from typing import List, Dict, Set, Tuple, Optional

from common.types import Detection
from config.settings import EyeConfig


class StateFilter:
    """
    视觉状态过滤器

    功能:
    - 追踪检测到的对象
    - 通过IOU判断是否是同一对象
    - 决定是否需要触发VLM分析
    - 管理高危目标名单

    工作原理:
    1. 新对象出现 -> 触发VLM
    2. 已追踪对象位置变化超过阈值 -> 触发VLM
    3. 已追踪对象超过复查间隔 -> 触发VLM
    4. 高危对象始终触发
    """

    def __init__(self):
        # 追踪对象列表
        self.tracked_objects: List[Dict] = []

        # IOU阈值：超过此值认为是同一对象
        self.iou_threshold: float = EyeConfig.IOU_THRESHOLD

        # 复查间隔（秒）：超过此时间需要重新分析
        self.recheck_interval: float = EyeConfig.RECHECK_INTERVAL

        # 默认的高危基础类（无论什么模式都危险）
        self.base_alert_classes: Set[str] = EyeConfig.BASE_ALERT_CLASSES.copy()

        # 当前生效的高危名单（由 Agent 动态设定）
        self.high_priority_classes: Set[str] = set(self.base_alert_classes)

        # 当前风险级别
        self.current_risk_level: str = "normal"

        logging.info(
            f"🛡️ [StateFilter] 初始化完成 | IOU阈值: {self.iou_threshold} | 复查间隔: {self.recheck_interval}s")
        logging.info(f"🛡️ [StateFilter] 基础高危类别: {self.base_alert_classes}")

    def update_policy(self, risk_level: str, dynamic_targets: List[str] = None):
        """
        更新过滤策略

        Agent 通过此接口修改底层的过滤逻辑

        Args:
            risk_level: 风险级别 ("high", "normal", "low")
            dynamic_targets: 动态目标列表（如离家模式下的 person）
        """
        self.current_risk_level = risk_level

        # 1. 基础名单永远保留
        new_priority = set(self.base_alert_classes)

        # 2. 根据风险级别调整
        if risk_level == "high" and dynamic_targets:
            # 高风险模式：把动态目标也加入高危名单
            new_priority.update(dynamic_targets)
            self.recheck_interval = 5.0  # 高频复查
        elif risk_level == "low":
            # 低风险模式：放宽复查间隔
            self.recheck_interval = 60.0
        else:
            # 标准模式
            self.recheck_interval = EyeConfig.RECHECK_INTERVAL

        self.high_priority_classes = new_priority

        logging.info(f"🛡️ [StateFilter] 策略更新: Level={risk_level}, "
                     f"HighRisk={self.high_priority_classes}, "
                     f"RecheckInterval={self.recheck_interval}s")

    def should_trigger_vlm(self, current_detections: List[Detection]) -> Tuple[bool, List[Detection]]:
        """
        判断是否需要触发VLM分析

        Args:
            current_detections: 当前帧检测到的对象列表

        Returns:
            (是否触发, 需要分析的对象列表)
        """
        trigger_needed = False
        objects_to_analyze: List[Detection] = []
        current_time = time.time()
        new_tracked_list: List[Dict] = []

        # 如果没有检测到任何对象，清空追踪列表
        if not current_detections:
            self.tracked_objects = []
            return False, []

        for det in current_detections:
            cls = det.class_name
            box = det.box.to_list()
            is_high_priority = cls in self.high_priority_classes

            match_found = False

            # 尝试匹配已追踪的对象
            for prev_obj in self.tracked_objects:
                if prev_obj['class'] == cls:
                    iou = self._calculate_iou(box, prev_obj['box'])

                    if iou > self.iou_threshold:
                        # 匹配成功 - 是同一对象
                        match_found = True
                        time_diff = current_time - prev_obj['last_check_time']

                        # 判断是否需要重新分析
                        if is_high_priority or time_diff > self.recheck_interval:
                            # 高优先级对象或超过复查间隔
                            prev_obj['box'] = box
                            prev_obj['last_check_time'] = current_time
                            objects_to_analyze.append(det)
                            trigger_needed = True
                        else:
                            # 只更新位置，不触发分析
                            prev_obj['box'] = box

                        new_tracked_list.append(prev_obj)
                        break

            if not match_found:
                # 新对象 - 需要分析
                new_obj = {
                    'class': cls,
                    'box': box,
                    'last_check_time': current_time
                }
                new_tracked_list.append(new_obj)
                objects_to_analyze.append(det)
                trigger_needed = True

        self.tracked_objects = new_tracked_list
        return trigger_needed, objects_to_analyze

    def _calculate_iou(self, boxA: List[int], boxB: List[int]) -> float:
        """
        计算两个框的交并比 (Intersection over Union)

        Args:
            boxA: [x1, y1, x2, y2]
            boxB: [x1, y1, x2, y2]

        Returns:
            IoU值 (0-1)
        """
        # 计算交集
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)

        if interArea <= 0:
            return 0

        # 计算并集
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        union = float(boxAArea + boxBArea - interArea)

        return interArea / union if union != 0 else 0

    def reset(self):
        """重置追踪状态"""
        self.tracked_objects = []
        logging.info("🛡️ [StateFilter] 追踪状态已重置")

    def get_tracked_count(self) -> int:
        """获取当前追踪的对象数量"""
        return len(self.tracked_objects)

    def get_status(self) -> Dict:
        """获取过滤器状态"""
        return {
            "risk_level": self.current_risk_level,
            "high_priority_classes": list(self.high_priority_classes),
            "tracked_count": len(self.tracked_objects),
            "recheck_interval": self.recheck_interval,
            "iou_threshold": self.iou_threshold
        }