# api/app.py
"""
FastAPI应用设置
"""

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import chat, video, health
from api.websockets import video_feed, alerts
from api.middleware.auth import AuthMiddleware
from config.settings import ServerConfig

def create_app(agent_instance) -> FastAPI:
    """
    创建和配置FastAPI应用
    
    Args:
        agent_instance: AICameraAgent实例用于依赖注入
    
    Returns:
        配置好的FastAPI应用
    """
    app = FastAPI(
        title="AI Camera Agent",
        description="智能安防摄像头监控系统",
        version="1.0.0"
    )
    
    # CORS中间件（生产环境中应适当配置）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: 生产环境中限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 认证中间件
    app.add_middleware(AuthMiddleware, excluded_paths=["/", "/api/v1/health", "/docs", "/redoc"])
    
    # 注入agent实例以供路由访问
    app.state.agent = agent_instance
    
    # 挂载HTTP路由
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(video.router, prefix="/api/v1", tags=["video"])
    
    # 挂载WebSocket端点
    app.include_router(video_feed.router, tags=["websocket"])
    app.include_router(alerts.router, tags=["websocket"])
    
    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"error": "内部服务器错误", "detail": str(exc)}
        )
    
    # 根端点
    @app.get("/")
    async def root():
        return {
            "service": "AI Camera Agent",
            "version": "1.0.0",
            "status": "running"
        }
    
    # 认证端点
    @app.post("/api/v1/auth/login")
    async def login(username: str, password: str):
        """
        用户登录获取访问令牌
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            访问令牌
        """
        # 在生产环境中应验证用户名和密码
        # 这里简化处理
        if username == "admin" and password == "password":  # TODO: 替换为实际验证
            from api.middleware.auth import create_access_token
            access_token = create_access_token(data={"sub": username, "role": "admin"})
            return {"access_token": access_token, "token_type": "bearer"}
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误"
            )
    
    return app