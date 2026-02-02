# skills/notification/email_notify.py
"""
邮件通知技能 - 发送邮件报警

基于 old_app/skills/email_notify.py 重构
"""
import logging
from typing import Optional
from pydantic import Field

from skills.base_skill import BaseSkill
from infrastructure.email_client import send_email_alert_sync, EmailClient


class EmailNotificationSkill(BaseSkill):
    """
    邮件通知技能
    
    功能: 发送邮件报警给管理员
    使用场景: 检测到高危异常（如火灾、入侵）或系统严重故障时
    """
    
    name = "send_email_alert"
    description = "发送邮件通知给管理员。当检测到高危异常（如火灾、入侵）或系统严重故障时使用。"
    
    class Parameters(BaseSkill.Parameters):
        subject: str = Field(..., description="邮件标题，例如：'【严重报警】发现火情'")
        content: str = Field(..., description="邮件正文，简述事件经过")
        attachment_path: Optional[str] = Field(None, description="附件路径（可选），支持图片或视频文件")
    
    def __init__(self):
        super().__init__()
        self.email_client = EmailClient()
        logging.info(f"📧 [Skill] {self.name} 技能初始化完成")
    
    async def execute(self, params: dict) -> str:
        """
        执行邮件发送
        
        Args:
            params: 参数字典，包含 subject, content, attachment_path
            
        Returns:
            执行结果描述
        """
        # 验证参数
        try:
            p = self.Parameters(**params)
        except Exception as e:
            return f"❌ 参数验证失败: {e}"
        
        logging.info(f"📧 [Skill] 正在尝试发送邮件: {p.subject}")
        
        # 发送邮件
        success = send_email_alert_sync(p.subject, p.content, p.attachment_path)
        
        if success:
            result = f"✅ 邮件已发送给管理员。\n标题: {p.subject}"
            if p.attachment_path:
                result += f"\n附件: {p.attachment_path}"
            return result
        else:
            return "❌ 邮件发送失败，请检查 SMTP 配置或网络。"
    
    async def send_visual_alert(
        self, 
        description: str, 
        detected_objects: list,
        risk_level: str = "high",
        attachment_path: str = None
    ) -> bool:
        """
        发送视觉报警邮件（便捷方法）
        
        Args:
            description: 报警描述
            detected_objects: 检测到的对象列表
            risk_level: 风险级别
            attachment_path: 附件路径
            
        Returns:
            是否发送成功
        """
        subject = f"🚨 [视觉报警] {description[:30]}..."
        
        content = f"""
视觉传感器检测到高危目标！

报警描述: {description}
检测目标: {', '.join(detected_objects)}
风险级别: {risk_level}
时间: {self._get_current_time()}

请立即查看监控画面。
"""
        
        return await self.email_client.send_alert(
            "visual", description, 
            {"detected_objects": detected_objects, "risk_level": risk_level},
            attachment_path
        )
    
    async def send_behavior_alert(
        self,
        description: str,
        analysis_result: dict,
        attachment_path: str = None
    ) -> bool:
        """
        发送行为报警邮件（便捷方法）
        
        Args:
            description: 报警描述
            analysis_result: VLM分析结果
            attachment_path: 附件路径
            
        Returns:
            是否发送成功
        """
        subject = f"⚠️ [行为报警] {description[:30]}..."
        
        content = f"""
智能分析检测到异常行为！

报警描述: {description}
分析结果: {analysis_result.get('reason', '未知')}
异常判断: {'是' if analysis_result.get('is_abnormal', False) else '否'}
时间: {self._get_current_time()}

请查看详细分析报告。
"""
        
        return await self.email_client.send_alert(
            "behavior", description,
            analysis_result,
            attachment_path
        )
    
    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')