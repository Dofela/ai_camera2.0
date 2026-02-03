from typing import TYPE_CHECKING
from fastapi import Request

# 使用 TYPE_CHECKING 避免运行时循环导入
if TYPE_CHECKING:
    from agent.agent_core import AICameraAgent

def get_agent(request: Request) -> "AICameraAgent":
    """
    FastAPI 依赖注入函数：获取 Agent 实例
    """
    return request.app.state.agent