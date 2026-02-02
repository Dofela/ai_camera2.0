# hand/executor/skill_executor.py
"""
技能执行器 - 负责执行具体技能逻辑
"""
import logging
import asyncio
from typing import Dict, Any
from skills.base_skill import BaseSkill


class SkillExecutor:
    """
    技能执行器，负责：
    1. 执行技能逻辑
    2. 超时控制
    3. 异常处理
    4. 性能监控
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout  # 默认超时时间（秒）
        self.execution_stats = {}  # 执行统计

    async def execute(self, skill: BaseSkill, params: Dict[str, Any]) -> str:
        """
        执行技能

        Args:
            skill: 技能实例
            params: 已验证的参数

        Returns:
            执行结果字符串
        """
        skill_name = skill.name
        logging.info(f"🔄 开始执行技能: {skill_name}, 参数: {params}")

        try:
            # 设置超时
            result = await asyncio.wait_for(
                self._execute_with_monitoring(skill, params),
                timeout=self.timeout
            )

            # 记录执行成功
            self._record_execution(skill_name, success=True)
            logging.info(f"✅ 技能执行成功: {skill_name}")

            return result

        except asyncio.TimeoutError:
            error_msg = f"❌ 技能执行超时: {skill_name} (超时时间: {self.timeout}秒)"
            logging.error(error_msg)
            self._record_execution(skill_name, success=False)
            return error_msg

        except Exception as e:
            error_msg = f"❌ 技能执行异常: {skill_name}, 错误: {str(e)}"
            logging.error(error_msg, exc_info=True)
            self._record_execution(skill_name, success=False)
            return error_msg

    async def _execute_with_monitoring(self, skill: BaseSkill, params: Dict[str, Any]) -> str:
        """带监控的技能执行"""
        import time
        start_time = time.time()

        try:
            # 执行技能
            result = await skill.execute(params)

            # 计算执行时间
            execution_time = time.time() - start_time

            # 记录性能指标
            self._record_performance(skill.name, execution_time)

            return result

        except Exception as e:
            # 重新抛出异常，由外层处理
            raise e

    def _record_execution(self, skill_name: str, success: bool):
        """记录执行统计"""
        if skill_name not in self.execution_stats:
            self.execution_stats[skill_name] = {
                "total": 0,
                "success": 0,
                "failure": 0
            }

        stats = self.execution_stats[skill_name]
        stats["total"] += 1
        if success:
            stats["success"] += 1
        else:
            stats["failure"] += 1

    def _record_performance(self, skill_name: str, execution_time: float):
        """记录性能指标"""
        if skill_name not in self.execution_stats:
            self.execution_stats[skill_name] = {
                "total": 0,
                "success": 0,
                "failure": 0,
                "total_time": 0.0,
                "avg_time": 0.0
            }

        stats = self.execution_stats[skill_name]
        if "total_time" not in stats:
            stats["total_time"] = 0.0
            stats["avg_time"] = 0.0

        stats["total_time"] += execution_time
        if stats["success"] > 0:
            stats["avg_time"] = stats["total_time"] / stats["success"]

    def get_execution_stats(self, skill_name: str = None) -> Dict:
        """获取执行统计"""
        if skill_name:
            return self.execution_stats.get(skill_name, {})
        else:
            return self.execution_stats

    def get_success_rate(self, skill_name: str) -> float:
        """获取技能成功率"""
        stats = self.execution_stats.get(skill_name)
        if not stats or stats["total"] == 0:
            return 0.0
        return stats["success"] / stats["total"]

    def get_average_execution_time(self, skill_name: str) -> float:
        """获取平均执行时间"""
        stats = self.execution_stats.get(skill_name)
        if not stats or "avg_time" not in stats:
            return 0.0
        return stats["avg_time"]

    def reset_stats(self, skill_name: str = None):
        """重置统计"""
        if skill_name:
            if skill_name in self.execution_stats:
                self.execution_stats[skill_name] = {
                    "total": 0,
                    "success": 0,
                    "failure": 0,
                    "total_time": 0.0,
                    "avg_time": 0.0
                }
        else:
            self.execution_stats.clear()

    def set_timeout(self, timeout: int):
        """设置超时时间"""
        self.timeout = timeout
        logging.info(f"技能执行器超时时间设置为: {timeout}秒")