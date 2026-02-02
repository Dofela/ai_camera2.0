# eye/eye_core.py
"""
Eye 核心模块 - 感知层统一入口

工作流程:
1. VideoCapture 采集视频帧
2. ObjectDetector 进行YOLO检测
3. StateFilter 过滤/去重/追踪
4. SceneAnalyzer 调用VLM进行场景理解
5. PerceptionMemory 存储感知结果
"""
import asyncio
import logging
from typing import Optional, List, Set
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
    眼睛核心类 - 统一管理所有感知组件

    职责:
    - 协调各感知组件的工作
    - 管理感知循环
    - 提供统一的感知接口
    """

    def __init__(self):
        """创建Eye组件（不进行重初始化）"""
        # 只创建对象，不启动任何操作
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
        
        # 配置
        self.target_objects: List[str] = ["person"]
        self.security_policy: str = "标准模式"
        self.muted_classes: Set[str] = set()
        
        logging.info("👁️ [Eye] 创建完成（未初始化）")

    async def initialize(self):
        """重初始化（异步操作）"""
        try:
            await self.perception_memory.connect_database()

            # 验证数据库健康
            if self.perception_memory.db_manager:
                if not await self.perception_memory.db_manager.health_check():
                    raise RuntimeError("数据库健康检查失败")

            logging.info("👁️ [Eye] 初始化完成")

        except Exception as e:
            logging.error(f"❌ [Eye] 初始化失败: {e}")
            raise

    async def start(self):
        """启动感知循环"""
        self._running = True
        logging.info("👁️ [Eye] 启动感知循环...")

        # 启动视频采集
        capture_task = asyncio.create_task(self._capture_loop())

        # 启动分析循环
        analysis_task = asyncio.create_task(self._analysis_loop())
        
        # 启动录制循环
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
        # 关闭数据库连接
        if self.perception_memory and self.perception_memory.db_manager:
            await self.perception_memory.db_manager.close_all()
        
        # 关闭视频采集
        await self.video_capture.stop()
        
        # 关闭场景分析器
        await self.scene_analyzer.close()
        
        logging.info("👁️ [Eye] 资源已关闭")

    async def _capture_loop(self):
        """视频采集循环"""
        await self.video_capture.start()

        while self._running:
            frame_data = await self.video_capture.get_frame()
            if frame_data:
                self.latest_frame = frame_data["frame"]
                self.latest_timestamp = frame_data["timestamp"]
                await self.frame_buffer.add(frame_data)
                
                # 广播帧到WebSocket客户端
                try:
                    from api.websockets.video_feed import manager
                    await manager.broadcast_frame(self.latest_frame)
                except Exception as e:
                    logging.debug(f"📺 WebSocket广播失败: {e}")
                    
            await asyncio.sleep(0)

    async def _analysis_loop(self):
        """分析循环"""
        while self._running:
            # 等待新帧
            await self.frame_buffer.wait_for_new_data()

            # 获取帧序列
            frames = await self.frame_buffer.get_frames()
            if not frames:
                continue

            # 执行感知
            try:
                result = await self.perceive(frames)
                if result:
                    # 存储感知结果
                    await self.perception_memory.store(result)
            except Exception as e:
                logging.error(f"👁️ [Eye] 分析错误: {e}")

            await asyncio.sleep(0.01)
    
    async def _recording_loop(self):
        """录制循环 - 管理视频录制基于事件"""
        while self._running:
            # 检查事件是否活跃且需要录制
            if (self.perception_memory.current_event.is_active and
                self.perception_memory.current_event.event_id is not None):
                
                if not self.recording_active:
                    # 开始录制
                    event_id = self.perception_memory.current_event.event_id
                    context_frames = await self.get_context_frames()
                    
                    video_path = self.video_recorder.start_recording(
                        event_id=event_id,
                        frames=context_frames
                    )
                    
                    if video_path:
                        self.recording_active = True
                        logging.info(f"🎥 开始录制事件 {event_id}")
                
                # 向录制器添加帧
                if self.recording_active and self.latest_frame is not None:
                    self.video_recorder.add_frame(self.latest_frame)
            
            elif self.recording_active:
                # 停止录制当事件关闭时
                video_path = self.video_recorder.stop_recording()
                
                # 更新数据库中的视频路径
                if video_path and self.perception_memory.db_manager:
                    try:
                        await self.perception_memory.db_manager.update_video_path(
                            event_id=self.perception_memory.current_event.event_id,
                            video_path=video_path
                        )
                        logging.info(f"💾 视频已保存: {video_path}")
                    except Exception as e:
                        logging.error(f"❌ 更新视频路径失败: {e}")
                
                self.recording_active = False
            
            await asyncio.sleep(0.1)

    async def perceive(self, frames: List[dict]) -> Optional[PerceptionResult]:
        """
        执行一次完整的感知流程

        Args:
            frames: 帧数据列表

        Returns:
            感知结果
        """
        if not frames:
            return None

        latest_frame = frames[-1]["frame"]
        timestamp = frames[-1].get("timestamp", "")

        # 1. 目标检测
        detection_result = await self.object_detector.detect(
            latest_frame,
            alert_targets=self.state_filter.high_priority_classes
        )

        # 2. 过滤静音类别
        if self.muted_classes:
            detection_result = self._filter_muted(detection_result)

        # 3. 状态过滤
        should_analyze, objects_to_analyze = self.state_filter.should_trigger_vlm(
            detection_result.detections
        )

        # 4. 构建感知结果
        result = PerceptionResult(
            detection_result=detection_result,
            timestamp=timestamp
        )

        # 5. 处理检测结果
        if detection_result.detections:
            # 检查视觉高危
            visual_risks = self._check_visual_risks(detection_result)
            if visual_risks:
                result.alert_tags.add("visual")

            # 更新事件
            result.event_id = await self._update_event(detection_result, result.alert_tags)

            # 6. 触发VLM分析
            if should_analyze and result.event_id:
                analysis_result = await self._run_vlm_analysis(frames, detection_result)
                if analysis_result:
                    result.analysis_result = analysis_result
                    if analysis_result.is_abnormal:
                        result.alert_tags.add("behavior")
        else:
            # 无目标，尝试关闭事件
            await self._try_close_event()

        return result

    async def perceive_single(self, frame: np.ndarray) -> Optional[PerceptionResult]:
        """
        对单帧进行感知（用于即时查询）

        Args:
            frame: 单帧图像

        Returns:
            感知结果
        """
        detection_result = await self.object_detector.detect(frame)

        return PerceptionResult(
            detection_result=detection_result,
            timestamp=""
        )

    def _filter_muted(self, detection_result: DetectionResult) -> DetectionResult:
        """过滤静音类别"""
        filtered = [
            d for d in detection_result.detections
            if d.class_name not in self.muted_classes
        ]
        return DetectionResult(
            detections=filtered,
            frame=detection_result.frame,
            plotted_frame=detection_result.plotted_frame,
            timestamp=detection_result.timestamp
        )

    def _check_visual_risks(self, detection_result: DetectionResult) -> List[str]:
        """检查视觉高危目标"""
        risks = []
        for det in detection_result.detections:
            if det.class_name in self.state_filter.high_priority_classes:
                risks.append(det.class_name)
        return risks

    async def _update_event(self, detection_result: DetectionResult, alert_tags: Set[str]) -> int:
        """更新或创建事件"""
        return await self.perception_memory.update_event(
            detection_result.class_counts,
            is_abnormal="visual" in alert_tags,
            alert_tags=alert_tags
        )

    async def _try_close_event(self):
        """尝试关闭当前事件"""
        await self.perception_memory.try_close_event()

    async def _run_vlm_analysis(
            self,
            frames: List[dict],
            detection_result: DetectionResult
    ) -> Optional[AnalysisResult]:
        """运行VLM分析"""
        frame_list = [f["frame"] for f in frames]
        return await self.scene_analyzer.analyze(
            frames=frame_list,
            detections=detection_result.unique_classes,
            security_policy=self.security_policy
        )

    # ============================================================
    # 配置接口
    # ============================================================

    def update_targets(self, targets: List[str]) -> bool:
        """更新检测目标"""
        self.target_objects = targets
        return self.object_detector.update_targets(targets)

    def update_security_policy(self, policy: str, risk_level: str = "normal"):
        """更新安防策略"""
        self.security_policy = policy

        # 更新状态过滤器
        dynamic_targets = self.target_objects if risk_level == "high" else None
        self.state_filter.update_policy(risk_level, dynamic_targets)

    def mute_class(self, class_name: str):
        """静音某个类别"""
        self.muted_classes.add(class_name)

    def unmute_class(self, class_name: str):
        """取消静音"""
        self.muted_classes.discard(class_name)

    # ============================================================
    # 状态查询接口
    # ============================================================

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """获取最新帧"""
        return self.latest_frame

    async def get_context_frames(self) -> List[np.ndarray]:
        """获取上下文帧序列"""
        frames = await self.frame_buffer.get_frames()
        return [f["frame"] for f in frames]

    def get_status(self) -> dict:
        """获取眼睛状态"""
        return {
            "running": self._running,
            "targets": self.target_objects,
            "policy": self.security_policy,
            "muted_classes": list(self.muted_classes),
            "current_event_id": self.current_event_id
        }