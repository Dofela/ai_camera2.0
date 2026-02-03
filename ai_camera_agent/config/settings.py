# config/settings.py
"""
全局配置文件 - AI Camera Agent

配置优先级: 环境变量 > .env文件 > 默认值
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# ============================================================
# 项目路径配置
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "video_archive")
VIDEO_SOURCE = os.getenv("VIDEO_SOURCE")  # 0=摄像头, 或RTSP地址


# ============================================================
# 服务器配置
# ============================================================
class ServerConfig:
    """FastAPI 服务器配置"""
    HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("SERVER_PORT", "8000"))
    RELOAD: bool = os.getenv("SERVER_RELOAD", "false").lower() == "true"
    WORKERS: int = int(os.getenv("SERVER_WORKERS", "1"))


# ============================================================
# 视频配置
# ============================================================
class VideoConfig:
    """视频采集与处理配置"""
    # 视频源
    SOURCE: str = VIDEO_SOURCE

    # 帧率控制
    TARGET_FPS: int = int(os.getenv("VIDEO_TARGET_FPS", "25"))

    # 缓冲区配置
    BUFFER_SIZE: int = int(os.getenv("VIDEO_BUFFER_SIZE", "1"))
    CONTEXT_DURATION: float = float(os.getenv("VIDEO_CONTEXT_DURATION", "6.0"))

    # 编码质量
    JPEG_QUALITY: int = int(os.getenv("VIDEO_JPEG_QUALITY", "80"))

    # 录像配置
    VIDEO_INTERVAL: int = int(os.getenv("VIDEO_INTERVAL", "300"))  # 5分钟切片

    # WebSocket配置
    WS_RETRY_INTERVAL: float = float(os.getenv("WS_RETRY_INTERVAL", "3.0"))


# ============================================================
# YOLO 检测配置
# ============================================================
class YoloConfig:
    """YOLO 目标检测配置"""
    # 模式选择
    USE_LOCAL_MODEL: bool = os.getenv("YOLO_USE_LOCAL", "true").lower() == "true"

    # 本地模型配置
    LOCAL_MODEL_PATH: str = os.getenv("YOLO_MODEL_PATH", "yolov8n.pt")

    # 远程服务配置
    WS_URL: str = os.getenv("YOLO_WS_URL", "ws://localhost:8765")
    API_URL: str = os.getenv("YOLO_API_URL", "http://localhost:8765/update_targets")

    # 检测参数
    DETECT_FPS: int = int(os.getenv("YOLO_DETECT_FPS", "5"))
    CONFIDENCE_THRESHOLD: float = float(os.getenv("YOLO_CONFIDENCE", "0.35"))
    NMS_THRESHOLD: float = float(os.getenv("YOLO_NMS_THRESHOLD", "0.45"))

    # [Stage 1] 默认粗筛目标 (寻找感兴趣区域 ROI)
    DEFAULT_TARGETS: list = ["person", "car", "bicycle", "motorcycle"]

    # [Stage 2] 精修目标 (在 ROI 中寻找细节，用于提取特征向量)
    # 这些目标只在 Stage 2 的裁剪图中进行检测
    REFINE_TARGETS: list = ["face", "license plate", "mobile phone", "cigarette", "knife"]


# ============================================================
# VLM 配置基类
# ============================================================
class VLMConfig:
    """VLM (视觉语言模型) 基础配置"""
    API_URL: str = os.getenv("VLM_API_URL", "https://api.openai.com/v1/chat/completions")
    API_KEY: str = os.getenv("VLM_API_KEY", "")
    MODEL: str = os.getenv("VLM_MODEL", "gpt-4-vision-preview")

    # 请求参数
    TEMPERATURE: float = float(os.getenv("VLM_TEMPERATURE", "0.1"))
    TOP_P: float = float(os.getenv("VLM_TOP_P", "0.8"))
    REQUEST_TIMEOUT: float = float(os.getenv("VLM_TIMEOUT", "30.0"))
    MAX_RETRIES: int = int(os.getenv("VLM_MAX_RETRIES", "3"))


# ============================================================
# 监控专用 LLM 配置
# ============================================================
class MonitorLLMConfig(VLMConfig):
    """监控分析专用 LLM 配置 (用于安防分析)"""
    API_URL: str = os.getenv("MONITOR_LLM_URL", VLMConfig.API_URL)
    API_KEY: str = os.getenv("MONITOR_LLM_KEY", VLMConfig.API_KEY)
    MODEL: str = os.getenv("MONITOR_LLM_MODEL", VLMConfig.MODEL)
    REQUEST_TIMEOUT: float = float(os.getenv("MONITOR_LLM_TIMEOUT", "30.0"))


# ============================================================
# 对话专用 LLM 配置
# ============================================================
class ChatLLMConfig(VLMConfig):
    """对话交互专用 LLM 配置 (用于用户对话)"""
    API_URL: str = os.getenv("CHAT_LLM_URL", VLMConfig.API_URL)
    API_KEY: str = os.getenv("CHAT_LLM_KEY", VLMConfig.API_KEY)
    MODEL: str = os.getenv("CHAT_LLM_MODEL", "gpt-4-turbo-preview")
    REQUEST_TIMEOUT: float = float(os.getenv("CHAT_LLM_TIMEOUT", "60.0"))


# ============================================================
# 数据库配置 (PostgreSQL Upgrade)
# ============================================================
class DBConfig:
    """数据库配置 - PostgreSQL"""

    # 基础连接参数
    HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    USER: str = os.getenv("POSTGRES_USER", "postgres")
    PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    DB_NAME: str = os.getenv("POSTGRES_DB", "ai_camera_db")

    # 构建 DSN (Data Source Name)
    # 同步用 (psycopg2): postgresql://user:pass@host:port/dbname
    DATABASE_URL: str = f"postgresql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"

    # 异步用 (asyncpg): postgresql://user:pass@host:port/dbname
    # asyncpg 直接使用相同的 URL 格式即可，或者拆分参数传给 connect

    # 连接池配置
    # Web端连接池 (psycopg2)
    POOL_MIN_SIZE: int = int(os.getenv("DB_POOL_MIN", "1"))
    POOL_MAX_SIZE: int = int(os.getenv("DB_POOL_MAX", "5"))

    # Eye端连接池 (asyncpg) - 这里的配置要大，因为是高频写入
    EYE_POOL_MIN_SIZE: int = int(os.getenv("EYE_POOL_MIN", "2"))
    EYE_POOL_MAX_SIZE: int = int(os.getenv("EYE_POOL_MAX", "10"))


class VectorConfig:
    """向量数据库配置"""
    # 向量维度 (根据你使用的 ReID/Face 模型决定，例如 FaceNet 是 512 或 128)
    DIMENSION: int = int(os.getenv("VECTOR_DIMENSION", "512"))

    # 索引类型: 'hnsw' (快但费内存/CPU) 或 'ivfflat' (慢但省资源)
    # 建议: known_identities 用 hnsw，security_events 用 ivfflat 或不建索引
    INDEX_TYPE: str = os.getenv("VECTOR_INDEX_TYPE", "hnsw")


# ============================================================
# 邮件配置
# ============================================================
class EmailConfig:
    """邮件报警配置"""
    ENABLED: bool = os.getenv("EMAIL_ENABLED", "false").lower() == "true"

    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))

    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "")
    SENDER_PASSWORD: str = os.getenv("SENDER_PASSWORD", "")
    RECEIVER_EMAIL: str = os.getenv("RECEIVER_EMAIL", "")


# ============================================================
# 感知层配置 (Eye)
# ============================================================
class EyeConfig:
    """眼睛模块配置"""
    # 状态过滤器配置
    IOU_THRESHOLD: float = float(os.getenv("EYE_IOU_THRESHOLD", "0.85"))
    RECHECK_INTERVAL: float = float(os.getenv("EYE_RECHECK_INTERVAL", "15.0"))

    # [新增] 移动检测阈值 (像素) - 用于触发 Stage 2
    MOVEMENT_THRESHOLD: float = float(os.getenv("EYE_MOVEMENT_THRESHOLD", "20.0"))

    # 高危目标 (始终触发报警)
    BASE_ALERT_CLASSES: set = {"fire", "smoke", "blood", "knife", "fall"}

    # 事件关闭容忍帧数
    LOSS_TOLERANCE: int = int(os.getenv("EYE_LOSS_TOLERANCE", "15"))
    
    # 最大事件持续时间（秒）
    MAX_EVENT_DURATION: int = int(os.getenv("EYE_MAX_EVENT_DURATION", "300"))  # 5分钟

    # VLM分析帧数
    VLM_FRAME_COUNT: int = int(os.getenv("EYE_VLM_FRAME_COUNT", "5"))


# ============================================================
# 辅助函数
# ============================================================
def print_config():
    """打印当前配置信息"""
    logging.info("=" * 60)
    logging.info("🔧 AI Camera Agent 配置信息")
    logging.info("=" * 60)
    logging.info(f"📹 视频源: {VIDEO_SOURCE}")
    logging.info(f"🎯 YOLO模式: {'本地' if YoloConfig.USE_LOCAL_MODEL else '远程'}")
    logging.info(f"🤖 监控LLM: {MonitorLLMConfig.MODEL}")
    logging.info(f"💬 对话LLM: {ChatLLMConfig.MODEL}")
    logging.info(f"💾 数据库: {DBConfig.DB_PATH}")
    logging.info(f"📧 邮件报警: {'开启' if EmailConfig.ENABLED else '关闭'}")
    logging.info("=" * 60)


def validate_config() -> bool:
    """验证配置有效性"""
    errors = []

    # 检查API Key
    if not VLMConfig.API_KEY:
        errors.append("VLM_API_KEY 未配置")

    # 检查视频源
    if VIDEO_SOURCE != "0" and not VIDEO_SOURCE.startswith(("rtsp://", "http://", "/")):
        if not os.path.exists(VIDEO_SOURCE):
            errors.append(f"视频源不存在: {VIDEO_SOURCE}")

    if errors:
        for err in errors:
            logging.warning(f"⚠️ 配置警告: {err}")
        return False

    return True