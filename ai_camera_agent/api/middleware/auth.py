# api/middleware/auth.py
"""
认证中间件 - 保护API端点
"""

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import logging
from typing import Optional
from config.settings import ChatLLMConfig

# JWT配置
SECRET_KEY = "ai_camera_agent_secret_key"  # 在生产环境中应从环境变量获取
ALGORITHM = "HS256"

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    验证JWT令牌
    
    Args:
        credentials: HTTP认证凭证
        
    Returns:
        解码后的令牌载荷
        
    Raises:
        HTTPException: 令牌无效或过期
    """
    token = credentials.credentials
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已过期"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌"
        )

def create_access_token(data: dict) -> str:
    """
    创建访问令牌
    
    Args:
        data: 令牌载荷数据
        
    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()
    import datetime
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request) -> Optional[dict]:
    """
    获取当前用户信息
    
    Args:
        request: HTTP请求对象
        
    Returns:
        用户信息字典或None
    """
    # 检查是否有认证头
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    
    try:
        # 解析Bearer令牌
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            return None
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        return None

class AuthMiddleware:
    """
    认证中间件类
    """
    
    def __init__(self, excluded_paths: list = None):
        self.excluded_paths = excluded_paths or []
        logging.info("🔒 认证中间件初始化完成")
    
    async def __call__(self, request: Request, call_next):
        """
        中间件处理函数
        
        Args:
            request: HTTP请求对象
            call_next: 下一个处理函数
            
        Returns:
            HTTP响应
        """
        # 检查是否需要跳过认证
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # 检查认证
        user = await get_current_user(request)
        if not user:
            # 对于某些端点，允许匿名访问但标记用户状态
            request.state.user = None
        else:
            request.state.user = user
        
        response = await call_next(request)
        return response