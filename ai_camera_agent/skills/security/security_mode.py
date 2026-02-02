# skills/security/security_mode.py
"""
安防模式切换技能

用于切换系统的安防级别，如'我出门了'、'切换到高警戒模式'等。
"""
from pydantic import Field
from skills.base_skill import BaseSkill


class SecurityModeSkill(BaseSkill):
    name = "security_mode"
    description = (
        "【安防模式】切换系统安防级别。用于'我出门了'、'我回来了'、'切换到高警戒'等场景。"
        "支持的模式: normal(标准), high(高警戒), away(外出), night(夜间)"
    )

    class Parameters(BaseSkill.Parameters):
        mode: str = Field(
            ...,
            description="安防模式: 'normal'(标准), 'high'(高警戒), 'away'(外出), 'night'(夜间)"
        )

    def __init__(self, eye_core=None):
        self.eye = eye_core
        self._current_mode = "normal"

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)
        
        valid_modes = ["normal", "high", "away", "night"]
        if p.mode not in valid_modes:
            return f"❌ 无效模式: {p.mode}，支持的模式: {', '.join(valid_modes)}"

        old_mode = self._current_mode
        self._current_mode = p.mode

        # 更新Eye模块的安防策略
        if self.eye:
            policy_map = {
                "normal": ("标准模式", "normal"),
                "high": ("高警戒模式", "high"),
                "away": ("外出模式", "high"),
                "night": ("夜间模式", "normal")
            }
            policy_name, risk_level = policy_map[p.mode]
            self.eye.update_security_policy(policy_name, risk_level)

        mode_descriptions = {
            "normal": "标准监控，检测人员",
            "high": "高警戒，对所有目标敏感",
            "away": "外出模式，任何移动都会报警",
            "night": "夜间模式，降低误报"
        }

        return (
            f"🔒 安防模式已切换\n"
            f"📍 {old_mode} → {p.mode}\n"
            f"📝 {mode_descriptions[p.mode]}"
        )
