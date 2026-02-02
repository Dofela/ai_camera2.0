# hand/hand_core.py
"""
Hand 核心模块 - 执行层统一入口

职责：
1. 技能注册与管理
2. 技能执行与调度
3. 执行结果处理
4. 与眼睛模块的交互

架构：
1. Skill Registry（技能注册表）→ 管理所有可用技能
2. Skill Executor（技能执行器）→ 执行具体技能逻辑
3. Result Handler（结果处理器）→ 处理执行结果
4. Alert Dispatcher（警报分发器）→ 处理警报通知
"""
import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict

from eye.eye_core import EyeCore
from hand.registry.skill_registry import SkillRegistry
from hand.executor.skill_executor import SkillExecutor
from hand.result.result_handler import ResultHandler
from hand.alert.alert_dispatcher import AlertDispatcher
from skills.base_skill import BaseSkill


class HandCore:
    """
    手核心类 - 统一管理所有执行组件

    工作流程：
    脑模块请求 → 技能查找 → 参数验证 → 执行技能 → 结果处理 → 返回脑模块
    """

    def __init__(self):
        """创建Hand组件而不依赖"""
        # 不传递eye参数 - 它还未就绪!
        self.eye = None  # 将在initialize()中设置
        
        # 创建执行器
        self.skill_registry = SkillRegistry()
        self.skill_executor = SkillExecutor()
        self.result_handler = ResultHandler()
        self.alert_dispatcher = AlertDispatcher()
        
        # 存储
        self.skills: Dict[str, BaseSkill] = {}
        self.execution_history = []
        
        logging.info("🖐️ [Hand] 创建完成（未初始化）")
    
    async def initialize(self, eye_core: EyeCore):
        """使用Eye引用初始化"""
        self.eye = eye_core
        logging.info("🖐️ [Hand] 初始化完成并引用眼睛")
    
    async def register_skills(self):
        """在所有组件就绪后注册所有技能"""
        # 导入技能
        from skills.vision.visual_perception import VisualPerceptionSkill
        from skills.vision.observation import ObservationSkill
        from skills.security.security_mode import SecurityModeSkill
        from skills.security.dismiss_alerts import DismissAlertsSkill
        from skills.data.log_search import LogSearchSkill
        from skills.data.report import ReportSkill
        from skills.notification.email_notify import EmailNotificationSkill
        from skills.system.health_check import HealthCheckSkill
        from skills.system.vision_control import VisionControlSkill
        
        # 注册基础技能（不依赖硬件）
        self._register_skill(LogSearchSkill())
        self._register_skill(ReportSkill())
        self._register_skill(EmailNotificationSkill())
        self._register_skill(HealthCheckSkill())
        
        # 注册视觉技能（现在Eye已就绪）
        if self.eye:
            self._register_skill(VisualPerceptionSkill(self.eye))
            self._register_skill(ObservationSkill(self.eye))
            self._register_skill(SecurityModeSkill(self.eye))
            self._register_skill(DismissAlertsSkill(self.eye))
            self._register_skill(VisionControlSkill(self.eye))
        
        logging.info(f"🖐️ [Hand] 注册了 {len(self.skills)} 个技能")

    def _init_skills(self):
        """注册所有技能"""
        # 导入技能类
        from skills.vision.visual_perception import VisualPerceptionSkill
        from skills.vision.observation import ObservationSkill
        from skills.security.security_mode import SecurityModeSkill
        from skills.security.dismiss_alerts import DismissAlertsSkill
        from skills.data.log_search import LogSearchSkill
        from skills.data.report import ReportSkill
        from skills.notification.email_notify import EmailNotificationSkill
        from skills.system.health_check import HealthCheckSkill
        from skills.system.vision_control import VisionControlSkill

        # 基础技能（不依赖硬件）
        self._register_skill(LogSearchSkill())
        self._register_skill(ReportSkill())
        self._register_skill(EmailNotificationSkill())
        self._register_skill(HealthCheckSkill())

        # 视觉相关技能（依赖眼睛模块）
        if self.eye:
            self._register_skill(VisualPerceptionSkill(self.eye))
            self._register_skill(ObservationSkill(self.eye))
            self._register_skill(SecurityModeSkill(self.eye))
            self._register_skill(DismissAlertsSkill(self.eye))
            self._register_skill(VisionControlSkill(self.eye))
        else:
            # 如果没有眼睛模块，注册基础版本
            self._register_skill(DismissAlertsSkill())

    def _register_skill(self, skill: BaseSkill):
        """注册单个技能"""
        self.skills[skill.name] = skill
        self.skill_registry.register(skill)
        logging.debug(f"🖐️ [Hand] 注册技能: {skill.name}")

    async def execute_skill(self, skill_name: str, params: dict) -> str:
        """
        执行技能

        Args:
            skill_name: 技能名称
            params: 技能参数

        Returns:
            执行结果字符串
        """
        # 1. 查找技能
        skill = self.skills.get(skill_name)
        if not skill:
            error_msg = f"❌ 未找到技能: {skill_name}"
            logging.error(error_msg)
            return error_msg

        # 2. 参数验证
        try:
            validated_params = self._validate_params(skill, params)
        except Exception as e:
            error_msg = f"❌ 参数验证失败: {str(e)}"
            logging.error(error_msg)
            return error_msg

        # 3. 执行技能
        logging.info(f"🖐️ [Hand] 执行技能: {skill_name}, 参数: {validated_params}")
        try:
            result = await self.skill_executor.execute(skill, validated_params)

            # 4. 处理结果
            processed_result = await self.result_handler.process(result, skill_name, validated_params)

            # 5. 记录执行历史
            self._record_execution(skill_name, validated_params, processed_result)

            return processed_result

        except Exception as e:
            error_msg = f"❌ 技能执行异常: {str(e)}"
            logging.error(error_msg)
            return error_msg

    def _validate_params(self, skill: BaseSkill, params: dict) -> dict:
        """验证技能参数"""
        # 使用Pydantic模型验证
        try:
            param_model = skill.Parameters(**params)
            return param_model.model_dump()
        except Exception as e:
            raise ValueError(f"参数验证失败: {e}")

    def _record_execution(self, skill_name: str, params: dict, result: str):
        """记录执行历史"""
        execution_record = {
            "skill": skill_name,
            "params": params,
            "result": result,
            "timestamp": self._get_timestamp()
        }
        self.execution_history.append(execution_record)

        # 保持历史记录不超过100条
        if len(self.execution_history) > 100:
            self.execution_history.pop(0)

    async def get_available_tools(self) -> List[dict]:
        """获取可用工具列表（用于LLM）"""
        tools = []
        for skill in self.skills.values():
            tools.append(skill.get_schema())
        return tools

    async def get_skill_info(self, skill_name: str) -> Optional[dict]:
        """获取技能详细信息"""
        skill = self.skills.get(skill_name)
        if not skill:
            return None

        return {
            "name": skill.name,
            "description": skill.description,
            "parameters": skill.Parameters.model_json_schema(),
            "has_eye_dependency": hasattr(skill, 'eye') and skill.eye is not None
        }

    async def list_skills(self) -> List[dict]:
        """列出所有可用技能"""
        skills_info = []
        for skill in self.skills.values():
            skills_info.append({
                "name": skill.name,
                "description": skill.description,
                "category": self._get_skill_category(skill.name)
            })
        return skills_info

    def _get_skill_category(self, skill_name: str) -> str:
        """根据技能名称获取类别"""
        if "vision" in skill_name or "observation" in skill_name:
            return "vision"
        elif "security" in skill_name or "alert" in skill_name:
            return "security"
        elif "data" in skill_name or "log" in skill_name or "report" in skill_name:
            return "data"
        elif "email" in skill_name or "notification" in skill_name:
            return "notification"
        elif "system" in skill_name or "health" in skill_name:
            return "system"
        else:
            return "general"

    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()

    # ============================================================
    # 公共接口
    # ============================================================

    async def update_eye_reference(self, eye_core):
        """更新眼睛模块引用"""
        self.eye = eye_core
        # 重新初始化技能（以包含视觉相关技能）
        self._init_skills()
        logging.info("🖐️ [Hand] 眼睛模块引用已更新，重新初始化技能")

    async def get_execution_history(self, limit: int = 10) -> List[dict]:
        """获取执行历史"""
        return self.execution_history[-limit:]

    async def clear_history(self):
        """清空执行历史"""
        self.execution_history.clear()
        logging.info("🖐️ [Hand] 执行历史已清空")
    
    async def shutdown(self):
        """优雅关闭"""
        # 关闭警报分发器
        if hasattr(self.alert_dispatcher, 'close'):
            await self.alert_dispatcher.close()
        
        # 关闭结果处理器
        if hasattr(self.result_handler, 'close'):
            await self.result_handler.close()
        
        logging.info("🖐️ [Hand] 关闭完成")
    
    async def dispatch_alert(self, alert_type: str, message: str, severity: str = "medium"):
        """分发警报"""
        return await self.alert_dispatcher.dispatch(alert_type, message, severity)