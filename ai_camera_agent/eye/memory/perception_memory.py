# ai_camera_agent/eye/memory/perception_memory.py
"""
感知记忆 - 具备向量去重能力的事件管理器

功能:
1. 事件生命周期管理
2. 关键帧过滤 (方案 C): 基于向量相似度的去重
3. 数据库同步: 对接 AsyncDBManager (Eye专用高速引擎)
"""
import logging
import time
import math
from typing import Dict, Set, Optional, List, Any
from datetime import datetime
from dataclasses import dataclass, field

import numpy as np

from common.types import DetectionResult, PerceptionResult
from config.settings import EyeConfig
# 引入 Step 3 完成的异步管理器
from infrastructure.database.async_db_manager import async_db_manager, AsyncDBManager


def compute_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算余弦相似度 (简单的 numpy 实现)"""
    if not vec1 or not vec2: return 0.0
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0: return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


@dataclass
class EventState:
    """事件状态 (内存中维护的实时状态)"""
    event_id: Optional[int] = None
    max_counts: Dict[str, int] = field(default_factory=dict)
    alert_tags: Set[str] = field(default_factory=set)
    start_time: str = ""
    last_update_time: str = ""
    empty_frame_counter: int = 0
    is_active: bool = False

    # [核心新增] 累积的精修数据 (将同步到数据库的 refine_data 字段)
    # 格式: [{"label": "face", "vector": [...], "time": "..."}]
    refine_data_accumulated: List[Dict] = field(default_factory=list)

    # [核心新增] 去重缓存 (用于方案 C)
    # track_id -> {"vector": [...], "last_time": float}
    vector_cache: Dict[int, Dict] = field(default_factory=dict)

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
        self.refine_data_accumulated.clear()
        self.vector_cache.clear()


class PerceptionMemory:
    """
    感知记忆管理器 (V2: 支持向量去重)

    负责:
    1. 接收 EyeCore 的感知结果
    2. 过滤掉重复的特征向量 (关键帧过滤)
    3. 调用 AsyncDBManager 进行高性能存储
    """

    def __init__(self):
        self.current_event = EventState()
        self.db_manager: Optional[AsyncDBManager] = None

        # 配置参数
        self.loss_tolerance = EyeConfig.LOSS_TOLERANCE
        self.base_alert_classes = EyeConfig.BASE_ALERT_CLASSES
        self.max_event_duration = EyeConfig.MAX_EVENT_DURATION

        # 向量去重阈值 (大于此值视为重复)
        self.similarity_threshold = 0.99
        self.min_update_interval = 1.0  # 即使不相似，同一ID最快1秒更新一次

        # 事件历史 (仅内存保留少量)
        self.event_history: List[Dict] = []

        logging.info("🧠 [PerceptionMemory] 初始化 (启用向量去重过滤)")

    async def connect_database(self, db_manager: AsyncDBManager = None):
        """连接数据库 (EyeCore 初始化时调用)"""
        # 优先使用传入的，否则使用全局单例
        self.db_manager = db_manager or async_db_manager

        try:
            logging.info("💾 [PerceptionMemory] 连接数据库...")
            await self.db_manager.initialize()

            # 健康检查
            if not await self.db_manager.health_check():
                logging.warning("⚠️ 数据库健康检查未通过，Eye 将运行在离线模式")
            else:
                logging.info("✅ 数据库连接就绪")

        except Exception as e:
            logging.error(f"❌ 数据库连接失败: {e}")

    async def store(self, perception_result: PerceptionResult) -> bool:
        """
        存储感知结果 (主入口)

        Args:
            perception_result: 包含检测框、计数、Stage2特征的结果对象
        """
        try:
            # 1. 提取 Stage 2 特征 (如果 EyeCore 没有产生，则为空列表)
            raw_features = getattr(perception_result, 'refine_features', [])

            # 2. 执行关键帧过滤 (方案 C: 去重)
            new_features = self._filter_redundant_features(raw_features)

            # 3. 更新事件状态 (并触发数据库写入)
            await self._update_event_state(perception_result, new_features)

            # 4. 记录到内存历史 (仅供调试)
            self.event_history.append({
                "timestamp": perception_result.timestamp,
                "event_id": perception_result.event_id,
                "detections": perception_result.detection_result.class_counts,
                "new_features_count": len(new_features)
            })
            if len(self.event_history) > 50:
                self.event_history = self.event_history[-20:]

            return True

        except Exception as e:
            logging.error(f"❌ [PerceptionMemory] 存储失败: {e}")
            return False

    def _filter_redundant_features(self, features: List[Dict]) -> List[Dict]:
        """
        [方案 C] 核心去重逻辑

        Args:
            features: 当前帧检测到的所有精修特征

        Returns:
            List[Dict]: 只有"有价值"的新特征会被保留
        """
        valid_features = []
        current_time = time.time()

        for feat in features:
            # 必须有 track_id 才能去重
            tid = feat.get('parent_track_id')
            if tid is None:
                continue

            # 获取/生成向量
            # (在真实 ReID 模型接入前，如果 vector 为空，我们先用 0 填充或跳过，避免报错)
            vector = feat.get('vector')
            if vector is None:
                # 模拟向量: 仅供测试架构连通性
                # 实际项目中应由 EyeCore/ReID 模型填充
                box = feat.get('global_box', [0, 0, 0, 0])
                # 简单用 box 生成一个伪向量，确保入库格式正确
                vector = [float(b) / 1000.0 for b in box] + [0.0] * (512 - 4)
                feat['vector'] = vector

                # 检查缓存
            cached = self.current_event.vector_cache.get(tid)

            is_useful = False
            if not cached:
                # 这是一个新出现的 ID
                is_useful = True
            else:
                # 这是一个已知 ID，检查是否需要更新
                time_diff = current_time - cached['last_time']

                # 规则: 至少间隔 min_update_interval 秒才检查
                if time_diff > self.min_update_interval:
                    # 计算相似度
                    sim = compute_cosine_similarity(vector, cached['vector'])

                    # 规则: 只有相似度低于阈值 (姿态/外观变了) 才保留
                    if sim < self.similarity_threshold:
                        is_useful = True
                        logging.debug(f"🔍 [Filter] ID={tid} 姿态变化 (Sim={sim:.3f})")

            if is_useful:
                # 更新缓存
                self.current_event.vector_cache[tid] = {
                    "vector": vector,
                    "last_time": current_time
                }
                # 标记时间戳
                feat['timestamp'] = datetime.now().isoformat()
                valid_features.append(feat)

        if valid_features:
            logging.debug(f"🧠 [Filter] 保留 {len(valid_features)}/{len(features)} 个关键特征")

        return valid_features

    async def _update_event_state(self, result: PerceptionResult, new_features: List[Dict]):
        """更新事件状态"""
        class_counts = result.detection_result.class_counts
        timestamp = result.timestamp
        is_visual_abnormal = "visual" in result.alert_tags

        # 如果有新特征，追加到累积列表
        if new_features:
            self.current_event.refine_data_accumulated.extend(new_features)
            # 防止无限膨胀: 仅保留最近 50 个关键特征
            if len(self.current_event.refine_data_accumulated) > 50:
                self.current_event.refine_data_accumulated = \
                    self.current_event.refine_data_accumulated[-50:]

        has_targets = bool(result.detection_result.detections)

        if has_targets:
            self.current_event.empty_frame_counter = 0

            # 检查最大持续时间
            if self.current_event.is_active:
                if self.current_event.start_time:
                    try:
                        start_ts = time.mktime(datetime.fromisoformat(self.current_event.start_time).timetuple())
                        event_duration = time.time() - start_ts
                        if event_duration > self.max_event_duration:
                            await self._close_event(timestamp)
                            # 立即开启新事件
                            await self._start_event(
                                timestamp, class_counts, is_visual_abnormal, result.alert_tags
                            )
                            result.event_id = self.current_event.event_id
                            return
                    except:
                        pass

            if not self.current_event.is_active:
                # 1. 开启新事件
                await self._start_event(
                    timestamp, class_counts, is_visual_abnormal, result.alert_tags
                )
            else:
                # 2. 更新现有事件
                self.current_event.update_counts(class_counts)
                if result.alert_tags:
                    self.current_event.alert_tags.update(result.alert_tags)

                await self._update_event_db(timestamp, new_features)

            result.event_id = self.current_event.event_id

        else:
            # 无目标逻辑
            self.current_event.empty_frame_counter += 1
            if (self.current_event.is_active and
                    self.current_event.empty_frame_counter >= self.loss_tolerance):
                await self._close_event(timestamp)

    async def _start_event(self, timestamp: str, counts: Dict, is_abnormal: bool, tags: Set[str]):
        """开始事件"""
        self.current_event.is_active = True
        self.current_event.start_time = timestamp
        self.current_event.last_update_time = timestamp
        self.current_event.max_counts = counts.copy()
        self.current_event.alert_tags = tags.copy()

        if self.db_manager:
            # 传入当前的累积特征 (refine_data)
            # 注意: 此时 accumulated 可能还为空，或者刚加入了第一帧的 feature
            event_id = await self.db_manager.start_event(
                timestamp, counts, is_abnormal, ",".join(tags),
                self.current_event.refine_data_accumulated
            )
            if event_id:
                self.current_event.event_id = event_id
            logging.info(f"📝 [PerceptionMemory] 事件开始: ID={event_id}, 目标={counts}")

    async def _update_event_db(self, timestamp: str, new_features: List[Dict]):
        """更新数据库 (方案 A 批量写入入口)"""
        if not self.db_manager or not self.current_event.event_id:
            return

        # 只有在有"新特征"或者"计数变化"或者"长时间未更新"时才推送到 DB
        # 为了简化，我们每次感知都推送到 Queue，由 AsyncDBManager 做缓冲聚合

        # 关键: refine_data 我们只在有新数据时才传入全量(覆盖)或增量
        # 这里的策略是: 如果 new_features 不为空，说明 refine_data 变了，传入最新的 accumulated
        refine_payload = self.current_event.refine_data_accumulated if new_features else None

        await self.db_manager.update_event(
            row_id=self.current_event.event_id,
            end_time=timestamp,
            max_targets=self.current_event.max_counts,
            is_abnormal=1 if "visual" in self.current_event.alert_tags else 0,
            alert_tags=",".join(self.current_event.alert_tags),
            refine_data=refine_payload  # 仅当有新数据时才传入，否则传 None (不更新字段)
        )

    async def _close_event(self, timestamp: str):
        """关闭事件"""
        if self.current_event.is_active:
            event_id = self.current_event.event_id
            if self.db_manager and event_id:
                await self.db_manager.close_event(event_id, timestamp)
                logging.info(f"📝 [PerceptionMemory] 事件关闭: ID={event_id}")

            self.current_event.reset()

    # 兼容旧接口
    async def update_event(self, *args, **kwargs):
        pass

    async def try_close_event(self):
        pass

    def get_event_history(self, limit: int = 10) -> List[Dict]:
        return self.event_history[-limit:] if self.event_history else []