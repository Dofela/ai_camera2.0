# infrastructure/database/async_db_manager.py
"""
异步数据库管理器 - Eye 模块专用高性能引擎

核心特性:
1. 基于 asyncpg 的高性能连接池
2. 实现了 "方案 A" 批量写入策略 (Batch Writing)
   - 观察流 (INSERT) -> 缓冲队列 -> 批量提交
   - 事件更新 (UPDATE) -> 缓冲队列 -> 批量提交
3. 支持 JSONB 和 Vector 数据的高效存储
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
import asyncpg
from datetime import datetime

from config.settings import DBConfig


class AsyncDBManager:
    """
    Eye 模块专用异步数据库管理器 (单例模式)

    职责:
    1. 管理 Eye 模块的高频写入 (Vectors, Observations)
    2. 维护批量写入队列，防止 I/O 阻塞
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AsyncDBManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.pool: Optional[asyncpg.Pool] = None

        # 批量写入配置
        self.batch_size = 50        # 批次大小
        self.flush_interval = 1.0   # 刷新间隔(秒)

        # 缓冲队列
        # 队列项: (sql, params_tuple)
        self._obs_queue = asyncio.Queue()     # 观察流队列
        self._update_queue = asyncio.Queue()  # 事件更新队列

        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

        self._initialized = True
        logging.info("🚀 [AsyncDBManager] 异步引擎初始化 (AsyncPG + Batching)")

    async def initialize(self):
        """初始化连接池并启动后台 Worker"""
        async with self._lock:
            if self.pool:
                return

            try:
                # 创建连接池
                # 自动将 json 转换注册到连接中，方便 JSONB 存取
                self.pool = await asyncpg.create_pool(
                    dsn=DBConfig.DATABASE_URL,
                    min_size=DBConfig.EYE_POOL_MIN_SIZE,
                    max_size=DBConfig.EYE_POOL_MAX_SIZE,
                    init=self._init_connection
                )

                # 启动后台批处理 Worker
                self._running = True
                self._worker_task = asyncio.create_task(self._batch_worker())

                logging.info(f"✅ [AsyncDBManager] 连接池就绪: {DBConfig.EYE_POOL_MIN_SIZE}-{DBConfig.EYE_POOL_MAX_SIZE} Conns")

            except Exception as e:
                logging.critical(f"❌ [AsyncDBManager] 初始化失败: {e}")
                raise

    async def _init_connection(self, conn):
        """连接初始化钩子: 配置 JSONB 编解码"""
        await conn.set_type_codec(
            'jsonb',
            encoder=json.dumps,
            decoder=json.loads,
            schema='pg_catalog'
        )

    # ============================================================
    # 核心写操作 (业务接口)
    # ============================================================

    async def start_event(self, start_time: str, initial_targets: Dict[str, int],
                         is_abnormal: bool = False, alert_tags: str = "",
                         refine_data: List[Dict] = None) -> Optional[int]:
        """
        开始新事件 (同步等待返回 ID)

        注意: start_event 不能批处理，因为业务层立即需要 event_id
        """
        if not self.pool:
            logging.error("❌ DB未连接")
            return None

        summary = self._fmt_summary(initial_targets)
        # asyncpg 会自动处理 dict/list -> jsonb 的转换
        refine_payload = refine_data if refine_data else []

        sql = """
        INSERT INTO security_events 
        (start_time, end_time, status, target_data, sys_summary, is_abnormal, alert_tags, refine_data)
        VALUES ($1, $2, 'ongoing', $3, $4, $5, $6, $7)
        RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    sql,
                    datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time,
                    datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time,
                    initial_targets,
                    summary,
                    is_abnormal,
                    alert_tags,
                    refine_payload
                )
                event_id = row['id']
                logging.info(f"📝 [AsyncDBManager] 事件创建: ID={event_id} (实时)")
                return event_id
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] Start Event 失败: {e}")
            return None

    async def update_event(self, row_id: int, end_time: str, max_targets: Dict[str, int],
                          is_abnormal: Optional[bool] = None, alert_tags: Optional[str] = None,
                          refine_data: List[Dict] = None):
        """
        更新事件 (进入批量队列)

        核心优化: 这是高频操作，使用 "方案 A" 放入队列，后台批量 UPDATE
        """
        if not self.pool: return

        # 构建 UPDATE 语句
        # 为了支持 executemany，我们需要一个统一的 SQL 模板
        # 这里的策略是：即使某些字段不更新，也传入当前值（由业务层保证）
        # 但为了简单起见，我们这里针对最常见的高频更新场景优化：更新时间和目标数据

        # 如果有 refine_data (向量数据)，这是最“重”的操作，必须进队列

        target_json = max_targets
        summary = self._fmt_summary(max_targets)
        refine_payload = refine_data if refine_data else []

        # 动态构建 SQL 比较麻烦，对于批处理，最好固定 SQL
        # 这里我们假设 update_event 总是更新 end_time, target_data, sys_summary
        # is_abnormal, alert_tags, refine_data 是可选更新

        # 为了简化批处理逻辑，我们使用 COALESCE 或者在 Python 层处理
        # 这里采用一个通用 SQL，所有字段都传

        sql = """
        UPDATE security_events SET 
            end_time = $1, 
            target_data = $2, 
            sys_summary = $3,
            is_abnormal = COALESCE($4, is_abnormal),
            alert_tags = COALESCE($5, alert_tags),
            refine_data = CASE WHEN $6::jsonb IS NOT NULL THEN $6::jsonb ELSE refine_data END
        WHERE id = $7
        """

        params = (
            datetime.fromisoformat(end_time) if isinstance(end_time, str) else end_time,
            target_json,
            summary,
            is_abnormal,
            alert_tags,
            refine_payload if refine_data is not None else None, # 注意: None 在 SQL 中是 NULL
            row_id
        )

        # 放入队列 (Fire & Forget)
        try:
            self._update_queue.put_nowait((sql, params))
        except asyncio.QueueFull:
            logging.warning("⚠️ [AsyncDBManager] 更新队列已满，丢弃更新")

    async def insert_observation(self, content: str, target: str = "unknown"):
        """
        插入观察日志 (进入批量队列)

        核心优化: 典型的日志流，最适合批量 INSERT
        """
        sql = "INSERT INTO observation_stream (content, target, timestamp) VALUES ($1, $2, CURRENT_TIMESTAMP)"
        params = (content, target)

        try:
            self._obs_queue.put_nowait((sql, params))
        except asyncio.QueueFull:
            pass # 日志丢弃不影响主流程

    async def close_event(self, row_id: int, end_time: str):
        """关闭事件 (实时执行)"""
        if not self.pool: return

        sql = "UPDATE security_events SET status = 'closed', end_time = $1 WHERE id = $2"
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, datetime.fromisoformat(end_time) if isinstance(end_time, str) else end_time, row_id)
                logging.info(f"📝 [AsyncDBManager] 事件关闭: ID={row_id}")
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] Close Event 失败: {e}")

    async def update_video_path(self, event_id: int, video_path: str):
        """更新视频路径 (实时执行)"""
        if not self.pool: return
        sql = "UPDATE security_events SET video_path = $1 WHERE id = $2"
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(sql, video_path, event_id)
        except Exception as e:
            logging.error(f"❌ 更新视频路径失败: {e}")

    # ============================================================
    # 后台批处理 Worker (方案 A 核心)
    # ============================================================

    async def _batch_worker(self):
        """
        后台 Worker: 定期从队列取出数据并批量执行
        """
        logging.info("⚙️ [AsyncDBManager] 批处理 Worker 已启动")

        while self._running:
            try:
                # 1. 处理观察流 (INSERTs)
                await self._flush_queue(self._obs_queue, "观察流")

                # 2. 处理事件更新 (UPDATEs)
                await self._flush_queue(self._update_queue, "事件更新")

                # 休眠
                await asyncio.sleep(self.flush_interval)

            except Exception as e:
                logging.error(f"❌ [AsyncDBManager] Worker 异常: {e}")
                await asyncio.sleep(1.0)

    async def _flush_queue(self, queue: asyncio.Queue, name: str):
        """通用队列刷新逻辑"""
        if queue.empty():
            return

        batch_data = []
        sql_template = None

        # 取出当前队列中的所有项 (上限 batch_size)
        for _ in range(self.batch_size):
            if queue.empty():
                break

            try:
                item = queue.get_nowait()
                sql, params = item

                # 简单的批处理要求 SQL 语句必须一致
                if sql_template is None:
                    sql_template = sql
                elif sql != sql_template:
                    # 如果遇到不同的 SQL，先处理当前的批次，剩下的放回或这就提交
                    # 为了简化，我们只处理相同 SQL 的批次 (通常同个队列 SQL 是一样的)
                    # 实际生产中可能需要按 SQL 分组
                    logging.warning(f"⚠️ [AsyncDBManager] {name} SQL 不一致，跳过批处理优化")
                    # 这里简单的处理：如果 SQL 不同，回退该 item 并停止本轮
                    # 但为了不阻塞，我们假设同个队列的 SQL 是一致的 (由调用方保证)
                    pass

                batch_data.append(params)
                queue.task_done()

            except Exception:
                break

        if not batch_data or not sql_template:
            return

        # 执行批量操作
        try:
            async with self.pool.acquire() as conn:
                # executemany 是 asyncpg 的高性能利器
                await conn.executemany(sql_template, batch_data)
                logging.debug(f"⚡ [AsyncDBManager] {name} 批量提交: {len(batch_data)} 条")
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] {name} 批量提交失败: {e}")
            # 失败处理: 关键数据可能需要重试，但日志数据可丢弃

    # ============================================================
    # 辅助方法
    # ============================================================

    def _fmt_summary(self, targets: Dict[str, int]) -> str:
        if not targets: return "无目标"
        parts = [f"{k}({v})" for k, v in targets.items()]
        return "发现: " + ", ".join(parts)

    async def health_check(self) -> bool:
        if not self.pool: return False
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except:
            return False

    async def close_all(self):
        """关闭资源"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self.pool:
            await self.pool.close()
            logging.info("🔒 [AsyncDBManager] 连接池已关闭")

# 全局实例
async_db_manager = AsyncDBManager()