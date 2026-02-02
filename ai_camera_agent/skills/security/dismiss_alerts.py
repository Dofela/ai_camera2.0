# skills/security/dismiss_alerts.py
"""
消除警报技能

用于处理误报、确认安全等场景，如'没事了，误报'、'是我自己'等。
"""
from pydantic import Field
from typing import Optional
from skills.base_skill import BaseSkill


class DismissAlertsSkill(BaseSkill):
    name = "dismiss_alerts"
    description = (
        "【消除警报】处理误报或确认安全。用于'没事了'、'误报'、'是我自己'、"
        "'忽略这个警报'等场景。可以消除当前警报或静音特定类型。"
    )

    class Parameters(BaseSkill.Parameters):
        action: str = Field(
            default="dismiss",
            description="操作类型: 'dismiss'(消除当前), 'mute'(静音类型), 'unmute'(取消静音)"
        )
        target_class: Optional[str] = Field(
            default=None,
            description="要静音/取消静音的目标类型，如'cat'、'dog'。仅在mute/unmute时需要"
        )
        reason: Optional[str] = Field(
            default=None,
            description="消除原因，如'是家人'、'是快递员'等"
        )

    def __init__(self, eye_core=None):
        self.eye = eye_core

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)

        if p.action == "dismiss":
            return await self._dismiss_current(p.reason)
        elif p.action == "mute":
            return await self._mute_class(p.target_class)
        elif p.action == "unmute":
            return await self._unmute_class(p.target_class)
        else:
            return f"❌ 未知操作: {p.action}"

    async def _dismiss_current(self, reason: Optional[str]) -> str:
        """消除当前警报"""
        # 这里可以关闭当前事件
        if self.eye and self.eye.perception_memory:
            await self.eye.perception_memory.try_close_event()
        
        reason_text = f"，原因: {reason}" if reason else ""
        return f"✅ 当前警报已消除{reason_text}"

    async def _mute_class(self, target_class: Optional[str]) -> str:
        """静音特定类型"""
        if not target_class:
            return "❌ 请指定要静音的目标类型，如 'cat' 或 'dog'"

        if self.eye:
            self.eye.mute_class(target_class)
            return f"🔇 已静音 '{target_class}' 类型的警报"
        else:
            return "❌ 视觉模块未初始化"

    async def _unmute_class(self, target_class: Optional[str]) -> str:
        """取消静音"""
        if not target_class:
            return "❌ 请指定要取消静音的目标类型"

        if self.eye:
            self.eye.unmute_class(target_class)
            return f"🔊 已取消静音 '{target_class}' 类型"
        else:
            return "❌ 视觉模块未初始化"
