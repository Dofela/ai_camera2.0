# skills/system/vision_control.py
"""
视觉控制技能

用于调整视觉检测参数，如'只检测人和车'、'提高检测灵敏度'等。
"""
from pydantic import Field
from typing import List, Optional
from skills.base_skill import BaseSkill


class VisionControlSkill(BaseSkill):
    name = "vision_control"
    description = (
        "【视觉控制】调整视觉检测参数。用于'只检测人和车'、'添加检测狗'、"
        "'提高灵敏度'等需要调整检测设置的场景。"
    )

    class Parameters(BaseSkill.Parameters):
        action: str = Field(
            ...,
            description="操作类型: 'set_targets'(设置检测目标), 'add_target'(添加目标), 'get_status'(获取状态)"
        )
        targets: Optional[List[str]] = Field(
            default=None,
            description="检测目标列表，如 ['person', 'car']。用于set_targets"
        )
        target: Optional[str] = Field(
            default=None,
            description="单个目标，如 'dog'。用于add_target"
        )

    def __init__(self, eye_core=None):
        self.eye = eye_core

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)

        if p.action == "set_targets":
            return await self._set_targets(p.targets)
        elif p.action == "add_target":
            return await self._add_target(p.target)
        elif p.action == "get_status":
            return self._get_status()
        else:
            return f"❌ 未知操作: {p.action}"

    async def _set_targets(self, targets: Optional[List[str]]) -> str:
        """设置检测目标"""
        if not targets:
            return "❌ 请指定检测目标列表"

        if not self.eye:
            return "❌ 视觉模块未初始化"

        success = self.eye.update_targets(targets)
        if success:
            return f"✅ 检测目标已更新为: {', '.join(targets)}"
        else:
            return "❌ 更新检测目标失败"

    async def _add_target(self, target: Optional[str]) -> str:
        """添加单个检测目标"""
        if not target:
            return "❌ 请指定要添加的目标"

        if not self.eye:
            return "❌ 视觉模块未初始化"

        current_targets = self.eye.target_objects.copy()
        if target not in current_targets:
            current_targets.append(target)
            self.eye.update_targets(current_targets)
            return f"✅ 已添加检测目标: {target}"
        else:
            return f"ℹ️ 目标 '{target}' 已在检测列表中"

    def _get_status(self) -> str:
        """获取视觉状态"""
        if not self.eye:
            return "❌ 视觉模块未初始化"

        status = self.eye.get_status()
        return (
            f"👁️ 视觉模块状态\n"
            f"📍 运行中: {status.get('running', False)}\n"
            f"🎯 检测目标: {', '.join(status.get('targets', []))}\n"
            f"🔒 安防策略: {status.get('policy', 'unknown')}\n"
            f"🔇 静音类别: {', '.join(status.get('muted_classes', [])) or '无'}"
        )
