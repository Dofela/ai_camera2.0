# hand/registry/skill_registry.py
"""
技能注册表 - 管理所有可用技能
"""
import logging
from typing import Dict, List, Optional
from skills.base_skill import BaseSkill


class SkillRegistry:
    """
    技能注册表，负责：
    1. 技能注册与注销
    2. 技能查找
    3. 技能分类管理
    """

    def __init__(self):
        self.skills: Dict[str, BaseSkill] = {}
        self.categories: Dict[str, List[str]] = {
            "vision": [],      # 视觉相关技能
            "security": [],    # 安防相关技能
            "data": [],        # 数据相关技能
            "notification": [], # 通知相关技能
            "system": [],      # 系统相关技能
            "general": []      # 通用技能
        }

    def register(self, skill: BaseSkill, category: str = None):
        """注册技能"""
        if skill.name in self.skills:
            logging.warning(f"技能 {skill.name} 已存在，将被覆盖")

        self.skills[skill.name] = skill

        # 自动分类或使用指定分类
        if category:
            skill_category = category
        else:
            skill_category = self._auto_categorize(skill.name)

        if skill_category not in self.categories:
            self.categories[skill_category] = []

        if skill.name not in self.categories[skill_category]:
            self.categories[skill_category].append(skill.name)

        logging.debug(f"注册技能: {skill.name} -> 分类: {skill_category}")

    def unregister(self, skill_name: str):
        """注销技能"""
        if skill_name in self.skills:
            # 从分类中移除
            for category, skills in self.categories.items():
                if skill_name in skills:
                    skills.remove(skill_name)

            # 从技能字典中移除
            del self.skills[skill_name]
            logging.debug(f"注销技能: {skill_name}")

    def get_skill(self, skill_name: str) -> Optional[BaseSkill]:
        """获取技能"""
        return self.skills.get(skill_name)

    def get_skills_by_category(self, category: str) -> List[BaseSkill]:
        """按分类获取技能"""
        skill_names = self.categories.get(category, [])
        return [self.skills[name] for name in skill_names if name in self.skills]

    def list_all_skills(self) -> List[dict]:
        """列出所有技能信息"""
        skills_info = []
        for name, skill in self.skills.items():
            skills_info.append({
                "name": name,
                "description": skill.description,
                "category": self._get_skill_category(name)
            })
        return skills_info

    def get_available_tools(self) -> List[dict]:
        """获取可用工具列表（用于LLM）"""
        tools = []
        for skill in self.skills.values():
            tools.append(skill.get_schema())
        return tools

    def _auto_categorize(self, skill_name: str) -> str:
        """自动分类技能"""
        skill_name_lower = skill_name.lower()

        if any(keyword in skill_name_lower for keyword in ["vision", "visual", "observation", "camera"]):
            return "vision"
        elif any(keyword in skill_name_lower for keyword in ["security", "alert", "dismiss", "guard"]):
            return "security"
        elif any(keyword in skill_name_lower for keyword in ["data", "log", "search", "report"]):
            return "data"
        elif any(keyword in skill_name_lower for keyword in ["email", "notification", "notify"]):
            return "notification"
        elif any(keyword in skill_name_lower for keyword in ["system", "health", "check", "control"]):
            return "system"
        else:
            return "general"

    def _get_skill_category(self, skill_name: str) -> str:
        """获取技能的分类"""
        for category, skills in self.categories.items():
            if skill_name in skills:
                return category
        return "general"

    def clear(self):
        """清空注册表"""
        self.skills.clear()
        for category in self.categories:
            self.categories[category].clear()
        logging.info("技能注册表已清空")