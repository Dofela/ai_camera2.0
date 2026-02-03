# eye/detection/object_detector.py
"""
目标检测器 - 全 YOLO-World 级联架构 (Stage 1 + Stage 2)

核心职责：
1. 管理 YOLO 客户端实例
2. 执行两阶段检测：
   - Stage 1: 全图扫描，寻找 ROI (感兴趣区域)
   - Stage 2: 裁剪精修，寻找 Feature (特征细节)
3. 负责动态 Prompt 的切换与状态恢复
"""
import logging
import asyncio
from typing import List, Set, Optional, Dict, Any
import numpy as np

from common.types import DetectionResult, Detection, BoundingBox
from eye.detection.yolo_client import create_yolo_client, BaseYoloClient
from config.settings import YoloConfig


class ObjectDetector:
    """
    全 YOLO-World 级联检测器

    功能:
    - Stage 1: 全局粗筛 (Person, Car)
    - Stage 2: 局部精修 (Face, License Plate) - 复用同一个 YOLO 实例
    - 支持外部 Agent 动态修改两阶段的目标
    """

    def __init__(self):
        self._client: Optional[BaseYoloClient] = None

        # 定义两套 Prompt (可被 update_targets 修改)
        self._stage1_targets: List[str] = YoloConfig.DEFAULT_TARGETS.copy()
        self._stage2_targets: List[str] = YoloConfig.REFINE_TARGETS.copy()

        self._initialized = False
        logging.info("🎯 [ObjectDetector] 初始化 (全 YOLO-World 架构)...")

    async def _ensure_initialized(self):
        """确保客户端已初始化"""
        if not self._initialized:
            self._client = create_yolo_client()
            # 默认处于 Stage 1 状态
            self._client.update_prompt(self._stage1_targets)
            self._initialized = True
            logging.info(f"🎯 [ObjectDetector] YOLO客户端就绪 | 默认目标: {self._stage1_targets}")

    async def detect_stage1(self, frame: np.ndarray, alert_targets: Set[str] = None) -> DetectionResult:
        """
        Stage 1: 全局粗筛
        使用当前的 _stage1_targets 对全图进行扫描

        Args:
            frame: 全图
            alert_targets: 需要标红的高危目标 (用于绘图)
        """
        await self._ensure_initialized()

        if alert_targets is None:
            alert_targets = set()

        try:
            # 1. 确保 YOLO 处于 Stage 1 模式
            # 注意：client 内部通常会有缓存，如果 targets 没变不会重复发送请求
            self._client.update_prompt(self._stage1_targets)

            # 2. 执行全图检测
            raw_detections, plotted_frame = await self._client.detect_async(
                frame,
                alert_targets=alert_targets
            )

            # 3. 封装结果
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
            logging.error(f"❌ [Stage 1] 检测错误: {e}")
            # 发生错误时返回空结果，避免系统崩溃
            return DetectionResult(frame=frame)

    async def detect_stage2(self, frame: np.ndarray, tasks: List[Dict]) -> List[Dict[str, Any]]:
        """
        Stage 2: 局部精修 (利用 YOLO-World 的动态 Prompt 能力)

        Args:
            frame: 原始大图
            tasks: 任务列表 [{'detection': Detection, 'track_id': int}, ...]

        Returns:
            精修特征列表 (包含全局坐标、置信度、父ID)
        """
        await self._ensure_initialized()

        if not tasks:
            return []

        refined_features = []

        try:
            # 1. 准备裁剪图 (Batch Preparation)
            crops = []
            valid_tasks = []

            h, w = frame.shape[:2]

            for task in tasks:
                det = task['detection']
                # 获取 Stage 1 的坐标
                x1, y1, x2, y2 = det.box.to_list()

                # 边界保护 (防止裁剪越界)
                x1, y1 = max(0, int(x1)), max(0, int(y1))
                x2, y2 = min(w, int(x2)), min(h, int(y2))

                # 只有有效区域才处理
                if x2 > x1 and y2 > y1:
                    crop_img = frame[y1:y2, x1:x2]
                    crops.append(crop_img)
                    valid_tasks.append({
                        'track_id': task['track_id'],
                        'parent_class': det.class_name,
                        'offset': (x1, y1)  # 记录偏移量用于后续坐标还原
                    })

            if not crops:
                return []

            # 2. 核心操作：切换 YOLO 到精修模式 (Prompt: face, license plate...)
            self._client.update_prompt(self._stage2_targets)

            # 3. 并发推理 (针对所有小图)
            # 注意: 为了速度，这里不再要求画图 (alert_targets为空)，只取数据
            results_list = []
            for crop in crops:
                # 调用 detect_async，传入 crop 作为画面
                res, _ = await self._client.detect_async(crop, alert_targets=set())
                results_list.append(res)

            # 4. 坐标还原 (Local -> Global) & 数据封装
            for task_info, local_results in zip(valid_tasks, results_list):
                off_x, off_y = task_info['offset']

                for det in local_results:
                    lx1, ly1, lx2, ly2 = det['box']

                    # 还原全局坐标
                    global_box = [
                        lx1 + off_x,
                        ly1 + off_y,
                        lx2 + off_x,
                        ly2 + off_y
                    ]

                    # 构造特征数据 (这是您"视觉向量"的基础数据)
                    refined_features.append({
                        "parent_track_id": task_info['track_id'],
                        "parent_class": task_info['parent_class'],
                        "refine_label": det['class'],
                        "refine_score": det['confidence'],
                        "global_box": global_box,
                        # 保留原始数据 (Local Box)，方便后续如果需要再次Crop
                        "raw_box_local": det['box'],
                        "raw_confidence": det['confidence']
                    })

            # 5. 核心操作：恢复 YOLO 到 Stage 1 模式
            # 这一步至关重要，必须在 Stage 2 结束后立即执行
            # 否则下一帧的 detect_stage1 可能会用错误的 prompt (找人脸) 去扫全图
            self._client.update_prompt(self._stage1_targets)

            if refined_features:
                logging.debug(f"🔍 [Stage 2] 精修发现 {len(refined_features)} 个细节特征")

            return refined_features

        except Exception as e:
            logging.error(f"❌ [Stage 2] 精修错误: {e}")
            # 发生异常也要确保 Prompt 恢复，防止系统卡死在精修模式
            if self._client:
                self._client.update_prompt(self._stage1_targets)
            return []

    # ============================================================
    # 外部指令接口 (Command Interface)
    # ============================================================

    def update_stage1_targets(self, targets: List[str]) -> bool:
        """
        外部指令: 更新 Stage 1 粗筛目标
        例如: 厨房模式下更新为 ["person", "fire", "knife"]
        """
        self._stage1_targets = targets
        logging.info(f"🎯 [Command] Stage 1 目标已更新: {targets}")

        # 如果已经初始化，立即同步给 client，因为 client 默认就在 Stage 1 状态
        if self._client:
            return self._client.update_prompt(targets)
        return True

    def update_stage2_targets(self, targets: List[str]) -> bool:
        """
        外部指令: 更新 Stage 2 精修目标
        例如: 需要看清人脸和香烟时更新为 ["face", "cigarette"]
        """
        self._stage2_targets = targets
        logging.info(f"🎯 [Command] Stage 2 目标已更新: {targets}")

        # 注意: 这里不立即调用 client.update_prompt
        # 因为 client 绝大多数时间应该停留在 Stage 1 状态
        # 这个 targets 列表只在 detect_stage2 函数执行期间被临时使用
        return True

    def update_targets(self, targets: List[str]) -> bool:
        """
        兼容旧接口: 默认更新 Stage 1
        """
        return self.update_stage1_targets(targets)

    def get_targets(self) -> Dict[str, List[str]]:
        """获取当前的检测目标配置"""
        return {
            "stage1": self._stage1_targets.copy(),
            "stage2": self._stage2_targets.copy()
        }