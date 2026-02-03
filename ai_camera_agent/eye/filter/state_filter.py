# eye/filter/state_filter.py
"""
视觉状态过滤器 - 决定 Stage 2 (精修) 和 VLM 的触发时机

功能:
1. 目标追踪 (Simple IOU Tracker)
2. 移动检测 (静止 -> 移动)
3. 动态策略管理 (风险等级/高危名单)
4. 筛选需要 YOLO Stage 2 精修的候选目标
"""
import time
import logging
import math
from typing import List, Dict, Set, Tuple, Optional
from common.types import Detection
from config.settings import EyeConfig


class StateFilter:
    """
    状态过滤器 V2 (支持动态策略与移动检测)
    """

    def __init__(self):
        # 追踪对象列表: [{'id': int, 'class': str, 'box': list, 'center': tuple, 'is_moving': bool, 'last_check_time': float}]
        self.tracked_objects: List[Dict] = []

        # 基础配置
        self.iou_threshold: float = EyeConfig.IOU_THRESHOLD
        self.recheck_interval: float = EyeConfig.RECHECK_INTERVAL
        self.movement_threshold: float = getattr(EyeConfig, 'MOVEMENT_THRESHOLD', 20.0)

        # 基础高危类 (无论什么模式都危险)
        self.base_alert_classes: Set[str] = EyeConfig.BASE_ALERT_CLASSES.copy()

        # 当前生效的高危名单 (包含动态目标)
        self.high_priority_classes: Set[str] = self.base_alert_classes.copy()

        # ID 计数器
        self._next_id = 0

        # 当前策略状态
        self.current_risk_level = "normal"

        logging.info(f"🛡️ [StateFilter] 初始化 | 移动阈值: {self.movement_threshold}px")

    def update_policy(self, risk_level: str, dynamic_targets: List[str] = None):
        """
        更新过滤策略 (由 Agent 调用)

        Args:
            risk_level: 风险级别 ("high", "normal", "low")
            dynamic_targets: 动态高危目标 (如离家模式下的 'person')
        """
        self.current_risk_level = risk_level

        # 重置为基础高危名单
        new_priority = self.base_alert_classes.copy()

        # 根据风险级别调整参数
        if risk_level == "high":
            self.recheck_interval = 5.0  # 高危模式：5秒复查一次
            if dynamic_targets:
                new_priority.update(dynamic_targets)
        elif risk_level == "low":
            self.recheck_interval = 60.0  # 低耗模式：60秒复查一次
        else:
            self.recheck_interval = EyeConfig.RECHECK_INTERVAL  # 标准模式

        self.high_priority_classes = new_priority

        logging.info(f"🛡️ [StateFilter] 策略更新: Level={risk_level}, "
                     f"Interval={self.recheck_interval}s, "
                     f"HighRisk={list(self.high_priority_classes)}")

    def check_refinement_needs(self, current_detections: List[Detection]) -> Tuple[List[Dict], List[Detection]]:
        """
        核心逻辑：检查哪些目标需要 Stage 2 精修，哪些需要 VLM 分析

        Args:
            current_detections: 当前 Stage 1 YOLO 结果

        Returns:
            (refine_tasks, vlm_candidates)
            - refine_tasks: Stage 2 任务列表 [{'detection': ..., 'track_id': ...}]
            - vlm_candidates: 需要 VLM 描述的 Detection 列表
        """
        refine_tasks = []
        vlm_candidates = []

        current_time = time.time()
        new_tracked_list = []

        if not current_detections:
            self.tracked_objects = []
            return [], []

        for det in current_detections:
            cls = det.class_name
            box = det.box.to_list()
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            is_high_risk = cls in self.high_priority_classes

            match_found = False
            track_id = -1

            # --- 1. 尝试匹配已追踪对象 ---
            for prev_obj in self.tracked_objects:
                if prev_obj['class'] == cls:
                    iou = self._calculate_iou(box, prev_obj['box'])

                    if iou > self.iou_threshold:
                        match_found = True
                        track_id = prev_obj['id']

                        # 计算移动距离
                        prev_center = prev_obj.get('center', center)
                        dist = math.sqrt((center[0] - prev_center[0]) ** 2 + (center[1] - prev_center[1]) ** 2)

                        # 判定状态变化：静止 -> 移动 (苏醒)
                        was_moving = prev_obj.get('is_moving', False)
                        is_moving = dist > self.movement_threshold

                        state_changed = (not was_moving) and is_moving

                        # 更新追踪信息
                        prev_obj['box'] = box
                        prev_obj['center'] = center
                        prev_obj['is_moving'] = is_moving

                        # 触发条件 A: 状态突变 (苏醒) -> 必选 Stage 2 + VLM
                        if state_changed:
                            logging.debug(f"🛡️ [Filter] 目标苏醒 ID={track_id}")
                            refine_tasks.append({'detection': det, 'track_id': track_id})
                            vlm_candidates.append(det)

                            # 触发条件 B: 高危目标 -> 总是值得关注 (取决于策略)
                        # 如果是高危目标且正在移动，保持关注
                        elif is_high_risk and is_moving:
                            # 只有当间隔一定时间才再次精修，避免每帧都跑 Stage 2
                            if (current_time - prev_obj['last_check_time']) > 2.0:  # 2秒冷却
                                prev_obj['last_check_time'] = current_time
                                refine_tasks.append({'detection': det, 'track_id': track_id})

                        # 触发条件 C: 定期复查 -> 触发 VLM (Stage 2 可选，这里保守策略不触发)
                        elif (current_time - prev_obj['last_check_time']) > self.recheck_interval:
                            prev_obj['last_check_time'] = current_time
                            vlm_candidates.append(det)
                            # 如果是高危目标，定期复查时也做一次 Stage 2
                            if is_high_risk:
                                refine_tasks.append({'detection': det, 'track_id': track_id})

                        new_tracked_list.append(prev_obj)
                        break

            # --- 2. 新目标出现 ---
            if not match_found:
                self._next_id += 1
                track_id = self._next_id

                # 新目标必须看清楚 (Stage 2 + VLM)
                logging.debug(f"🛡️ [Filter] 新目标 ID={track_id}")
                new_obj = {
                    'id': track_id,
                    'class': cls,
                    'box': box,
                    'center': center,
                    'last_check_time': current_time,
                    'is_moving': False
                }
                new_tracked_list.append(new_obj)

                refine_tasks.append({'detection': det, 'track_id': track_id})
                vlm_candidates.append(det)

        self.tracked_objects = new_tracked_list
        return refine_tasks, vlm_candidates

    def reset(self):
        """重置过滤器状态"""
        self.tracked_objects = []
        self._next_id = 0
        logging.info("🛡️ [StateFilter] 状态已重置")

    def get_status(self) -> Dict:
        """获取过滤器状态"""
        return {
            "risk_level": self.current_risk_level,
            "tracked_count": len(self.tracked_objects),
            "high_priority": list(self.high_priority_classes)
        }

    def _calculate_iou(self, boxA: List[int], boxB: List[int]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        if interArea <= 0: return 0

        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        union = float(boxAArea + boxBArea - interArea)

        return interArea / union if union != 0 else 0