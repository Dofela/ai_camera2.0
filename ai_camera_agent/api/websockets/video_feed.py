# api/websockets/video_feed.py
"""
视频流WebSocket端点
"""

from fastapi import WebSocket, WebSocketDisconnect, APIRouter
from typing import Set
import asyncio
import cv2
import numpy as np
import logging

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
    
    async def broadcast_frame(self, frame: np.ndarray):
        """向所有连接的客户端广播帧"""
        if not self.active_connections:
            return
            
        try:
            # 将帧编码为JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_bytes = buffer.tobytes()
            
            # 发送到所有连接
            dead_connections = set()
            for connection in self.active_connections:
                try:
                    await connection.send_bytes(frame_bytes)
                except:
                    dead_connections.add(connection)
            
            # 清理死连接
            self.active_connections -= dead_connections
            
        except Exception as e:
            logging.error(f"❌ 广播帧失败: {e}")

# 全局连接管理器
manager = ConnectionManager()

@router.websocket("/ws/video")
async def video_feed(websocket: WebSocket):
    """视频流WebSocket端点"""
    await manager.connect(websocket)
    
    try:
        # 保持连接活跃
        while True:
            # 回显任何消息以保持连接
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logging.info("🔌 视频流客户端断开连接")