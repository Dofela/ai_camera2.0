# api/routes/chat.py
"""
聊天路由 - 处理用户对话请求

基于 old_app/api/endpoints.py 和 old_app/services/chat_service_v2.py 重构
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agent.agent_core import AICameraAgent
from api.dependencies import get_agent
from api.middleware.auth import verify_token

router = APIRouter()


class ChatQuery(BaseModel):
    """聊天请求模型"""
    question: str
    session_id: str = None  # 可选会话ID，用于多轮对话


class ChatResponse(BaseModel):
    """聊天响应模型"""
    answer: str
    session_id: str = None
    skill_used: str = None  # 使用的技能名称


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(
    query: ChatQuery,
    agent: AICameraAgent = Depends(get_agent)
) -> ChatResponse:
    """
    对话接口 - 使用 AICameraAgent 处理用户问题
    
    Args:
        query: 聊天请求
        agent: AICameraAgent 实例
        
    Returns:
        聊天响应
    """
    try:
        logging.info(f"💬 [Chat] 收到问题: {query.question[:50]}...")
        
        # 处理用户问题
        answer = await agent.process(query.question)
        
        # 获取使用的技能信息
        skill_used = getattr(agent, 'last_used_skill', None)
        
        return ChatResponse(
            answer=answer,
            session_id=query.session_id,
            skill_used=skill_used
        )
        
    except Exception as e:
        logging.error(f"❌ [Chat] 处理失败: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"系统错误: {str(e)}"
        )


@router.post("/chat/stream")
async def chat_stream(
    query: ChatQuery,
    agent: AICameraAgent = Depends(get_agent)
):
    """
    流式对话接口（SSE）
    
    返回 Server-Sent Events 流
    """
    from fastapi.responses import StreamingResponse
    import asyncio
    
    async def event_generator():
        """生成 SSE 事件"""
        try:
            # 开始处理
            yield f"data: {{\"event\": \"start\", \"message\": \"开始处理问题...\"}}\n\n"
            
            # 模拟流式响应（实际应集成到 AICameraAgent 的流式处理）
            # 这里先返回完整响应，后续可优化为真正的流式
            answer = await agent.process(query.question)
            
            # 分块发送
            chunk_size = 50
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i+chunk_size]
                yield f"data: {{\"event\": \"chunk\", \"chunk\": \"{chunk}\"}}\n\n"
                await asyncio.sleep(0.05)  # 模拟流式延迟
            
            # 结束
            yield f"data: {{\"event\": \"end\", \"message\": \"处理完成\"}}\n\n"
            
        except Exception as e:
            yield f"data: {{\"event\": \"error\", \"message\": \"处理失败: {str(e)}\"}}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/chat/skills")
async def list_skills(agent: AICameraAgent = Depends(get_agent)):
    """
    列出所有可用技能
    
    Returns:
        技能列表
    """
    try:
        skills = agent.get_available_skills()
        return {
            "skills": [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.get_parameters_schema()
                }
                for skill in skills.values()
            ]
        }
    except Exception as e:
        logging.error(f"❌ [Chat] 获取技能列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/autonomous")
async def trigger_autonomous_check(agent: AICameraAgent = Depends(get_agent)):
    """
    触发自主巡检
    
    模拟 old_app/services/chat_service_v2.py 中的 autonomous_tick 功能
    """
    try:
        # 查找系统健康检查技能
        skill = agent.skills.get("system_health_check")
        if skill:
            result = await skill.execute({})
            
            # 检查结果
            if "异常" in result or "错误" in result:
                logging.warning(f"🤖 [Autonomous] 巡检发现问题: {result}")
                return {
                    "status": "warning",
                    "message": "巡检发现问题",
                    "details": result
                }
            else:
                return {
                    "status": "ok",
                    "message": "巡检正常",
                    "details": result
                }
        else:
            return {
                "status": "info",
                "message": "系统健康检查技能未找到",
                "details": None
            }
            
    except Exception as e:
        logging.error(f"❌ [Autonomous] 巡检失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))