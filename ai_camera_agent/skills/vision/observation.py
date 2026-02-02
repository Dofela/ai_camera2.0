# skills/vision/observation.py
"""
持续观察技能 - 开启/关闭持续观察模式

用于'帮我盯着门口'、'观察这个区域'、'持续监控'等需要长时间观察的场景。
与visual_perception不同，这是持续性的观察任务。
"""
from pydantic import Field
from typing import Optional
from skills.base_skill import BaseSkill


class ObservationSkill(BaseSkill):
    name = "observation"
    description = (
        "【持续观察】开启或关闭持续观察模式。用于'帮我盯着门口'、'观察这个区域'、"
        "'停止观察'等需要长时间监控的场景。与一次性查看不同，这是持续性的观察任务。"
    )

    class Parameters(BaseSkill.Parameters):
        action: str = Field(
            ..., 
            description="操作类型: 'start' 开始观察, 'stop' 停止观察, 'status' 查看状态"
        )
        target: Optional[str] = Field(
            default=None, 
            description="观察目标，如 'person'、'car'、'door' 等。仅在 action='start' 时需要"
        )
        duration: Optional[int] = Field(
            default=300, 
            description="观察持续时间（秒），默认5分钟。仅在 action='start' 时有效"
        )

    def __init__(self, eye_core=None):
        self.eye = eye_core
        self._observation_active = False
        self._observation_target = None

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)

        if p.action == "start":
            return await self._start_observation(p.target, p.duration)
        elif p.action == "stop":
            return await self._stop_observation()
        elif p.action == "status":
            return self._get_status()
        else:
            return f"❌ 未知操作: {p.action}，支持的操作: start, stop, status"

    async def _start_observation(self, target: Optional[str], duration: int) -> str:
        """开始持续观察"""
        if not self.eye:
            return "❌ 视觉模块未初始化，无法开始观察。"

        if self._observation_active:
            return f"⚠️ 观察已在进行中，目标: {self._observation_target}。如需更改请先停止当前观察。"

        # 设置观察目标
        self._observation_active = True
        self._observation_target = target or "all"

        # 如果指定了目标，更新Eye模块的检测目标
        if target:
            self.eye.update_targets([target])

        return (
            f"👁️ 开始持续观察\n"
            f"📍 目标: {self._observation_target}\n"
            f"⏱️ 持续时间: {duration}秒\n"
            f"💡 提示: 发送'停止观察'可以结束"
        )

    async def _stop_observation(self) -> str:
        """停止持续观察"""
        if not self._observation_active:
            return "ℹ️ 当前没有正在进行的观察任务。"

        self._observation_active = False
        old_target = self._observation_target
        self._observation_target = None

        # 恢复默认检测目标
        if self.eye:
            self.eye.update_targets(["person"])  # 恢复默认

        return f"✅ 已停止观察，之前的目标: {old_target}"

    def _get_status(self) -> str:
        """获取观察状态"""
        if self._observation_active:
            return (
                f"👁️ 观察状态: 进行中\n"
                f"📍 目标: {self._observation_target}\n"
                f"🎥 视觉模块: {'已连接' if self.eye else '未连接'}"
            )
        else:
            return "💤 观察状态: 未启动"
