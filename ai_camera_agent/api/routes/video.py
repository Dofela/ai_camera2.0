# api/routes/video.py
"""
视频路由 - 处理视频相关请求
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from agent.agent_core import AICameraAgent
from api.dependencies import get_agent
from api.middleware.auth import verify_token

router = APIRouter()

class VideoStatusResponse(BaseModel):
    """视频状态响应模型"""
    is_recording: bool
    recording_path: Optional[str]
    fps: int
    resolution: str
    last_frame_time: Optional[str]

class EventListResponse(BaseModel):
    """事件列表响应模型"""
    events: List[dict]
    total: int
    page: int
    limit: int

@router.get("/video/status", response_model=VideoStatusResponse, dependencies=[Depends(verify_token)])
async def get_video_status(agent: AICameraAgent = Depends(get_agent)):
    """
    获取视频状态
    
    Returns:
        视频状态信息
    """
    try:
        if not agent.eye:
            raise HTTPException(status_code=503, detail="视觉模块未初始化")
        
        status = agent.eye.get_status()
        return VideoStatusResponse(
            is_recording=status.get("is_recording", False),
            recording_path=status.get("recording_path"),
            fps=status.get("fps", 0),
            resolution=status.get("resolution", "unknown"),
            last_frame_time=status.get("last_frame_time")
        )
    except Exception as e:
        logging.error(f"获取视频状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/video/events", response_model=EventListResponse, dependencies=[Depends(verify_token)])
async def list_events(
    page: int = 1,
    limit: int = 20,
    agent: AICameraAgent = Depends(get_agent)
):
    """
    列出安全事件
    
    Args:
        page: 页码
        limit: 每页数量
        
    Returns:
        事件列表
    """
    try:
        if not agent.eye or not agent.eye.perception_memory:
            raise HTTPException(status_code=503, detail="视觉模块未初始化")
        
        # 获取事件历史
        events = agent.eye.perception_memory.get_event_history(limit)
        total = len(events)
        
        return EventListResponse(
            events=events,
            total=total,
            page=page,
            limit=limit
        )
    except Exception as e:
        logging.error(f"获取事件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/video/snapshot", dependencies=[Depends(verify_token)])
async def get_snapshot(agent: AICameraAgent = Depends(get_agent)):
    """
    获取当前快照
    
    Returns:
        JPEG格式的当前帧
    """
    try:
        if not agent.eye:
            raise HTTPException(status_code=503, detail="视觉模块未初始化")
        
        frame = agent.eye.get_latest_frame()
        if frame is None:
            raise HTTPException(status_code=404, detail="当前无视频帧")
        
        # 编码为JPEG
        import cv2
        import numpy as np
        from fastapi.responses import Response
        
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return Response(
            content=buffer.tobytes(),
            media_type="image/jpeg"
        )
    except Exception as e:
        logging.error(f"获取快照失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))