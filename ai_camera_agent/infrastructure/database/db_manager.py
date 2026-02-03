# infrastructure/database/db_manager.py
"""
数据库管理器 (同步版) - 基于 PostgreSQL 重构

职责:
1. 提供 Web API 和 后台管理任务 的数据库访问
2. 系统启动时的表结构初始化
3. 连接池管理 (psycopg2)
"""
import logging
import json
import threading
from typing import Dict, List, Optional, Any, Generator
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json
from config.settings import DBConfig
from infrastructure.database import schemas


class DBManager:
    """PostgreSQL 数据库管理器（单例模式）"""

    _instance = None
    _lock = threading.Lock()
    _pool = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(DBManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._init_pool()
        self._init_tables()
        self._initialized = True
        logging.info(f"🐘 [DBManager] PostgreSQL 就绪: {DBConfig.HOST}:{DBConfig.PORT}/{DBConfig.DB_NAME}")

    def _init_pool(self):
        """初始化连接池"""
        try:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                minconn=DBConfig.POOL_MIN_SIZE,
                maxconn=DBConfig.POOL_MAX_SIZE,
                dsn=DBConfig.DATABASE_URL
            )
        except Exception as e:
            logging.critical(f"❌ [DBManager] 连接池创建失败: {e}")
            raise

    def _init_tables(self):
        """初始化表结构 (调用 schemas 定义)"""
        with self.get_cursor() as cur:
            try:
                for sql in schemas.get_init_sqls():
                    cur.execute(sql)
                logging.info("✅ [DBManager] 表结构初始化完成 (含 Vector 扩展)")
            except Exception as e:
                logging.error(f"❌ [DBManager] 建表失败: {e}")
                raise

    @contextmanager
    def get_cursor(self, commit: bool = True) -> Generator[Any, None, None]:
        """
        获取数据库游标的上下文管理器
        自动处理连接的获取(Get)和归还(Put)
        """
        conn = None
        try:
            conn = self._pool.getconn()
            # 使用 RealDictCursor 让查询结果返回字典而非元组
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
                if commit:
                    conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logging.error(f"❌ [DBManager] 数据库操作异常: {e}")
            raise
        finally:
            if conn:
                self._pool.putconn(conn)

    # ============================================================
    # 核心读写操作 (同步接口 - 供 Web/Admin 使用)
    # ============================================================

    def start_event(self, start_time: str, initial_targets: Dict[str, int],
                    is_abnormal: bool = False, alert_tags: str = "",
                    refine_data: List[Dict] = None) -> Optional[int]:
        """开始新事件"""
        # PostgreSQL 会自动将 Python dict/list 转为 JSONB
        # 但为了保险，psycopg2 通常推荐用 Json() 包装，或者直接传 dict 依赖适配器
        sql = """
        INSERT INTO security_events 
        (start_time, end_time, status, target_data, sys_summary, is_abnormal, alert_tags, refine_data)
        VALUES (%s, %s, 'ongoing', %s, %s, %s, %s, %s)
        RETURNING id
        """
        summary = self._fmt_summary(initial_targets)
        refine_json = Json(refine_data) if refine_data else Json([])
        target_json = Json(initial_targets)

        try:
            with self.get_cursor() as cur:
                cur.execute(sql, (
                    start_time, start_time, target_json,
                    summary, is_abnormal, alert_tags, refine_json
                ))
                event_id = cur.fetchone()['id']
                logging.info(f"📝 [DBManager] 事件创建: ID={event_id}")
                return event_id
        except Exception:
            return None

    def update_event(self, row_id: int, end_time: str, max_targets: Dict[str, int],
                     is_abnormal: Optional[bool] = None, alert_tags: Optional[str] = None):
        """更新事件"""
        target_json = Json(max_targets)
        summary = self._fmt_summary(max_targets)

        # 动态构建 SQL
        update_fields = ["end_time = %s", "target_data = %s", "sys_summary = %s"]
        params = [end_time, target_json, summary]

        if is_abnormal is not None:
            update_fields.append("is_abnormal = %s")
            params.append(is_abnormal)

        if alert_tags is not None:
            update_fields.append("alert_tags = %s")
            params.append(alert_tags)

        params.append(row_id)
        sql = f"UPDATE security_events SET {', '.join(update_fields)} WHERE id = %s"

        with self.get_cursor() as cur:
            cur.execute(sql, params)

    def search_logs(self, keyword: str = "all", only_abnormal: bool = False,
                    limit: int = 20) -> List[Dict[str, Any]]:
        """搜索日志 (适配 PostgreSQL 语法)"""
        sql = """
        SELECT id, start_time, sys_summary, ai_analysis, is_abnormal, 
               target_data, alert_tags, video_path 
        FROM security_events WHERE 1=1
        """
        params = []

        if only_abnormal:
            sql += " AND is_abnormal = TRUE"

        if keyword and keyword.lower() != "all":
            # 简单的文本模糊搜索
            sql += " AND (sys_summary ILIKE %s OR ai_analysis ILIKE %s OR alert_tags ILIKE %s)"
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        sql += " ORDER BY start_time DESC LIMIT %s"
        params.append(limit)

        results = []
        with self.get_cursor(commit=False) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

            for row in rows:
                # 构建前端所需的格式
                desc = row['sys_summary'] or ""
                if row['ai_analysis']:
                    desc += f" | 🤖 {row['ai_analysis']}"

                tags_str = row['alert_tags'] or ""
                if "visual" in tags_str: desc = "👁️ " + desc
                if "behavior" in tags_str: desc = "🧠 " + desc

                results.append({
                    "row_id": row['id'],
                    "start_time": str(row['start_time']),  # 转字符串供前端显示
                    "description": desc,
                    "is_abnormal": row['is_abnormal'],
                    "targets": row['target_data'],  # psycopg2 自动转回 dict
                    "alert_tags": tags_str,
                    "video_path": row['video_path']
                })
        return results

    # ============================================================
    # 工具方法
    # ============================================================

    def _fmt_summary(self, targets: Dict[str, int]) -> str:
        if not targets: return "无目标"
        parts = [f"{k}({v})" for k, v in targets.items()]
        return "发现: " + ", ".join(parts)

    def close_all(self):
        """关闭连接池"""
        if self._pool:
            self._pool.closeall()
            logging.info("🔒 [DBManager] 连接池已关闭")

    def __del__(self):
        self.close_all()