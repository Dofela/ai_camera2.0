# api/routes/health.py
"""
健康检查端点
"""

from fastapi import APIRouter, Request
from typing import Dict, Any

router = APIRouter()

@router.get("/health")
async def health_check(request: Request) -> Dict[str, Any]:
    """
    全面健康检查
    
    返回系统状态包括所有组件
    """
    agent = request.app.state.agent
    
    try:
        # 从所有模块获取状态
        eye_status = agent.eye.get_status() if agent.eye else None
        brain_initialized = agent.brain is not None
        hand_skills = len(agent.hand.skills) if agent.hand else 0
        
        # 检查数据库
        db_healthy = False
        if agent.eye and agent.eye.perception_memory.db_manager:
            db_healthy = await agent.eye.perception_memory.db_manager.health_check()
        
        all_healthy = (
            agent._running and
            eye_status and
            brain_initialized and
            hand_skills > 0 and
            db_healthy
        )
        
        return {
            "status": "healthy" if all_healthy else "degraded",
            "components": {
                "agent_running": agent._running,
                "eye": eye_status,
                "brain": {"initialized": brain_initialized},
                "hand": {"skills_registered": hand_skills},
                "database": {"healthy": db_healthy}
            },
            "uptime_seconds": 0  # TODO: 跟踪实际运行时间
        }
    
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }

@router.get("/health/ready")
async def readiness_check(request: Request):
    """Kubernetes就绪探针"""
    agent = request.app.state.agent
    
    if not agent._running:
        raise HTTPException(status_code=503, detail="Agent未运行")
    
    return {"ready": True}

@router.get("/health/live")
async def liveness_check():
    """Kubernetes存活探针"""
    return {"alive": True}