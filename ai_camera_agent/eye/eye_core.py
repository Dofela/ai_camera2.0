# ai_camera_agent/eye/eye_core.py
"""
Eye 核心模块 - 全 YOLO-World 级联感知架构 (执行层)

核心定位: 可编程、高保真的感知执行器
适配: Step 4 数据库重构 (AsyncDBManager + PerceptionMemory V2)
"""
import asyncio
import logging
from typing import Optional, List, Set, Dict, Any
import numpy as np

from common.types import PerceptionResult, DetectionResult, AnalysisResult
from eye.capture.video_capture import VideoCapture
from eye.capture.frame_buffer import FrameBuffer
from eye.detection.object_detector import ObjectDetector
from eye.filter.state_filter import StateFilter
from eye.analysis.scene_analyzer import SceneAnalyzer
from eye.memory.perception_memory import PerceptionMemory


class EyeCore:
    """
    眼睛核心类 - 统一管理感知流水线
    """

    def __init__(self):
        self.video_capture = VideoCapture()
        self.frame_buffer = FrameBuffer()
        self.object_detector = ObjectDetector()
        self.state_filter = StateFilter()
        self.scene_analyzer = SceneAnalyzer()
        self.perception_memory = PerceptionMemory()

        # 视频录制器
        from eye.capture.video_recorder import VideoRecorder
        self.video_recorder = VideoRecorder()
        self.recording_active = False

        self._running = False
        self._perception_task: Optional[asyncio.Task] = None
        self._recording_task: Optional[asyncio.Task] = None

        # 状态
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_timestamp: float = 0.0
        self.current_event_id: Optional[int] = None
        self.security_policy: str = "标准模式"
        self.muted_classes: Set[str] = set()

        logging.info("👁️ [Eye] V2 全 YOLO 级联架构初始化完成")

    async def initialize(self):
        """重初始化（异步操作）"""
        try:
            # [Step 4] 连接新版数据库管理器 (AsyncPG)
            await self.perception_memory.connect_database()
            if self.perception_memory.db_manager:
                if not await self.perception_memory.db_manager.health_check():
                    raise RuntimeError("数据库健康检查失败")
            logging.info("👁️ [Eye] 初始化完成 (数据库已连接)")
        except Exception as e:
            logging.error(f"❌ [Eye] 初始化失败: {e}")
            raise

    async def start(self):
        """启动感知循环"""
        self._running = True
        logging.info("👁️ [Eye] 启动感知循环...")
        capture_task = asyncio.create_task(self._capture_loop())
        analysis_task = asyncio.create_task(self._analysis_loop())
        recording_task = asyncio.create_task(self._recording_loop())
        await asyncio.gather(capture_task, analysis_task, recording_task)

    async def stop(self):
        """停止感知循环"""
        self._running = False
        await self.video_capture.stop()
        await self.scene_analyzer.close()
        logging.info("👁️ [Eye] 感知循环已停止")

    async def close(self):
        """关闭Eye核心资源"""
        if self.perception_memory and self.perception_memory.db_manager:
            await self.perception_memory.db_manager.close_all()
        await self.video_capture.stop()
        await self.scene_analyzer.close()
        logging.info("👁️ [Eye] 资源已关闭")

    async def _capture_loop(self):
        capture_task = asyncio.create_task(self.video_capture.start())
        try:
            while self._running:
                frame_data = await self.video_capture.get_frame()
                if frame_data:
                    self.latest_frame = frame_data["frame"]
                    self.latest_timestamp = frame_data["timestamp"]
                    await self.frame_buffer.add(frame_data)
                    try:
                        from api.websockets.video_feed import manager
                        await manager.broadcast_frame(self.latest_frame)
                    except Exception as e:
                        logging.debug(f"📺 WebSocket广播失败: {e}")
                await asyncio.sleep(0.01)
        finally:
            await self.video_capture.stop()
            capture_task.cancel()

    async def _analysis_loop(self):
        """分析循环 - 核心流水线"""
        while self._running:
            await self.frame_buffer.wait_for_new_data()
            frames = await self.frame_buffer.get_frames()
            if not frames: continue
            try:
                result = await self.perceive(frames)
                if result:
                    # [Step 4] 存储结果 (将自动触发去重和 DB 写入)
                    await self.perception_memory.store(result)
            except Exception as e:
                logging.error(f"👁️ [Eye] 分析错误: {e}")
            await asyncio.sleep(0.01)

    async def _recording_loop(self):
        """录制循环"""
        while self._running:
            # 简化录制逻辑，避免过于复杂
            if (self.perception_memory.current_event.is_active and
                    self.perception_memory.current_event.event_id is not None):
                if not self.recording_active:
                    event_id = self.perception_memory.current_event.event_id
                    context_frames = await self.get_context_frames()
                    video_path = self.video_recorder.start_recording(event_id=event_id, frames=context_frames)
                    if video_path:
                        self.recording_active = True
                if self.recording_active and self.latest_frame is not None:
                    self.video_recorder.add_frame(self.latest_frame)
            elif self.recording_active:
                video_path = self.video_recorder.stop_recording()
                if video_path and self.perception_memory.db_manager:
                    try:
                        await self.perception_memory.db_manager.update_video_path(
                            event_id=self.perception_memory.current_event.event_id,
                            video_path=video_path
                        )
                    except Exception as e:
                        logging.error(f"❌ 更新视频路径失败: {e}")
                self.recording_active = False
            await asyncio.sleep(0.1)

    async def perceive(self, frames: List[dict]) -> Optional[PerceptionResult]:
        """执行完整感知流程"""
        if not frames: return None
        latest_frame = frames[-1]["frame"]
        timestamp = frames[-1].get("timestamp", "")

        # Step 1: Stage 1 Detect
        detection_result = await self.object_detector.detect_stage1(
            latest_frame,
            alert_targets=self.state_filter.high_priority_classes if hasattr(self.state_filter,
                                                                             'high_priority_classes') else None
        )

        if self.muted_classes:
            detection_result = self._filter_muted(detection_result)

        # Step 2: State Filter
        refine_tasks, vlm_candidates = self.state_filter.check_refinement_needs(
            detection_result.detections
        )

        # Step 3: Stage 2 Refine (提取特征)
        refine_features = []
        if refine_tasks:
            refine_features = await self.object_detector.detect_stage2(
                latest_frame,
                refine_tasks
            )

        # Step 4: Assembly
        # [核心] 挂载特征数据，供 PerceptionMemory 使用
        alert_tags = set()
        visual_risks = self._check_visual_risks(detection_result)
        if visual_risks: alert_tags.add("visual")

        for f in refine_features:
            if f.get('refine_label') in ['knife', 'gun', 'weapon', 'fire']:
                alert_tags.add(f['refine_label'])

        result = PerceptionResult(
            detection_result=detection_result,
            timestamp=timestamp,
            alert_tags=alert_tags,
            event_id=None  # 将由 Memory 填充
        )

        # [Step 4] 关键: 将 Stage 2 特征挂载到结果对象
        setattr(result, 'refine_features', refine_features)

        # Step 5: VLM (Optional)
        should_analyze_vlm = (len(vlm_candidates) > 0)
        if should_analyze_vlm and detection_result.detections:
            analysis_result = await self._run_vlm_analysis(
                frames, detection_result.unique_classes
            )
            if analysis_result:
                result.analysis_result = analysis_result
                if analysis_result.is_abnormal:
                    result.alert_tags.add("behavior")

        return result

    async def perceive_single(self, frame: np.ndarray) -> Optional[PerceptionResult]:
        detection_result = await self.object_detector.detect_stage1(frame)
        return PerceptionResult(detection_result=detection_result, timestamp="")

    def _filter_muted(self, detection_result: DetectionResult) -> DetectionResult:
        filtered = [d for d in detection_result.detections if d.class_name not in self.muted_classes]
        return DetectionResult(
            detections=filtered,
            frame=detection_result.frame,
            plotted_frame=detection_result.plotted_frame,
            timestamp=detection_result.timestamp
        )

    def _check_visual_risks(self, detection_result: DetectionResult) -> List[str]:
        current_high_priority = self.state_filter.high_priority_classes
        risks = []
        for det in detection_result.detections:
            if det.class_name in current_high_priority:
                risks.append(det.class_name)
        return risks

    async def _run_vlm_analysis(self, frames: List[dict], detection_labels: List[str]) -> Optional[AnalysisResult]:
        frame_list = [f["frame"] for f in frames]
        return await self.scene_analyzer.analyze(
            frames=frame_list,
            detections=detection_labels,
            security_policy=self.security_policy
        )

    # Command Interfaces
    def update_targets(self, targets: List[str]) -> bool:
        return self.object_detector.update_stage1_targets(targets)

    def update_stage1_targets(self, targets: List[str]) -> bool:
        return self.object_detector.update_stage1_targets(targets)

    def update_stage2_targets(self, targets: List[str]) -> bool:
        return self.object_detector.update_stage2_targets(targets)

    def update_security_policy(self, policy: str, risk_level: str = "normal", dynamic_targets: List[str] = None):
        self.security_policy = policy
        self.state_filter.update_policy(risk_level, dynamic_targets)
        logging.info(f"👁️ [Eye] 策略更新: {policy}")

    def mute_class(self, class_name: str):
        self.muted_classes.add(class_name)

    def unmute_class(self, class_name: str):
        self.muted_classes.discard(class_name)

    def get_latest_frame(self) -> Optional[np.ndarray]:
        return self.latest_frame

    async def get_context_frames(self) -> List[np.ndarray]:
        frames = await self.frame_buffer.get_frames()
        return [f["frame"] for f in frames]

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "policy": self.security_policy,
            "filter_status": self.state_filter.get_status(),
            "muted_classes": list(self.muted_classes),
            "current_event_id": self.perception_memory.current_event.event_id
        }