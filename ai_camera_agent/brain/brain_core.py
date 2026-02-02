# brain/brain_core.py
"""
Brain 核心模块 - 认知层统一入口

职责：
1. 理解用户意图（自然语言 → 结构化意图）
2. 任务规划（分解复杂任务为原子操作）
3. 协调眼睛和手的协作
4. 维护对话上下文和系统状态

架构：
1. Intent Router（快速路由）→ 处理80%的明确意图
2. LLM Reasoning（深度思考）→ 处理20%的复杂/模糊情况
3. Task Planner（任务规划）→ 分解复杂任务
4. Context Manager（上下文管理）→ 维护对话历史
"""
import json
import logging
import httpx
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from collections import deque

from eye.eye_core import EyeCore
from hand.hand_core import HandCore
from brain.intent.intent_router import IntentRouter, IntentCategory, IntentResult
from brain.llm.llm_connector import LLMConnector
from brain.memory.short_term import ShortTermMemory
from brain.context.context_manager import ContextManager
from brain.planner.task_planner import TaskPlanner
from config.settings import ChatLLMConfig


@dataclass
class BrainThought:
    """Brain的思考过程（用于调试和可解释性）"""
    step: int
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict] = None
    observation: Optional[str] = None


class BrainCore:
    """
    大脑核心类 - 统一管理所有认知组件

    工作流程：
    用户输入 → 意图识别 → 任务规划 → 技能调度 → 执行反馈
    """

    def __init__(self):
        """创建Brain组件而不依赖"""
        # 不接受参数 - 依赖关系在initialize()中设置
        self.eye = None
        self.hand = None
        
        # 创建认知组件
        self.intent_router = IntentRouter()
        self.llm_connector = LLMConnector()
        self.short_term_memory = ShortTermMemory()
        self.context_manager = ContextManager()
        self.task_planner = TaskPlanner()
        
        # 存储
        self.skills: Dict[str, object] = {}
        self.history = deque(maxlen=10)
        self.thought_chain: List[BrainThought] = []
        
        # HTTP客户端（将在initialize中配置）
        self.client = None
        
        logging.info("🧠 [Brain] 创建完成（未初始化）")
    
    async def initialize(self, eye_core: EyeCore, hand_core: HandCore):
        """使用Eye和Hand引用初始化"""
        self.eye = eye_core
        self.hand = hand_core
        
        # 创建带适当配置的HTTP客户端
        self.client = httpx.AsyncClient(
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {ChatLLMConfig.API_KEY}"
            },
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=30.0
            )
        )
        
        logging.info("🧠 [Brain] 初始化完成并引用眼睛和手")
    
    async def shutdown(self):
        """优雅关闭"""
        if self.client:
            await self.client.aclose()
            self.client = None
        
        logging.info("🧠 [Brain] 关闭完成")

    def _init_skills(self):
        """通过手模块注册所有技能"""
        # 注意：实际技能注册通过hand.skill_registry完成
        # 这里只维护技能名称到hand的映射
        pass

    async def process(self, user_input: str) -> str:
        """
        核心处理流程

        Step 1: 快速路由（规则引擎）
        Step 2: 如果路由置信度高，直接执行
        Step 3: 否则，交给LLM深度思考
        Step 4: 任务规划（复杂任务分解）
        """
        self.thought_chain = []

        # === Step 1: 意图识别 ===
        intent = self.intent_router.route(user_input)
        self._log_thought(1, f"意图识别: {intent.category.value} (置信度: {intent.confidence})")

        # 更新上下文
        self.context_manager.update_context(user_input, intent)

        # === Step 2: 高置信度 → 直接执行 ===
        if intent.confidence >= 0.7 and intent.suggested_skill:
            self._log_thought(2, f"快速路由: 调用 {intent.suggested_skill}",
                           action=intent.suggested_skill,
                           action_input=intent.extracted_params)

            # 通过手模块执行技能
            result = await self._execute_skill(
                intent.suggested_skill,
                intent.extracted_params or {}
            )

            # 生成自然语言回复
            response = await self._generate_response(user_input, intent, result)
            return response

        # === Step 3: 低置信度 → LLM决策 ===
        if intent.category == IntentCategory.CHITCHAT and intent.confidence >= 0.7:
            # 纯闲聊，不需要工具
            return await self._llm_chat(user_input)

        # === Step 4: 复杂情况 → LLM + 工具 ===
        return await self._llm_with_tools(user_input, intent)

    async def _execute_skill(self, skill_name: str, params: dict) -> str:
        """通过手模块执行技能"""
        if not self.hand:
            return "❌ 手模块未初始化，无法执行技能"

        try:
            # 通过手模块的技能执行器调用技能
            result = await self.hand.execute_skill(skill_name, params)
            self._log_thought(3, f"技能执行完成", observation=result)
            return result
        except Exception as e:
            error_msg = f"❌ 技能执行失败: {str(e)}"
            self._log_thought(3, error_msg, observation=error_msg)
            return error_msg

    async def _generate_response(self, user_input: str, intent: IntentResult, skill_result: str) -> str:
        """根据技能结果生成自然语言回复"""
        # 简单场景：直接返回技能结果
        if "✅" in skill_result or "👁️" in skill_result or "🧠" in skill_result:
            return skill_result

        # 复杂场景：让LLM润色
        prompt = f"""用户说: {user_input}
系统执行了 {intent.suggested_skill}，结果是:
{skill_result}

请用简洁友好的语言回复用户（不超过2句话）。"""

        return await self._llm_chat(prompt, is_internal=True)

    async def _llm_chat(self, message: str, is_internal: bool = False) -> str:
        """纯对话（不带工具）"""
        messages = [
            {"role": "system", "content": "你是智能安防助手，回复简洁专业，不超过3句话。"},
            {"role": "user", "content": message}
        ]

        try:
            resp = await self.client.post(
                ChatLLMConfig.API_URL,
                json={
                    "model": ChatLLMConfig.MODEL,
                    "messages": messages,
                    "stream": False,
                    "max_tokens": 200  # 限制回复长度
                }
            )

            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content']
            else:
                return "系统繁忙，请稍后再试。"
        except Exception as e:
            logging.error(f"LLM调用失败: {e}")
            return "网络异常，请稍后再试。"

    async def _llm_with_tools(self, user_input: str, intent: IntentResult) -> str:
        """带工具的LLM调用（复杂场景）"""
        # 构建精简的System Prompt
        system_prompt = self._build_minimal_prompt(intent)

        # 获取可用工具（通过手模块）
        available_tools = await self._get_available_tools()

        messages = [
            {"role": "system", "content": system_prompt},
            *list(self.history),
            {"role": "user", "content": user_input}
        ]

        try:
            resp = await self.client.post(
                ChatLLMConfig.API_URL,
                json={
                    "model": ChatLLMConfig.MODEL,
                    "messages": messages,
                    "tools": available_tools,
                    "stream": False
                }
            )

            if resp.status_code != 200:
                return "系统繁忙，请稍后再试。"

            response_msg = resp.json()['choices'][0]['message']
            tool_calls = response_msg.get("tool_calls")

            if tool_calls:
                # 执行工具
                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    func_args = json.loads(tc["function"]["arguments"])
                    result = await self._execute_skill(func_name, func_args)

                # 记录并返回
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": result})
                return result
            else:
                answer = response_msg.get("content", "")
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": answer})
                return answer

        except Exception as e:
            logging.error(f"LLM with tools失败: {e}")
            return "处理请求时出错，请重试。"

    def _build_minimal_prompt(self, intent: IntentResult) -> str:
        """构建最小化的System Prompt"""
        base = "你是安防助手。"

        # 根据意图添加针对性指令
        if intent.category == IntentCategory.VISION_ONCE:
            base += " 用户想查看当前画面，请调用视觉感知技能。"
        elif intent.category == IntentCategory.VISION_TRACK:
            base += " 用户想持续追踪目标，请调用观察模式技能。"
        elif intent.category == IntentCategory.VISION_CONFIG:
            base += " 用户想修改检测目标，请调用视觉配置技能。"
        elif intent.category == IntentCategory.SECURITY_MODE:
            base += " 用户想切换安防模式，请调用安防模式技能。"
        elif intent.category == IntentCategory.ALERT_CONTROL:
            base += " 用户想控制警报，请调用警报控制技能。"

        base += " 如果用户意图不明确，请先询问澄清。"

        return base

    async def _get_available_tools(self) -> list:
        """获取可用工具列表（通过手模块）"""
        if not self.hand:
            return []

        try:
            return await self.hand.get_available_tools()
        except:
            return []

    def _log_thought(self, step: int, thought: str, action: str = None, action_input: dict = None, observation: str = None):
        """记录思考过程"""
        thought_obj = BrainThought(
            step=step,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation
        )
        self.thought_chain.append(thought_obj)
        logging.debug(f"🧠 [思考步骤{step}] {thought}")

    # ============================================================
    # 公共接口
    # ============================================================

    async def get_thought_chain(self) -> List[BrainThought]:
        """获取思考链（用于调试）"""
        return self.thought_chain

    async def clear_history(self):
        """清空对话历史"""
        self.history.clear()
        self.context_manager.clear()
        logging.info("🧠 [Brain] 对话历史已清空")

    async def update_eye_reference(self, eye_core):
        """更新眼睛模块引用"""
        self.eye = eye_core
        logging.info("🧠 [Brain] 眼睛模块引用已更新")

    async def update_hand_reference(self, hand_core):
        """更新手模块引用"""
        self.hand = hand_core
        logging.info("🧠 [Brain] 手模块引用已更新")