# hand/alert/alert_dispatcher.py
"""
报警分发器 - 实时推送报警信息到前端

支持的报警类型：
- alert: 紧急报警（红色提示）
- log_update: 日志更新（蓝色提示）
- observation: 观察模式更新
- dismiss_all: 清除所有报警
- mute: 静音期间
- vision_update: 视觉检测目标变更
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import WebSocket
from fastapi.websockets import WebSocketState


class AlertDispatcher:
    """
    报警分发器 - 管理 WebSocket 连接并广播报警信息
    
    这是一个单例类，全局共享连接状态。
    """
    _connections = set()
    _muted_until: Optional[float] = None  # 静音截止时间戳
    _alert_history: List[Dict] = []  # 报警历史（最近100条）

    @classmethod
    async def register(cls, websocket: WebSocket):
        """注册新的 WebSocket 连接"""
        await websocket.accept()
        cls._connections.add(websocket)
        logging.info(f"🔔 [Alert] 新客户端连接，当前总数: {len(cls._connections)}")

    @classmethod
    async def unregister(cls, websocket: WebSocket):
        """注销 WebSocket 连接"""
        if websocket in cls._connections:
            cls._connections.remove(websocket)
            logging.info(f"🔔 [Alert] 客户端断开，当前总数: {len(cls._connections)}")

    @classmethod
    async def notify(cls, data: Dict):
        """
        广播警报信息
        
        Args:
            data: 报警数据，包含以下字段：
                - alert: 报警标题
                - description: 详细描述
                - is_abnormal: 是否异常
                - type: 报警类型 (alert/log_update/observation/vision_update)
                - tags: 标签列表
                - row_id: 关联的数据库记录ID
        """
        # 检查是否在静音期
        if cls._muted_until and time.time() < cls._muted_until:
            if data.get('type') == 'alert':
                logging.debug(f"🔇 [Alert] 静音期间，跳过报警: {data.get('description', '')[:30]}")
                return
        
        # 添加时间戳
        message_data = {
            "timestamp": datetime.now().astimezone().isoformat(),
            **data
        }
        
        # 记录到历史
        cls._alert_history.append(message_data)
        if len(cls._alert_history) > 100:
            cls._alert_history.pop(0)
        
        message = json.dumps(message_data, ensure_ascii=False)
        
        # 广播到所有连接
        for conn in list(cls._connections):
            try:
                if conn.client_state == WebSocketState.CONNECTED:
                    await conn.send_text(message)
                else:
                    cls._connections.discard(conn)
            except Exception as e:
                logging.warning(f"⚠️ 推送失败移除连接: {e}")
                cls._connections.discard(conn)

    @classmethod
    async def notify_vision_update(cls, targets: List[str], risk_level: str):
        """通知前端视觉检测目标变更"""
        await cls.notify({
            "type": "vision_update",
            "alert": "视觉配置更新",
            "description": f"检测目标已更新为: {', '.join(targets)}",
            "is_abnormal": False,
            "targets": targets,
            "risk_level": risk_level
        })

    @classmethod
    async def notify_observation_update(cls, observation_mode: str, description: str):
        """通知前端观察模式更新"""
        await cls.notify({
            "type": "observation",
            "alert": "观察模式更新",
            "description": description,
            "is_abnormal": False,
            "observation_mode": observation_mode
        })

    @classmethod
    async def dismiss_all(cls):
        """清除所有报警"""
        await cls.notify({
            "type": "dismiss_all",
            "alert": "报警已清除",
            "description": "用户已确认所有报警",
            "is_abnormal": False
        })

    @classmethod
    def mute(cls, duration_seconds: int = 300):
        """设置静音期（默认5分钟）"""
        cls._muted_until = time.time() + duration_seconds
        logging.info(f"🔇 [Alert] 报警静音 {duration_seconds} 秒")

    @classmethod
    def unmute(cls):
        """取消静音"""
        cls._muted_until = None
        logging.info(f"🔔 [Alert] 报警静音已取消")

    @classmethod
    def get_recent_alerts(cls, count: int = 20) -> List[Dict]:
        """获取最近的报警记录"""
        return cls._alert_history[-count:]

    @classmethod
    def get_connection_count(cls) -> int:
        """获取当前连接数"""
        return len(cls._connections)

    @classmethod
    def is_muted(cls) -> bool:
        """检查是否处于静音状态"""
        if cls._muted_until is None:
            return False
        return time.time() < cls._muted_until