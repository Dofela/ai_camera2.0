# skills/vision/visual_perception.py
"""
视觉感知技能 - 查看摄像头画面

用于'看看现在有什么'、'画面里是谁'、'那个人在干嘛'等任何需要看一眼的问题。
这是最常用的视觉技能，优先使用此技能而非持续观察。
"""
from pydantic import Field
from skills.base_skill import BaseSkill


class VisualPerceptionSkill(BaseSkill):
    name = "visual_perception"
    description = (
        "【一次性查看】调用摄像头查看当前画面。用于'看看现在有什么'、'画面里是谁'、'那个人在干嘛'等任何需要看一眼的问题。"
        "这是最常用的视觉技能，优先使用此技能而非持续观察。"
    )

    class Parameters(BaseSkill.Parameters):
        instruction: str = Field(..., description="具体的观察指令。如：'判断当前场景类型'、'检查门口是否有快递'。")

    def __init__(self, eye_core):
        self.eye = eye_core

    async def execute(self, params: dict) -> str:
        p = self.Parameters(**params)

        # 检查眼睛模块是否可用
        if not self.eye:
            return "❌ 视觉模块未初始化，无法观察。"

        # 获取当前帧
        try:
            # 获取最新帧
            latest_frame = self.eye.get_latest_frame()
            if latest_frame is None:
                return "❌ 摄像头暂无信号，无法观察。"
            
            # 调用眼睛模块的感知功能
            perception_result = await self.eye.perceive_single(latest_frame)
            
            if not perception_result:
                return "❌ 视觉感知失败。"

            # 如果有检测结果，构建描述
            if perception_result.detection_result and perception_result.detection_result.detections:
                detections = perception_result.detection_result.detections
                detection_summary = []
                for det in detections:
                    detection_summary.append(f"{det.class_name} (置信度: {det.confidence:.2f})")
                
                base_info = f"👁️ 检测到 {len(detections)} 个目标: {', '.join(detection_summary)}"
            else:
                base_info = "👁️ 当前画面未检测到目标"

            # 如果有VLM分析结果，添加
            if perception_result.analysis_result and perception_result.analysis_result.description:
                vlm_analysis = perception_result.analysis_result.description
                return f"{base_info}\n🧠 VLM分析: {vlm_analysis}"
            else:
                # 如果没有VLM分析，根据用户指令返回基础信息
                return f"{base_info}\n📝 用户指令: {p.instruction}"

        except Exception as e:
            return f"❌ 视觉感知失败: {str(e)}"