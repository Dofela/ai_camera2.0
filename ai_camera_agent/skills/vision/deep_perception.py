# skills/vision/deep_perception.py
"""
深度感知技能 - 執行三層識別系統
"""
from pydantic import Field
from skills.base_skill import BaseSkill
import json


class DeepPerceptionSkill(BaseSkill):
    name = "deep_perception"
    description = (
        "【深度感知】執行三層識別系統（YOLO+全景LLM+精確LLM）。"
        "用於用戶詢問「詳細分析畫面」、「那個人在幹嘛」、「仔細檢查」等需要深層理解的場景。"
        "比普通視覺感知更慢但更詳細。"
    )

    class Parameters(BaseSkill.Parameters):
        focus_target: str = Field(
            default="all",
            description="特別關注的目標，如 'person'。如果指定，會在報告中強調。"
        )

    def __init__(self, eye_core):
        self.eye = eye_core

    async def execute(self, params: dict) -> str:
        if not self.eye:
            return "❌ 視覺模塊未初始化"

        # 執行三層感知
        result = await self.eye.perceive_three_tier()

        if "error" in result:
            return f"❌ 分析失敗: {result['error']}"

        # 格式化輸出給用戶/LLM看
        pano = result.get("panoramic", {})
        details = result.get("detailed", [])

        # 構建報告
        report = [
            "🧠 **三層感知分析報告**",
            f"👁️ **實時檢測**: {json.dumps(result.get('yolo_summary', {}), ensure_ascii=False)}",
            "",
            "🌍 **全景分析**:",
            f"- 場景: {pano.get('description', '無')}",
            f"- 判斷: {pano.get('reason', '無')}",
            f"- 異常: {'是' if pano.get('is_abnormal') else '否'}",
            "",
            f"🔍 **精確目標分析** ({len(details)}個目標):"
        ]

        for i, detail in enumerate(details):
            analysis = detail['analysis']
            # 這裡兼容不同的返回結構
            desc = analysis.get('description') or analysis.get('behavior_description') or str(analysis)
            risk = analysis.get('risk_level', 0)

            icon = "⚠️" if risk > 0 or analysis.get('is_abnormal') else "✅"

            report.append(f"{i + 1}. {icon} **{detail['target']}**: {desc}")
            if 'appearance_features' in analysis:
                report.append(f"   - 特徵: {analysis['appearance_features']}")

        return "\n".join(report)