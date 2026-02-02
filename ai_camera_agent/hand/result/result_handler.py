# hand/result/result_handler.py
"""
结果处理器 - 处理技能执行结果
"""
import logging
import re
from typing import Dict, Any


class ResultHandler:
    """
    结果处理器，负责：
    1. 结果格式化
    2. 结果分类
    3. 结果存储
    4. 结果通知
    """

    def __init__(self):
        self.result_patterns = {
            "success": [r"✅", r"👁️", r"🧠", r"成功", r"完成", r"已"],
            "warning": [r"⚠️", r"注意", r"警告", r"建议"],
            "error": [r"❌", r"错误", r"失败", r"异常", r"无法", r"不支持"],
            "info": [r"ℹ️", r"信息", r"提示"]
        }

    async def process(self, result: str, skill_name: str, params: Dict[str, Any]) -> str:
        """
        处理技能执行结果

        Args:
            result: 原始结果字符串
            skill_name: 技能名称
            params: 技能参数

        Returns:
            处理后的结果字符串
        """
        # 1. 结果分类
        result_type = self._classify_result(result)

        # 2. 结果格式化
        formatted_result = self._format_result(result, skill_name, result_type)

        # 3. 记录日志
        self._log_result(skill_name, result_type, params, result)

        # 4. 检查是否需要特殊处理
        if result_type == "error":
            formatted_result = self._enhance_error_message(formatted_result, skill_name)

        return formatted_result

    def _classify_result(self, result: str) -> str:
        """分类结果"""
        result_lower = result.lower()

        for result_type, patterns in self.result_patterns.items():
            for pattern in patterns:
                if re.search(pattern, result_lower) or pattern in result:
                    return result_type

        # 默认分类为信息
        return "info"

    def _format_result(self, result: str, skill_name: str, result_type: str) -> str:
        """格式化结果"""
        # 移除多余的空格和换行
        result = result.strip()

        # 根据结果类型添加前缀
        if result_type == "success":
            if not result.startswith("✅"):
                result = f"✅ {result}"
        elif result_type == "error":
            if not result.startswith("❌"):
                result = f"❌ {result}"
        elif result_type == "warning":
            if not result.startswith("⚠️"):
                result = f"⚠️ {result}"
        elif result_type == "info":
            if not result.startswith("ℹ️"):
                result = f"ℹ️ {result}"

        # 添加技能名称标签
        skill_tag = self._get_skill_tag(skill_name)
        if skill_tag and skill_tag not in result:
            result = f"{skill_tag} {result}"

        return result

    def _get_skill_tag(self, skill_name: str) -> str:
        """获取技能标签"""
        skill_tags = {
            "visual_perception": "👁️",
            "observation": "🔍",
            "security_mode": "🛡️",
            "dismiss_alerts": "🔕",
            "log_search": "📊",
            "report": "📈",
            "email_notify": "📧",
            "health_check": "🏥",
            "vision_control": "🎯"
        }
        return skill_tags.get(skill_name, "🛠️")

    def _log_result(self, skill_name: str, result_type: str, params: Dict[str, Any], result: str):
        """记录结果日志"""
        log_level = {
            "success": logging.INFO,
            "error": logging.ERROR,
            "warning": logging.WARNING,
            "info": logging.INFO
        }.get(result_type, logging.INFO)

        # 简化参数日志（避免敏感信息）
        safe_params = self._sanitize_params(params)

        logging.log(
            log_level,
            f"技能结果 - 技能: {skill_name}, 类型: {result_type}, 参数: {safe_params}, 结果: {result[:100]}..."
        )

    def _sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """清理参数（移除敏感信息）"""
        safe_params = params.copy()

        # 定义敏感字段
        sensitive_fields = ["password", "token", "key", "secret", "auth"]

        for field in sensitive_fields:
            if field in safe_params:
                safe_params[field] = "***REDACTED***"

        return safe_params

    def _enhance_error_message(self, error_message: str, skill_name: str) -> str:
        """增强错误消息"""
        error_enhancements = {
            "visual_perception": "请检查摄像头连接和权限。",
            "observation": "请确保观察模式已正确配置。",
            "security_mode": "请检查安防模式配置。",
            "dismiss_alerts": "请确认当前是否有活跃警报。",
            "log_search": "请检查数据库连接和查询条件。",
            "email_notify": "请检查邮件服务器配置和收件人地址。",
            "health_check": "请检查系统组件状态。",
            "vision_control": "请检查视觉模块配置。"
        }

        enhancement = error_enhancements.get(skill_name, "请检查相关配置并重试。")

        if "建议" not in error_message:
            error_message += f"\n💡 建议: {enhancement}"

        return error_message

    def extract_key_info(self, result: str) -> Dict[str, Any]:
        """从结果中提取关键信息"""
        key_info = {
            "has_targets": False,
            "target_count": 0,
            "has_alerts": False,
            "is_abnormal": False,
            "summary": ""
        }

        # 检查是否有目标检测
        target_patterns = [r"检测到\s*(\d+)\s*个目标", r"(\d+)\s*个目标", r"目标:\s*(\d+)"]
        for pattern in target_patterns:
            match = re.search(pattern, result)
            if match:
                key_info["has_targets"] = True
                key_info["target_count"] = int(match.group(1))
                break

        # 检查是否有警报
        alert_patterns = [r"警报", r"报警", r"异常", r"危险", r"⚠️", r"❌"]
        for pattern in alert_patterns:
            if re.search(pattern, result):
                key_info["has_alerts"] = True
                break

        # 检查是否异常
        abnormal_patterns = [r"异常", r"错误", r"失败", r"❌"]
        for pattern in abnormal_patterns:
            if re.search(pattern, result):
                key_info["is_abnormal"] = True
                break

        # 生成摘要
        if len(result) > 100:
            key_info["summary"] = result[:100] + "..."
        else:
            key_info["summary"] = result

        return key_info

    async def store_result(self, result: str, skill_name: str, params: Dict[str, Any]):
        """存储结果（预留接口，可扩展为数据库存储）"""
        # 这里可以扩展为将结果存储到数据库
        pass