# api/websockets/alerts.py
"""
报警 WebSocket 路由 - 实时推送报警信息
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hand.alert.alert_dispatcher import AlertDispatcher

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket):
    """
    报警 WebSocket 端点
    
    客户端连接后，将实时接收所有报警信息。
    支持的消息类型：
    - 无输入消息，仅接收广播
    """
    await AlertDispatcher.register(websocket)
    
    try:
        # 保持连接，等待客户端断开
        while True:
            # 接收任何消息（可选）
            data = await websocket.receive_text()
            # 目前不需要处理客户端消息
            logging.debug(f"📨 [Alert WS] 收到客户端消息: {data[:50]}")
    except WebSocketDisconnect:
        logging.info("🔔 [Alert] 客户端主动断开连接")
    except Exception as e:
        logging.error(f"❌ [Alert WS] 连接异常: {e}")
    finally:
        await AlertDispatcher.unregister(websocket)


@router.get("/alerts/recent")
async def get_recent_alerts(count: int = 20):
    """
    获取最近的报警记录
    
    Args:
        count: 返回的记录数量，默认20条
        
    Returns:
        报警历史列表
    """
    return AlertDispatcher.get_recent_alerts(count)


@router.post("/alerts/mute")
async def mute_alerts(duration_seconds: int = 300):
    """
    静音报警（默认5分钟）
    
    Args:
        duration_seconds: 静音时长（秒）
    """
    AlertDispatcher.mute(duration_seconds)
    return {"message": f"报警已静音 {duration_seconds} 秒"}


@router.post("/alerts/unmute")
async def unmute_alerts():
    """取消静音"""
    AlertDispatcher.unmute()
    return {"message": "报警静音已取消"}


@router.post("/alerts/dismiss")
async def dismiss_all_alerts():
    """清除所有报警"""
    await AlertDispatcher.dismiss_all()
    return {"message": "所有报警已清除"}