# eye/memory/perception_memory.py
"""
感知记忆 - 基于old_app的完整事件管理逻辑

功能:
1. 事件生命周期管理（开始/更新/关闭）
2. 最大计数跟踪
3. 报警标签管理
4. 无目标容忍帧数控制
5. 异步数据库集成（眼睛模块专用数据库）
"""
import logging
import time
from typing import Dict, Set, Optional, List, Union
from datetime import datetime
from dataclasses import dataclass, field

from common.types import DetectionResult, PerceptionResult
from config.settings import EyeConfig
from infrastructure.database.async_db_manager import AsyncDBManager, async_db_manager


@dataclass
class EventState:
    """事件状态（基于old_app的完整事件管理）"""
    event_id: Optional[int] = None
    max_counts: Dict[str, int] = field(default_factory=dict)
    alert_tags: Set[str] = field(default_factory=set)
    start_time: str = ""
    last_update_time: str = ""
    empty_frame_counter: int = 0
    is_active: bool = False
    
    def update_counts(self, new_counts: Dict[str, int]):
        """更新最大计数"""
        for cls_name, count in new_counts.items():
            if count > self.max_counts.get(cls_name, 0):
                self.max_counts[cls_name] = count
    
    def add_alert_tag(self, tag: str):
        """添加报警标签"""
        self.alert_tags.add(tag)
    
    def reset(self):
        """重置事件状态"""
        self.event_id = None
        self.max_counts.clear()
        self.alert_tags.clear()
        self.empty_frame_counter = 0
        self.is_active = False


