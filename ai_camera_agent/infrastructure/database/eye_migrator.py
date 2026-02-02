# infrastructure/database/eye_migrator.py
"""
眼睛模块数据库迁移工具

功能:
1. 从现有主数据库读取表结构
2. 创建新的 eye_module.db 数据库
3. 初始化表结构和索引
4. 提供状态检查和回滚机制
"""

import asyncio
import json
import logging
import os
import sqlite3
import aiosqlite
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from config.settings import DBConfig


class EyeDatabaseMigrator:
    """
    眼睛模块数据库迁移工具
    
    迁移流程:
    1. 读取源数据库表结构
    2. 创建目标数据库文件
    3. 创建表结构
    4. 创建索引
    5. 验证迁移结果
    6. 更新配置（可选）
    """
    
    def __init__(self, source_db_path: str = None, target_db_path: str = None):
        """
        初始化迁移工具
        
        Args:
            source_db_path: 源数据库路径（主数据库）
            target_db_path: 目标数据库路径（眼睛模块数据库）
        """
        self.source_db_path = source_db_path or DBConfig.DB_PATH
        self.target_db_path = target_db_path or DBConfig.EYE_DB_PATH
        
        # 迁移状态
        self.migration_steps = []
        self.current_step = 0
        self.is_rolled_back = False
        
        # 错误处理配置
        self.max_retries = 3
        self.retry_delay = 0.5
        
        logging.info(f"🔄 [EyeMigrator] 迁移工具初始化: {self.source_db_path} -> {self.target_db_path}")
    
    async def migrate(self) -> bool:
        """
        执行完整迁移流程
        
        Returns:
            bool: 迁移是否成功
        """
        try:
            self.migration_steps = []
            self.current_step = 0
            self.is_rolled_back = False
            
            # 定义迁移步骤
            steps = [
                ("检查源数据库", self._check_source_database),
                ("读取表结构", self._read_source_schema),
                ("创建目标数据库", self._create_target_database),
                ("创建表结构", self._create_tables),
                ("创建索引", self._create_indexes),
                ("验证迁移结果", self._validate_migration),
            ]
            
            # 执行每个步骤
            for step_name, step_func in steps:
                self.current_step += 1
                logging.info(f"🔄 [EyeMigrator] 步骤 {self.current_step}/{len(steps)}: {step_name}")
                
                success = await self._execute_with_retry(step_func, step_name)
                if not success:
                    logging.error(f"❌ [EyeMigrator] 步骤失败: {step_name}")
                    await self.rollback()
                    return False
                
                self.migration_steps.append({
                    "step": step_name,
                    "status": "completed",
                    "timestamp": datetime.now().isoformat()
                })
            
            logging.info("✅ [EyeMigrator] 数据库迁移完成")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 迁移过程异常: {e}")
            await self.rollback()
            return False
    
    async def _execute_with_retry(self, func, step_name: str) -> bool:
        """带重试的执行函数"""
        for attempt in range(self.max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logging.error(f"❌ [EyeMigrator] {step_name} 失败 (尝试 {attempt + 1} 次): {e}")
                    raise
                
                delay = self.retry_delay * (2 ** attempt)  # 指数退避
                logging.warning(f"⚠️ [EyeMigrator] {step_name} 失败，{delay}秒后重试: {e}")
                await asyncio.sleep(delay)
        
        return False
    
    async def _check_source_database(self) -> bool:
        """检查源数据库是否可访问"""
        try:
            if not os.path.exists(self.source_db_path):
                logging.warning(f"⚠️ [EyeMigrator] 源数据库不存在: {self.source_db_path}")
                # 如果源数据库不存在，仍然可以继续（创建空数据库）
                return True
            
            # 测试连接
            conn = sqlite3.connect(self.source_db_path)
            cursor = conn.cursor()
            
            # 检查是否有需要的表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            required_tables = {"security_events", "observation_stream"}
            existing_tables = set(tables)
            
            logging.info(f"📊 [EyeMigrator] 源数据库表: {tables}")
            
            conn.close()
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 检查源数据库失败: {e}")
            raise
    
    async def _read_source_schema(self) -> bool:
        """读取源数据库表结构"""
        try:
            if not os.path.exists(self.source_db_path):
                # 如果源数据库不存在，使用默认表结构
                self.table_schemas = self._get_default_schemas()
                logging.info("📋 [EyeMigrator] 使用默认表结构")
                return True
            
            conn = sqlite3.connect(self.source_db_path)
            cursor = conn.cursor()
            
            # 读取表结构
            self.table_schemas = {}
            
            # 获取所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            for table in tables:
                if table in ["security_events", "observation_stream"]:
                    # 获取建表语句
                    cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                    result = cursor.fetchone()
                    if result:
                        self.table_schemas[table] = result[0]
            
            # 获取索引
            self.index_schemas = []
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
            indexes = cursor.fetchall()
            for index in indexes:
                self.index_schemas.append(index[0])
            
            conn.close()
            
            logging.info(f"📋 [EyeMigrator] 读取到 {len(self.table_schemas)} 个表结构")
            logging.info(f"📋 [EyeMigrator] 读取到 {len(self.index_schemas)} 个索引")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 读取表结构失败: {e}")
            raise
    
    def _get_default_schemas(self) -> Dict[str, str]:
        """获取默认表结构（当源数据库不存在时使用）"""
        return {
            "security_events": """
                CREATE TABLE security_events (
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
                )
            """,
            "observation_stream": """
                CREATE TABLE observation_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    content TEXT,
                    target TEXT
                )
            """
        }
    
    async def _create_target_database(self) -> bool:
        """创建目标数据库文件"""
        try:
            # 检查目标数据库是否已存在
            if os.path.exists(self.target_db_path):
                logging.warning(f"⚠️ [EyeMigrator] 目标数据库已存在: {self.target_db_path}")
                # 备份原文件
                backup_path = f"{self.target_db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                import shutil
                shutil.copy2(self.target_db_path, backup_path)
                logging.info(f"📦 [EyeMigrator] 已备份原数据库: {backup_path}")
            
            # 创建目录（如果需要）
            target_dir = os.path.dirname(self.target_db_path)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            
            # 创建空数据库文件
            async with aiosqlite.connect(self.target_db_path) as conn:
                # 启用WAL模式
                await conn.execute("PRAGMA journal_mode=WAL;")
                await conn.execute("PRAGMA synchronous=NORMAL;")
                await conn.execute("PRAGMA foreign_keys=ON;")
                await conn.commit()
            
            logging.info(f"✅ [EyeMigrator] 目标数据库创建完成: {self.target_db_path}")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 创建目标数据库失败: {e}")
            raise
    
    async def _create_tables(self) -> bool:
        """在目标数据库创建表"""
        try:
            async with aiosqlite.connect(self.target_db_path) as conn:
                for table_name, create_sql in self.table_schemas.items():
                    # 确保SQL语句是有效的
                    if create_sql:
                        await conn.execute(create_sql)
                        logging.info(f"📊 [EyeMigrator] 创建表: {table_name}")
                
                await conn.commit()
            
            logging.info(f"✅ [EyeMigrator] 表结构创建完成: {len(self.table_schemas)} 个表")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 创建表失败: {e}")
            raise
    
    async def _create_indexes(self) -> bool:
        """创建索引"""
        try:
            if not hasattr(self, 'index_schemas') or not self.index_schemas:
                # 创建默认索引
                self.index_schemas = [
                    "CREATE INDEX IF NOT EXISTS idx_status ON security_events (status);",
                    "CREATE INDEX IF NOT EXISTS idx_start_time ON security_events (start_time);",
                    "CREATE INDEX IF NOT EXISTS idx_abnormal ON security_events (is_abnormal);",
                    "CREATE INDEX IF NOT EXISTS idx_alert_tags ON security_events (alert_tags);"
                ]
            
            async with aiosqlite.connect(self.target_db_path) as conn:
                for index_sql in self.index_schemas:
                    if index_sql:
                        await conn.execute(index_sql)
                
                await conn.commit()
            
            logging.info(f"✅ [EyeMigrator] 索引创建完成: {len(self.index_schemas)} 个索引")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 创建索引失败: {e}")
            raise
    
    async def _validate_migration(self) -> bool:
        """验证迁移结果"""
        try:
            async with aiosqlite.connect(self.target_db_path) as conn:
                # 检查表是否存在
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in await cursor.fetchall()]
                await cursor.close()
                
                required_tables = set(self.table_schemas.keys())
                existing_tables = set(tables)
                
                missing_tables = required_tables - existing_tables
                if missing_tables:
                    logging.error(f"❌ [EyeMigrator] 缺失表: {missing_tables}")
                    return False
                
                # 检查索引
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
                indexes = [row[0] for row in await cursor.fetchall()]
                await cursor.close()
                
                # 基本健康检查
                cursor = await conn.execute("SELECT 1")
                result = await cursor.fetchone()
                await cursor.close()
                
                if not result or result[0] != 1:
                    logging.error("❌ [EyeMigrator] 健康检查失败")
                    return False
            
            logging.info(f"✅ [EyeMigrator] 迁移验证通过: {len(tables)} 个表, {len(indexes)} 个索引")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 迁移验证失败: {e}")
            raise
    
    async def rollback(self) -> bool:
        """
        回滚迁移
        
        删除已创建的数据库文件，恢复系统状态
        """
        try:
            if self.is_rolled_back:
                logging.info("🔄 [EyeMigrator] 回滚已完成，跳过")
                return True
            
            # 删除目标数据库文件
            if os.path.exists(self.target_db_path):
                os.remove(self.target_db_path)
                logging.info(f"🗑️ [EyeMigrator] 已删除目标数据库: {self.target_db_path}")
            
            self.is_rolled_back = True
            logging.info("✅ [EyeMigrator] 回滚完成")
            return True
            
        except Exception as e:
            logging.error(f"❌ [EyeMigrator] 回滚失败: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """获取迁移状态"""
        return {
            "source_db": self.source_db_path,
            "target_db": self.target_db_path,
            "current_step": self.current_step,
            "total_steps": len(self.migration_steps) if hasattr(self, 'migration_steps') else 0,
            "steps": self.migration_steps if hasattr(self, 'migration_steps') else [],
            "is_rolled_back": self.is_rolled_back,
            "table_count": len(self.table_schemas) if hasattr(self, 'table_schemas') else 0,
            "index_count": len(self.index_schemas) if hasattr(self, 'index_schemas') else 0,
        }


# 便捷函数
async def migrate_eye_database() -> bool:
    """执行眼睛模块数据库迁移（便捷函数）"""
    migrator = EyeDatabaseMigrator()
    return await migrator.migrate()


async def check_eye_database() -> Dict[str, Any]:
    """检查眼睛模块数据库状态"""
    migrator = EyeDatabaseMigrator()
    
    status = {
        "source_exists": os.path.exists(migrator.source_db_path),
        "target_exists": os.path.exists(migrator.target_db_path),
        "config": {
            "eye_db_path": DBConfig.EYE_DB_PATH,
            "main_db_path": DBConfig.DB_PATH,
        }
    }
    
    # 检查目标数据库结构
    if status["target_exists"]:
        try:
            async with aiosqlite.connect(migrator.target_db_path) as conn:
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in await cursor.fetchall()]
                await cursor.close()
                
                status["tables"] = tables
                status["table_count"] = len(tables)
                
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
                indexes = [row[0] for row in await cursor.fetchall()]
                await cursor.close()
                
                status["indexes"] = indexes
                status["index_count"] = len(indexes)
                
        except Exception as e:
            status["error"] = str(e)
    
    return status