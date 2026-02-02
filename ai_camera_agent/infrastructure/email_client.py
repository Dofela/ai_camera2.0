# infrastructure/email_client.py
"""
邮件客户端 - 发送报警邮件

基于 old_app/infrastructure/email_client.py 重构
"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication

from config.settings import EmailConfig


def send_email_alert_sync(subject: str, content: str, attachment_path: str = None) -> bool:
    """
    同步发送邮件报警
    
    Args:
        subject: 邮件标题
        content: 邮件正文
        attachment_path: 附件路径（可选，支持图片或视频）
        
    Returns:
        是否发送成功
    """
    # 检查邮件功能是否启用
    if not EmailConfig.ENABLED:
        logging.debug("📧 [Email] 邮件功能未启用，跳过发送")
        return False
    
    # 检查配置
    if not EmailConfig.SENDER_EMAIL or not EmailConfig.SENDER_PASSWORD:
        logging.warning("⚠️ [Email] 邮件配置不完整，无法发送")
        return False
    
    try:
        # 创建邮件
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = EmailConfig.SENDER_EMAIL
        msg['To'] = EmailConfig.RECEIVER_EMAIL
        
        # 添加正文
        msg.attach(MIMEText(content, 'plain', 'utf-8'))
        
        # 添加附件（如果存在）
        if attachment_path and os.path.exists(attachment_path):
            filename = os.path.basename(attachment_path)
            file_ext = os.path.splitext(filename)[1].lower()
            
            with open(attachment_path, 'rb') as f:
                file_data = f.read()
                
                # 根据文件类型创建不同的MIME类型
                if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
                    attachment = MIMEImage(file_data)
                    attachment.add_header('Content-Disposition', 'attachment', filename=filename)
                elif file_ext in ['.mp4', '.avi', '.mov']:
                    attachment = MIMEApplication(file_data, Name=filename)
                    attachment['Content-Disposition'] = f'attachment; filename="{filename}"'
                else:
                    attachment = MIMEApplication(file_data, Name=filename)
                    attachment['Content-Disposition'] = f'attachment; filename="{filename}"'
                
                msg.attach(attachment)
                logging.info(f"📧 [Email] 添加附件: {filename}")
        
        # 发送邮件
        server = smtplib.SMTP_SSL(EmailConfig.SMTP_SERVER, EmailConfig.SMTP_PORT)
        server.login(EmailConfig.SENDER_EMAIL, EmailConfig.SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        logging.info(f"📧 [Email] 邮件发送成功: {subject}")
        return True
        
    except Exception as e:
        logging.error(f"❌ [Email] 邮件发送失败: {e}")
        return False


async def send_email_alert_async(subject: str, content: str, attachment_path: str = None) -> bool:
    """
    异步发送邮件报警（在线程池中执行同步发送）
    
    Args:
        subject: 邮件标题
        content: 邮件正文
        attachment_path: 附件路径
        
    Returns:
        是否发送成功
    """
    import asyncio
    
    try:
        # 在线程池中执行同步发送
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            None, 
            send_email_alert_sync, 
            subject, content, attachment_path
        )
        return success
    except Exception as e:
        logging.error(f"❌ [Email] 异步邮件发送失败: {e}")
        return False


class EmailClient:
    """
    邮件客户端类（提供更高级的接口）
    """
    
    def __init__(self):
        self.enabled = EmailConfig.ENABLED
        if self.enabled:
            logging.info("📧 [EmailClient] 初始化完成")
        else:
            logging.info("📧 [EmailClient] 邮件功能已禁用")
    
    async def send_alert(
        self, 
        alert_type: str, 
        description: str, 
        details: dict = None,
        attachment_path: str = None
    ) -> bool:
        """
        发送报警邮件
        
        Args:
            alert_type: 报警类型（visual/behavior/system）
            description: 报警描述
            details: 详细信息字典
            attachment_path: 附件路径
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        # 构建邮件内容
        subject = self._build_subject(alert_type, description)
        content = self._build_content(alert_type, description, details)
        
        return await send_email_alert_async(subject, content, attachment_path)
    
    def _build_subject(self, alert_type: str, description: str) -> str:
        """构建邮件标题"""
        prefixes = {
            "visual": "🚨 [视觉报警]",
            "behavior": "⚠️ [行为报警]", 
            "system": "🔧 [系统报警]",
            "info": "ℹ️ [信息通知]"
        }
        
        prefix = prefixes.get(alert_type, "📢 [通知]")
        short_desc = description[:30] + "..." if len(description) > 30 else description
        
        return f"{prefix} {short_desc}"
    
    def _build_content(self, alert_type: str, description: str, details: dict = None) -> str:
        """构建邮件正文"""
        from datetime import datetime
        
        content = f"""
报警时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
报警类型: {alert_type}
报警描述: {description}
"""
        
        if details:
            content += "\n详细信息:\n"
            for key, value in details.items():
                content += f"  - {key}: {value}\n"
        
        content += f"""
---
AI Camera Agent 系统
"""
        
        return content.strip()