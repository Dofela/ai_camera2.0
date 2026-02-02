# brain/intent/intent_router.py
"""
意图路由器 - Brain的"前额叶皮层"

在LLM决策之前，先用规则/小模型快速判断意图类别
优点：零延迟、可解释、可调试
"""
import re
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass


class IntentCategory(Enum):
    """意图大类 - 硬编码的快速路由"""
    VISION_ONCE = "vision_once"          # 看一眼（look_at_camera）
    VISION_TRACK = "vision_track"        # 持续追踪（manage_observation_mode）
    VISION_CONFIG = "vision_config"      # 修改检测目标（update_vision_targets）
    SECURITY_MODE = "security_mode"      # 安防模式切换
    ALERT_CONTROL = "alert_control"      # 报警控制
    DATA_QUERY = "data_query"            # 数据查询
    SYSTEM_CHECK = "system_check"        # 系统检查
    CHITCHAT = "chitchat"                # 闲聊（不需要工具）


@dataclass
class IntentResult:
    category: IntentCategory
    confidence: float  # 0-1
    suggested_skill: Optional[str] = None
    extracted_params: Optional[dict] = None


class IntentRouter:
    """
    基于规则的快速意图识别
    """

    # 关键词映射表（可扩展为配置文件或数据库）
    INTENT_PATTERNS = {
        IntentCategory.VISION_ONCE: {
            "keywords": ["看看", "看一下", "看下", "现在有什么", "画面", "是谁", "在干嘛", "在做什么", "有没有人", "什么情况"],
            "skill": "visual_perception",
            "anti_keywords": ["盯着", "持续", "追踪", "跟踪", "别让他跑", "只看", "只检测", "关注"]  # 排除词
        },
        IntentCategory.VISION_TRACK: {
            "keywords": ["盯着", "持续", "追踪", "跟踪", "别让他跑", "锁定", "监视他"],
            "skill": "observation",
            "default_params": {"action": "start"}
        },
        IntentCategory.VISION_CONFIG: {
            "keywords": ["只看", "只检测", "只关注", "检测有没有", "关注", "帮我盯", "发现", "检测"],
            "skill": "vision_control",
            "anti_keywords": ["看看", "看一下"],  # 区分"看看有没有人"和"只检测人"
            "extract_targets": True  # 标记需要提取目标
        },
        IntentCategory.SECURITY_MODE: {
            "keywords": ["出门", "离家", "上班", "回来", "到家", "睡觉", "晚安", "起床", "醒了"],
            "skill": "security_mode",
            "param_mapping": {
                "出门|离家|上班": {"mode": "away"},
                "回来|到家|回家": {"mode": "home"},
                "睡觉|晚安|睡了": {"mode": "sleep"},
            }
        },
        IntentCategory.ALERT_CONTROL: {
            "keywords": ["没事", "误报", "取消报警", "解除", "撤销", "别报警", "停止报警", "关掉报警"],
            "skill": "dismiss_alerts",
            "default_params": {"action": "clear_all"}
        },
        IntentCategory.DATA_QUERY: {
            "keywords": ["日志", "记录", "历史", "之前", "刚才", "上次"],
            "skill": "log_search"
        },
        IntentCategory.SYSTEM_CHECK: {
            "keywords": ["系统状态", "健康检查", "运行状态", "摄像头状态", "视觉状态"],
            "skill": "health_check"
        },
    }

    # 闲聊检测
    CHITCHAT_PATTERNS = [
        r"^(你好|嗨|hi|hello|早上好|晚上好|下午好)",
        r"^(谢谢|感谢|辛苦)",
        r"^(再见|拜拜|bye)",
        r"^(你是谁|你叫什么)",
        r"^(帮我|请问|能不能).*(?!看|盯|追踪)",  # 通用请求但不涉及视觉
    ]

    def route(self, user_input: str) -> IntentResult:
        """
        快速路由用户意图
        返回：意图类别 + 置信度 + 建议的技能 + 提取的参数
        """
        text = user_input.lower().strip()

        # 1. 先检查是否是闲聊
        for pattern in self.CHITCHAT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return IntentResult(
                    category=IntentCategory.CHITCHAT,
                    confidence=0.9,
                    suggested_skill=None
                )

        # 2. 遍历意图模式，找最匹配的
        best_match = None
        best_score = 0

        for category, config in self.INTENT_PATTERNS.items():
            score = self._calculate_match_score(text, config)
            if score > best_score:
                best_score = score
                best_match = (category, config)

        # 3. 如果匹配度足够高，返回结果
        if best_match and best_score >= 0.5:
            category, config = best_match
            params = self._extract_params(text, config)
            return IntentResult(
                category=category,
                confidence=best_score,
                suggested_skill=config.get("skill"),
                extracted_params=params
            )

        # 4. 无法判断，交给LLM
        return IntentResult(
            category=IntentCategory.CHITCHAT,  # 默认闲聊
            confidence=0.3,
            suggested_skill=None
        )

    def _calculate_match_score(self, text: str, config: dict) -> float:
        """计算匹配分数"""
        keywords = config.get("keywords", [])
        anti_keywords = config.get("anti_keywords", [])

        # 检查排除词
        for anti in anti_keywords:
            if anti in text:
                return 0.0

        # 计算匹配的关键词数量
        matched = sum(1 for kw in keywords if kw in text)
        if matched == 0:
            return 0.0

        # 归一化分数
        return min(1.0, matched / 2)  # 匹配2个关键词即满分

    def _extract_params(self, text: str, config: dict) -> dict:
        """从文本中提取参数"""
        params = config.get("default_params", {}).copy()

        # 特殊处理：安防模式参数映射
        param_mapping = config.get("param_mapping", {})
        for pattern, mapped_params in param_mapping.items():
            if re.search(pattern, text):
                params.update(mapped_params)
                break

        # 特殊处理：视觉目标提取
        if config.get("extract_targets"):
            targets = self._extract_vision_targets(text)
            if targets:
                params["targets"] = targets
                # 根据语义判断风险等级
                if any(word in text for word in ["报警", "警报", "危险", "陌生人", "入侵"]):
                    params["risk_level"] = "high"
                elif any(word in text for word in ["记录", "只是看看"]):
                    params["risk_level"] = "low"
                else:
                    params["risk_level"] = "medium"

        return params

    def _extract_vision_targets(self, text: str) -> list:
        """
        从用户输入中提取检测目标

        示例:
        - "只检测人和车" → ["person", "car"]
        - "帮我关注包裹" → ["package"]
        - "检测有没有火" → ["fire"]
        """
        # 常见目标映射（中文→英文）
        target_mapping = {
            "人": "person",
            "人类": "person",
            "行人": "person",
            "陌生人": "person",
            "车": "car",
            "汽车": "car",
            "车辆": "car",
            "包裹": "package",
            "快递": "package",
            "盒子": "box",
            "火": "fire",
            "火焰": "fire",
            "烟": "smoke",
            "烟雾": "smoke",
            "刀": "knife",
            "刀具": "knife",
            "狗": "dog",
            "猫": "cat",
            "动物": "animal",
            "宠物": "pet",
            "手机": "cell phone",
            "电脑": "laptop",
            "背包": "backpack",
            "书包": "backpack",
        }

        targets = []
        for cn, en in target_mapping.items():
            if cn in text and en not in targets:
                targets.append(en)

        return targets if targets else ["person"]  # 默认检测人


# ============================================================
# 使用示例
# ============================================================
if __name__ == "__main__":
    router = IntentRouter()

    test_cases = [
        "看看现在画面里有什么",
        "那个人在干嘛",
        "盯着他，别让他跑了",
        "我出门了",
        "没事了，误报",
        "你好",
        "帮我查一下今天的日志",
        "只检测人和车",
        "帮我关注门口的包裹",
        "检测有没有火，发现就报警",
    ]

    for text in test_cases:
        result = router.route(text)
        print(f"输入: {text}")
        print(f"  → 意图: {result.category.value}")
        print(f"  → 置信度: {result.confidence}")
        print(f"  → 建议技能: {result.suggested_skill}")
        print(f"  → 参数: {result.extracted_params}")
        print()