class PerceptionMemory:
    """
    感知记忆管理器
    
    基于 old_app 的 MultiModalAnalyzer 事件管理逻辑重构，
    适配新的类Agent架构。
    """
    
    def __init__(self):
        # 当前事件状态
        self.current_event = EventState()
        
        # 配置参数
        self.loss_tolerance = EyeConfig.LOSS_TOLERANCE  # 无目标容忍帧数
        self.base_alert_classes = EyeConfig.BASE_ALERT_CLASSES  # 基础高危类
        self.max_event_duration = EyeConfig.MAX_EVENT_DURATION  # 最大事件持续时间
        
        # 数据库管理器（后续集成）
        self.db_manager: Optional[AsyncDBManager] = None
        
        # 事件历史
        self.event_history: List[Dict] = []
        
        logging.info("🧠 [PerceptionMemory] 初始化完成")
    
    async def store(self, perception_result: PerceptionResult) -> bool:
        """
        存储感知结果
        
        Args:
            perception_result: 感知结果
            
        Returns:
            是否成功存储
        """
        try:
            # 更新事件状态
            await self._update_event_state(perception_result)
            
            # 记录到历史
            self.event_history.append({
                "timestamp": perception_result.timestamp,
                "event_id": perception_result.event_id,
                "detections": perception_result.detection_result.class_counts,
                "alert_tags": list(perception_result.alert_tags)
            })
            
            # 保持历史长度
            if len(self.event_history) > 100:
                self.event_history = self.event_history[-50:]
                
            return True
            
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 存储失败: {e}")
            return False
    
    async def _update_event_state(self, perception_result: PerceptionResult):
        """更新事件状态（核心逻辑）"""
        detection_result = perception_result.detection_result
        class_counts = detection_result.class_counts
        
        # 检查是否有检测目标
        if detection_result.has_detections:
            # 重置空帧计数器
            self.current_event.empty_frame_counter = 0
            
            # 检查当前事件是否已超过最大持续时间
            if self.current_event.is_active:
                event_duration = time.time() - float(self.current_event.start_time)
                
                if event_duration > self.max_event_duration:
                    logging.info(
                        f"📝 [PerceptionMemory] 事件 {self.current_event.event_id} "
                        f"达到最大持续时间 ({event_duration:.1f}s)，正在关闭..."
                    )
                    
                    # 关闭旧事件
                    await self._close_event(perception_result.timestamp)
                    
                    # 如果仍有对象存在，立即开始新事件
                    await self._start_event(
                        perception_result.timestamp,
                        class_counts,
                        self._is_visual_abnormal(detection_result),
                        perception_result.alert_tags
                    )
                    
                    perception_result.event_id = self.current_event.event_id
                    return
            
            # 正常事件更新逻辑
            if not self.current_event.is_active:
                # 开始新事件
                await self._start_event(
                    perception_result.timestamp,
                    class_counts,
                    self._is_visual_abnormal(detection_result),
                    perception_result.alert_tags
                )
                perception_result.event_id = self.current_event.event_id
            else:
                # 更新现有事件
                self.current_event.update_counts(class_counts)
                await self._update_event(perception_result.timestamp)
                
        else:
            # 无检测结果 - 增加空帧计数器
            self.current_event.empty_frame_counter += 1
            
            # 关闭事件如果空帧时间过长
            if (self.current_event.is_active and
                self.current_event.empty_frame_counter >= self.loss_tolerance):
                await self._close_event(perception_result.timestamp)
    
    def _is_visual_abnormal(self, detection_result: DetectionResult) -> bool:
        """检查检测是否包含高风险对象"""
        return any(
            det.class_name in self.base_alert_classes
            for det in detection_result.detections
        )
    
    async def _start_event(self, timestamp: str, class_counts: Dict[str, int], 
                          is_visual_abnormal: bool, alert_tags: Set[str]) -> int:
        """开始新事件"""
        try:
            # 生成事件ID（模拟数据库自增）
            event_id = int(time.time() * 1000)
            
            # 更新事件状态
            self.current_event.event_id = event_id
            self.current_event.max_counts = class_counts.copy()
            self.current_event.alert_tags = alert_tags.copy()
            self.current_event.start_time = timestamp
            self.current_event.last_update_time = timestamp
            self.current_event.empty_frame_counter = 0
            self.current_event.is_active = True
            
            # 添加视觉高危标签
            if is_visual_abnormal:
                self.current_event.add_alert_tag("visual")
            
            # 记录到数据库（如果可用）
            if self.db_manager:
                await self.db_manager.start_event(
                    timestamp, class_counts, 
                    1 if is_visual_abnormal else 0,
                    ",".join(self.current_event.alert_tags)
                )
            
            logging.info(f"📝 [PerceptionMemory] 事件开始: ID={event_id}, "
                        f"目标={class_counts}, 高危={is_visual_abnormal}")
            
            return event_id
            
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 开始事件失败: {e}")
            return -1
    
    async def _update_event(self, timestamp: str, new_visual_risk: bool = False):
        """更新事件"""
        if not self.current_event.is_active:
            return
            
        try:
            self.current_event.last_update_time = timestamp
            
            # 更新数据库（如果可用）
            if self.db_manager and new_visual_risk:
                await self.db_manager.update_event(
                    self.current_event.event_id,
                    timestamp,
                    self.current_event.max_counts,
                    is_abnormal=1,
                    alert_tags=",".join(self.current_event.alert_tags)
                )
                
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 更新事件失败: {e}")
    
    async def _close_event(self, timestamp: str):
        """关闭事件"""
        if not self.current_event.is_active:
            return
            
        try:
            event_id = self.current_event.event_id
            
            # 更新数据库（如果可用）
            if self.db_manager:
                await self.db_manager.close_event(event_id, timestamp)
            
            logging.info(f"📝 [PerceptionMemory] 事件关闭: ID={event_id}, "
                        f"持续={timestamp}, 最大目标={self.current_event.max_counts}")
            
            # 重置事件状态
            self.current_event.reset()
            
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 关闭事件失败: {e}")
    
    async def update_event(self, class_counts: Dict[str, int], 
                          is_abnormal: bool, alert_tags: Set[str]) -> int:
        """
        更新或创建事件（EyeCore调用的接口）
        
        Args:
            class_counts: 类别计数
            is_abnormal: 是否异常
            alert_tags: 报警标签
            
        Returns:
            事件ID
        """
        if not self.current_event.is_active:
            # 创建新事件
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return await self._start_event(timestamp, class_counts, is_abnormal, alert_tags)
        else:
            # 更新现有事件
            self.current_event.update_counts(class_counts)
            if is_abnormal:
                self.current_event.add_alert_tag("visual")
            return self.current_event.event_id
    
    async def try_close_event(self):
        """尝试关闭当前事件（EyeCore调用的接口）"""
        if self.current_event.is_active:
            self.current_event.empty_frame_counter += 1
            if self.current_event.empty_frame_counter >= self.loss_tolerance:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                await self._close_event(timestamp)
    
    def _check_visual_risks(self, detection_result: DetectionResult) -> List[str]:
        """检查视觉高危目标"""
        risks = []
        for det in detection_result.detections:
            if det.class_name in self.base_alert_classes:
                risks.append(det.class_name)
        return risks
    
    async def _trigger_fast_alert(self, visual_risks: List[str]):
        """触发快速视觉报警"""
        try:
            # 这里应该调用Hand模块的报警分发器
            # 暂时先记录日志
            logging.warning(f"🚨 [PerceptionMemory] 视觉高危报警: {visual_risks}")
            
            # TODO: 集成到Hand模块的报警系统
            # await self.alert_dispatcher.notify_fast_alert(visual_risks)
            
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 触发报警失败: {e}")
    
    def get_current_state(self) -> Dict:
        """获取当前状态"""
        return {
            "event_id": self.current_event.event_id,
            "is_active": self.current_event.is_active,
            "max_counts": self.current_event.max_counts,
            "alert_tags": list(self.current_event.alert_tags),
            "empty_frame_counter": self.current_event.empty_frame_counter,
            "loss_tolerance": self.loss_tolerance
        }
    
    def get_event_history(self, limit: int = 10) -> List[Dict]:
        """获取事件历史"""
        return self.event_history[-limit:] if self.event_history else []
    
    async def connect_database(self, db_manager: AsyncDBManager = None):
        """
        连接并初始化数据库
        
        这必须在系统初始化期间调用，而不是在__init__中
        """
        if db_manager is None:
            from infrastructure.database.async_db_manager import async_db_manager
            self.db_manager = async_db_manager
        else:
            self.db_manager = db_manager
        
        # 关键修复: 实际初始化连接池
        try:
            logging.info("💾 [PerceptionMemory] 初始化数据库连接池...")
            await self.db_manager.initialize()
            
            # 验证数据库是否健康
            is_healthy = await self.db_manager.health_check()
            
            if not is_healthy:
                raise RuntimeError("数据库初始化后健康检查失败")
            
            logging.info("✅ [PerceptionMemory] 数据库连接池就绪")
            
        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 数据库初始化失败: {e}")
            self.db_manager = None
            raise