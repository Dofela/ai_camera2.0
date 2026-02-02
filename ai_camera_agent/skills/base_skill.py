# skills/base_skill.py
"""
技能基类 - 所有技能必须继承此类

技能是Agent可执行的最小能力单元，如：
- 视觉感知（查看摄像头画面）
- 数据查询（搜索日志）
- 通知发送（发送邮件）
- 系统控制（切换安防模式）
"""
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Dict, Any, Type


class BaseSkill(ABC):
    """
    Agent技能基类
    所有的能力（查库、看图、发邮件）都必须继承此类
    """
    name: str = "base_skill"
    description: str = "技能描述"

    # 定义参数结构（使用Pydantic，方便自动转JSON Schema给大模型看）
    # 子类必须覆盖这个内部类
    class Parameters(BaseModel):
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> str:
        """执行逻辑，必须返回字符串给LLM阅读"""
        pass

    def get_schema(self) -> Dict[str, Any]:
        """获取技能的模式定义（用于LLM工具调用）"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.Parameters.model_json_schema()
            }
        }

    def __str__(self) -> str:
        return f"Skill(name={self.name}, description={self.description})"