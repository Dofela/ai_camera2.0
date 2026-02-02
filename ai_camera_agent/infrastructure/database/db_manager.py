# infrastructure/database/db_manager.py
"""
数据库管理器 - 基于old_app的数据库逻辑重构

支持双重警报标签系统：
- visual: 视觉高危报警（如fire, knife等）
- behavior: 行为异常报警（VLM分析结果）
"""
import sqlite3
import json
import threading
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from config.settings import DBConfig


class DBManager:
    """数据库管理器（单例模式）"""
    
    _instance = None
    _lock = threading.Lock()
    
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
            
        self.db_path = DBConfig.DB_PATH
        self._init_connection()
        self._init_table()
        self._initialized = True
        logging.info(f"💾 [DBManager] 数据库就绪 (支持双重警报标签): {self.db_path}")
    
    def _init_connection(self):
        """初始化数据库连接"""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        if DBConfig.USE_WAL:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
    
    def _init_table(self):
        """初始化数据表"""
        with self._lock:
            try:
                cursor = self._conn.cursor()
                
                # 安全事件表（支持双重警报标签）
                sql = """
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
                """
                cursor.execute(sql)
                
                # 创建索引
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON security_events (status);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_start_time ON security_events (start_time);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_abnormal ON security_events (is_abnormal);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_tags ON security_events (alert_tags);")
                
                # 观察流表（用于记录观察结果）
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS observation_stream (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    content TEXT,
                    target TEXT
                );
                """)
                
                self._conn.commit()
                logging.info("✅ [DBManager] 数据表初始化完成")
                
            except Exception as e:
                logging.error(f"❌ [DBManager] 建表失败: {e}")
                raise
    
    # ============================================================
    # 核心写操作（适配双重警报）
    # ============================================================
    
    def start_event(self, start_time: str, initial_targets: Dict[str, int], 
                   is_abnormal: int = 0, alert_tags: str = "") -> Optional[int]:
        """
        开始新事件
        
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
        
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(sql, (start_time, start_time, targets_json, summary, is_abnormal, alert_tags))
                self._conn.commit()
                event_id = cursor.lastrowid
                logging.info(f"📝 [DBManager] 事件开始: ID={event_id}, 目标={initial_targets}")
                return event_id
            except Exception as e:
                logging.error(f"❌ [DBManager] Start Event 失败: {e}")
                return None
    
    def update_event(self, row_id: int, end_time: str, max_targets: Dict[str, int],
                    is_abnormal: Optional[int] = None, alert_tags: Optional[str] = None):
        """
        更新事件
        
        Args:
            row_id: 事件ID
            end_time: 结束时间
            max_targets: 最大目标计数
            is_abnormal: 是否异常（None表示不更新）
            alert_tags: 报警标签（None表示不更新）
        """
        targets_json = json.dumps(max_targets, ensure_ascii=False)
        summary = self._fmt_summary(max_targets)
        
        # 动态构建SQL
        update_fields = ["end_time = ?", "target_data = ?", "sys_summary = ?"]
        params = [end_time, targets_json, summary]
        
        if is_abnormal is not None:
            update_fields.append("is_abnormal = ?")
            params.append(is_abnormal)
        
        if alert_tags is not None:
            update_fields.append("alert_tags = ?")
            params.append(alert_tags)
        
        params.append(row_id)
        sql = f"UPDATE security_events SET {', '.join(update_fields)} WHERE id = ?"
        
        with self._lock:
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
                logging.debug(f"📝 [DBManager] 事件更新: ID={row_id}")
            except Exception as e:
                logging.error(f"❌ [DBManager] Update Event 失败: {e}")
    
    def add_ai_analysis(self, row_id: int, analysis_text: str, is_abnormal: bool,
                       new_tags: Optional[str] = None, video_path: Optional[str] = None):
        """
        添加AI分析结果
        
        Args:
            row_id: 事件ID
            analysis_text: 分析文本
            is_abnormal: 是否异常
            new_tags: 新标签（追加）
            video_path: 视频路径
        """
        abnormal_val = 1 if is_abnormal else 0
        
        # 构建SQL
        sql = """
        UPDATE security_events
        SET ai_analysis = ?, is_abnormal = MAX(is_abnormal, ?)
        """
        params = [analysis_text, abnormal_val]
        
        if video_path:
            sql += ", video_path = ?"
            params.append(video_path)
        
        if new_tags:
            sql += ", alert_tags = ?"
            params.append(new_tags)
        
        sql += " WHERE id = ?"
        params.append(row_id)
        
        with self._lock:
            try:
                self._conn.execute(sql, params)
                self._conn.commit()
                logging.info(f"🤖 [DBManager] AI分析添加: ID={row_id}, 异常={is_abnormal}")
            except Exception as e:
                logging.error(f"❌ [DBManager] Add AI Analysis 失败: {e}")
    
    def close_event(self, row_id: int, end_time: str):
        """关闭事件"""
        sql = "UPDATE security_events SET status = 'closed', end_time = ? WHERE id = ?"
        with self._lock:
            try:
                self._conn.execute(sql, (end_time, row_id))
                self._conn.commit()
                logging.info(f"📝 [DBManager] 事件关闭: ID={row_id}")
            except Exception as e:
                logging.error(f"❌ [DBManager] Close Event 失败: {e}")
    
    def update_video_path(self, row_id: int, video_path: str):
        """更新视频路径"""
        sql = "UPDATE security_events SET video_path = ? WHERE id = ?"
        with self._lock:
            try:
                self._conn.execute(sql, (video_path, row_id))
                self._conn.commit()
            except Exception as e:
                logging.error(f"❌ [DBManager] Update Video Path 失败: {e}")
    
    # ============================================================
    # 查询操作
    # ============================================================
    
    def search_logs(self, keyword: str = "all", only_abnormal: bool = False,
                   limit: int = 20, start_date: Optional[str] = None,
                   end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        搜索日志
        
        Returns:
            日志列表
        """
        sql = """
        SELECT start_time, sys_summary, ai_analysis, is_abnormal, 
               target_data, alert_tags, id, video_path 
        FROM security_events WHERE 1=1
        """
        params = []
        
        if only_abnormal:
            sql += " AND is_abnormal = 1"
        if start_date:
            sql += " AND start_time >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND start_time <= ?"
            params.append(end_date)
        if keyword and keyword.lower() != "all":
            sql += " AND (sys_summary LIKE ? OR ai_analysis LIKE ? OR target_data LIKE ? OR alert_tags LIKE ?)"
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])
        
        sql += " ORDER BY start_time DESC LIMIT ?"
        params.append(limit)
        
        results = []
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            for row in rows:
                # 构建描述
                desc = row[1]  # sys_summary
                if row[2]:  # ai_analysis
                    desc += f" | 🤖 {row[2]}"
                
                # 添加标签前缀
                tags_str = row[5] if row[5] else ""
                if "visual" in tags_str:
                    desc = "👁️[视觉报警] " + desc
                if "behavior" in tags_str:
                    desc = "🧠[行为报警] " + desc
                
                results.append({
                    "start_time": row[0],
                    "description": desc,
                    "is_abnormal": bool(row[3]),
                    "targets": json.loads(row[4]) if row[4] else {},
                    "alert_tags": tags_str,
                    "row_id": row[6],
                    "video_path": row[7]
                })
                
        except Exception as e:
            logging.error(f"❌ [DBManager] Search Logs 失败: {e}")
        
        return results
    
    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        """获取单个事件"""
        sql = """
        SELECT start_time, end_time, status, target_data, sys_summary, 
               ai_analysis, is_abnormal, alert_tags, video_path 
        FROM security_events WHERE id = ?
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, (event_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    "start_time": row[0],
                    "end_time": row[1],
                    "status": row[2],
                    "targets": json.loads(row[3]) if row[3] else {},
                    "sys_summary": row[4],
                    "ai_analysis": row[5],
                    "is_abnormal": bool(row[6]),
                    "alert_tags": row[7],
                    "video_path": row[8]
                }
        except Exception as e:
            logging.error(f"❌ [DBManager] Get Event 失败: {e}")
        
        return None
    
    def get_active_events(self) -> List[Dict[str, Any]]:
        """获取活跃事件"""
        sql = """
        SELECT id, start_time, target_data, alert_tags 
        FROM security_events WHERE status = 'ongoing' ORDER BY start_time DESC
        """
        results = []
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            for row in rows:
                results.append({
                    "id": row[0],
                    "start_time": row[1],
                    "targets": json.loads(row[2]) if row[2] else {},
                    "alert_tags": row[3]
                })
        except Exception as e:
            logging.error(f"❌ [DBManager] Get Active Events 失败: {e}")
        
        return results
    
    # ============================================================
    # 观察流操作
    # ============================================================
    
    def insert_observation(self, content: str, target: str = "unknown"):
        """插入观察记录"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO observation_stream (timestamp, content, target) VALUES (?, ?, ?)",
                    (now, content, target)
                )
                self._conn.commit()
                logging.debug(f"📝 [DBManager] 观察记录: {content[:50]}...")
        except Exception as e:
            logging.error(f"❌ [DBManager] Insert Observation 失败: {e}")
    
    def get_recent_observations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的观察记录"""
        sql = "SELECT timestamp, content, target FROM observation_stream ORDER BY timestamp DESC LIMIT ?"
        results = []
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()
            
            for row in rows:
                results.append({
                    "timestamp": row[0],
                    "content": row[1],
                    "target": row[2]
                })
        except Exception as e:
            logging.error(f"❌ [DBManager] Get Observations 失败: {e}")
        
        return results
    
    # ============================================================
    # 工具方法
    # ============================================================
    
    def _fmt_summary(self, targets: Dict[str, int]) -> str:
        """格式化目标摘要"""
        if not targets:
            return "无目标"
        parts = [f"{k}({v})" for k, v in targets.items()]
        return "发现: " + ", ".join(parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {}
        try:
            cursor = self._conn.cursor()
            
            # 总事件数
            cursor.execute("SELECT COUNT(*) FROM security_events")
            stats["total_events"] = cursor.fetchone()[0]
            
            # 异常事件数
            cursor.execute("SELECT COUNT(*) FROM security_events WHERE is_abnormal = 1")
            stats["abnormal_events"] = cursor.fetchone()[0]
            
            # 活跃事件数
            cursor.execute("SELECT COUNT(*) FROM security_events WHERE status = 'ongoing'")
            stats["active_events"] = cursor.fetchone()[0]
            
            # 观察记录数
            cursor.execute("SELECT COUNT(*) FROM observation_stream")
            stats["observations"] = cursor.fetchone()[0]
            
        except Exception as e:
            logging.error(f"❌ [DBManager] Get Stats 失败: {e}")
        
        return stats
    
    def cleanup_old_events(self, days: int = 30):
        """清理旧事件"""
        try:
            cutoff_date = datetime.now().strftime("%Y-%m-%d")
            sql = "DELETE FROM security_events WHERE date(start_time) < date(?, ?)"
            with self._lock:
                self._conn.execute(sql, (cutoff_date, f"-{days} days"))
                self._conn.commit()
                logging.info(f"🧹 [DBManager] 清理了{days}天前的事件")
        except Exception as e:
            logging.error(f"❌ [DBManager] Cleanup 失败: {e}")
    
    def __del__(self):
        """析构函数"""
        try:
            if hasattr(self, '_conn'):
                self._conn.close()
        except:
            pass