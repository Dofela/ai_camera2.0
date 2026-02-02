# infrastructure/database/async_db_manager.py
"""
异步数据库管理器 - 眼睛模块专用

基于 aiosqlite 实现异步数据库操作，支持连接池和错误重试。
专为眼睛模块设计，提供与现有 DBManager 兼容的接口。
"""

import asyncio
import json
import logging
import aiosqlite
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

from config.settings import DBConfig


class AsyncDBManager:
    """
    眼睛模块异步数据库管理器
    
    功能:
    1. 异步数据库操作 (使用 aiosqlite)
    2. 连接池管理
    3. 错误重试机制
    4. 与现有 DBManager 兼容的接口
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
            
        self.db_path = DBConfig.EYE_DB_PATH
        self.pool_size = DBConfig.EYE_POOL_SIZE
        self.use_wal = DBConfig.USE_WAL
        
        # 连接池
        self._connection_pool = []
        self._pool_lock = asyncio.Lock()
        self._max_connections = self.pool_size
        self._active_connections = 0
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 0.1  # 初始延迟秒数
        
        self._initialized = True
        logging.info(f"💾 [AsyncDBManager] 异步数据库管理器初始化完成: {self.db_path}")
    
    async def initialize(self):
        """初始化数据库连接池到完整容量"""
        async with self._pool_lock:
            if self._connection_pool:
                logging.warning("⚠️ 连接池已初始化")
                return
            
            logging.info(f"🔗 创建 {self._max_connections} 个数据库连接...")
            
            # 并发创建所有连接
            tasks = [
                self._create_connection()
                for _ in range(self._max_connections)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 计算成功和失败
            successes = 0
            failures = 0
            
            for result in results:
                if isinstance(result, Exception):
                    logging.error(f"❌ 连接创建失败: {result}")
                    failures += 1
                elif result is not None:
                    self._connection_pool.append(result)
                    self._active_connections += 1
                    successes += 1
                else:
                    failures += 1
            
            if successes == 0:
                raise RuntimeError(
                    f"无法创建任何数据库连接 "
                    f"({failures} 个失败)"
                )
            
            if failures > 0:
                logging.warning(
                    f"⚠️ 创建了 {successes}/{self._max_connections} 个连接 "
                    f"({failures} 个失败)"
                )
            else:
                logging.info(
                    f"✅ 连接池初始化完成: "
                    f"{successes}/{self._max_connections} 个连接就绪"
                )
    
    async def _create_connection(self) -> Optional[aiosqlite.Connection]:
        """创建新的数据库连接"""
        try:
            conn = await aiosqlite.connect(self.db_path)
            
            if self.use_wal:
                await conn.execute("PRAGMA journal_mode=WAL;")
                await conn.execute("PRAGMA synchronous=NORMAL;")
            
            # 启用外键约束
            await conn.execute("PRAGMA foreign_keys=ON;")
            
            # 初始化表结构
            await self._init_tables(conn)
            
            return conn
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] 创建连接失败: {e}")
            return None
    
    async def _init_tables(self, conn: aiosqlite.Connection):
        """初始化数据表结构"""
        try:
            # 安全事件表（支持双重警报标签）
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT DEFAULT 'ongoing',
                    
                    start_time TEXT,
                    end_time TEXT,
                    
                    target_data TEXT,    -- JSON: {"person": 3, "fire": 1}
                    sys_summary TEXT,    -- 系统描述
                    ai_analysis TEXT,    -- LLM 描述
                    
                    is_abnormal INTEGER DEFAULT 0, -- 0:正常, 1:异常
                    alert_tags TEXT,     -- "visual,behavior" (逗号分隔)
                    
                    snapshot_path TEXT,
                    video_path TEXT      -- 报警视频路径
                );
            """)
            
            # 创建索引
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON security_events (status);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_start_time ON security_events (start_time);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_abnormal ON security_events (is_abnormal);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_tags ON security_events (alert_tags);")
            
            # 观察流表（用于记录观察结果）
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS observation_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    content TEXT,
                    target TEXT
                );
            """)
            
            await conn.commit()
            logging.info("✅ [AsyncDBManager] 数据表初始化完成")
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] 建表失败: {e}")
            raise
    
    @asynccontextmanager
    async def _get_connection(self):
        """获取数据库连接（连接池管理）"""
        conn = None
        try:
            async with self._pool_lock:
                if self._connection_pool:
                    conn = self._connection_pool.pop()
                elif self._active_connections < self._max_connections:
                    conn = await self._create_connection()
                    if conn:
                        self._active_connections += 1
            
            if not conn:
                # 如果连接池已满且没有可用连接，创建临时连接
                conn = await aiosqlite.connect(self.db_path)
                logging.debug("📡 [AsyncDBManager] 创建临时连接")
            
            yield conn
            
        finally:
            if conn:
                # 如果是临时连接，直接关闭
                if conn not in self._connection_pool and self._active_connections < self._max_connections:
                    async with self._pool_lock:
                        if len(self._connection_pool) < self._max_connections:
                            self._connection_pool.append(conn)
                        else:
                            await conn.close()
                elif conn not in self._connection_pool:
                    await conn.close()
    
    async def _execute_with_retry(self, sql: str, params: tuple = None):
        """带重试的SQL执行"""
        for attempt in range(self.max_retries):
            try:
                async with self._get_connection() as conn:
                    cursor = await conn.execute(sql, params or ())
                    await conn.commit()
                    return cursor
                    
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logging.error(f"❌ [AsyncDBManager] SQL执行失败 (尝试 {attempt + 1} 次): {e}")
                    raise
                
                delay = self.retry_delay * (2 ** attempt)  # 指数退避
                logging.warning(f"⚠️ [AsyncDBManager] SQL执行失败，{delay}秒后重试: {e}")
                await asyncio.sleep(delay)
    
    # ============================================================
    # 核心写操作（适配双重警报）
    # ============================================================
    
    async def start_event(self, start_time: str, initial_targets: Dict[str, int], 
                         is_abnormal: int = 0, alert_tags: str = "") -> Optional[int]:
        """
        开始新事件（异步）
        
        Args:
            start_time: 开始时间
            initial_targets: 初始目标计数
            is_abnormal: 是否异常（0:正常, 1:异常）
            alert_tags: 报警标签（逗号分隔）
            
        Returns:
            事件ID
        """
        targets_json = json.dumps(initial_targets, ensure_ascii=False)
        summary = self._fmt_summary(initial_targets)
        
        sql = """
        INSERT INTO security_events 
        (start_time, end_time, status, target_data, sys_summary, is_abnormal, alert_tags)
        VALUES (?, ?, 'ongoing', ?, ?, ?, ?)
        """
        
        try:
            cursor = await self._execute_with_retry(
                sql, (start_time, start_time, targets_json, summary, is_abnormal, alert_tags)
            )
            event_id = cursor.lastrowid
            
            logging.info(f"📝 [AsyncDBManager] 事件开始: ID={event_id}, 目标={initial_targets}")
            return event_id
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] Start Event 失败: {e}")
            return None
    
    async def update_event(self, row_id: int, end_time: str, max_targets: Dict[str, int],
                          is_abnormal: Optional[int] = None, alert_tags: Optional[str] = None):
        """
        更新事件（异步）
        
        Args:
            row_id: 事件ID
            end_time: 结束时间
            max_targets: 最大目标计数
            is_abnormal: 是否异常（None表示不更新）
            alert_tags: 报警标签（None表示不更新）
        """
        targets_json = json.dumps(max_targets, ensure_ascii=False)
        summary = self._fmt_summary(max_targets)
        
        sql = """
        UPDATE security_events 
        SET end_time = ?, target_data = ?, sys_summary = ?
        """
        params = [end_time, targets_json, summary]
        
        if is_abnormal is not None:
            sql += ", is_abnormal = ?"
            params.append(is_abnormal)
        
        if alert_tags is not None:
            sql += ", alert_tags = ?"
            params.append(alert_tags)
        
        sql += " WHERE id = ?"
        params.append(row_id)
        
        try:
            await self._execute_with_retry(sql, tuple(params))
            logging.info(f"📝 [AsyncDBManager] 事件更新: ID={row_id}")
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] Update Event 失败: {e}")
    
    async def close_event(self, row_id: int, end_time: str):
        """
        关闭事件（异步）
        
        Args:
            row_id: 事件ID
            end_time: 结束时间
        """
        sql = "UPDATE security_events SET status = 'closed', end_time = ? WHERE id = ?"
        
        try:
            await self._execute_with_retry(sql, (end_time, row_id))
            logging.info(f"📝 [AsyncDBManager] 事件关闭: ID={row_id}")
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] Close Event 失败: {e}")
    
    async def update_video_path(self, event_id: int, video_path: str):
        """
        更新事件的视频路径
        
        Args:
            event_id: 事件ID
            video_path: 视频文件路径
        """
        sql = "UPDATE security_events SET video_path = ? WHERE id = ?"
        
        try:
            await self._execute_with_retry(sql, (video_path, event_id))
            logging.info(f"💾 [AsyncDBManager] 视频路径更新: ID={event_id}, 路径={video_path}")
            
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] 更新视频路径失败: {e}")
            raise
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _fmt_summary(self, targets: Dict[str, int]) -> str:
        """格式化系统描述"""
        if not targets:
            return "无目标"
        
        items = []
        for cls_name, count in targets.items():
            if count > 0:
                items.append(f"{cls_name}:{count}")
        
        return " | ".join(items) if items else "无目标"
    
    async def health_check(self) -> bool:
        """健康检查：验证数据库连接是否正常"""
        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                await cursor.close()
                
                return result is not None and result[0] == 1
                
        except Exception as e:
            logging.error(f"❌ [AsyncDBManager] 健康检查失败: {e}")
            return False
    
    async def close_all(self):
        """关闭所有数据库连接"""
        async with self._pool_lock:
            for conn in self._connection_pool:
                try:
                    await conn.close()
                except Exception as e:
                    logging.error(f"❌ [AsyncDBManager] 关闭连接失败: {e}")
            
            self._connection_pool.clear()
            self._active_connections = 0
            logging.info("🔒 [AsyncDBManager] 所有数据库连接已关闭")


# 全局实例
async_db_manager = AsyncDBManager()