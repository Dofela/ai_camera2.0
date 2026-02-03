# infrastructure/database/schemas.py
"""
数据库表结构定义 - PostgreSQL
"""
from config.settings import VectorConfig

# 启用 pgvector 扩展
INIT_EXTENSIONS = """
CREATE EXTENSION IF NOT EXISTS vector;
"""

# 1. 安全事件表 (日志流)
# 策略: 热数据，无向量索引，JSONB 存储详情
CREATE_TABLE_EVENTS = """
CREATE TABLE IF NOT EXISTS security_events (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) DEFAULT 'ongoing',

    start_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMPTZ,

    -- Stage 1 统计数据 (e.g., {"person": 1})
    target_data JSONB DEFAULT '{}'::jsonb,

    -- Stage 2 精修特征 (e.g., [{"label": "face", "box": [...], "vector": [...]}])
    -- 核心变更: 存储空间特征和陌生人向量
    refine_data JSONB DEFAULT '[]'::jsonb,

    sys_summary TEXT,    -- 自然语言描述
    ai_analysis TEXT,    -- VLM 分析结果

    is_abnormal BOOLEAN DEFAULT FALSE,
    alert_tags TEXT,     -- 逗号分隔的标签

    video_path TEXT,     -- 仅存文件路径
    snapshot_path TEXT
);

-- 基础索引 (B-Tree)
CREATE INDEX IF NOT EXISTS idx_events_status ON security_events(status);
CREATE INDEX IF NOT EXISTS idx_events_time ON security_events(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_abnormal ON security_events(is_abnormal);
-- GIN 索引: 允许查询 JSON 内容 (e.g., 查找所有包含 'knife' 的事件)
CREATE INDEX IF NOT EXISTS idx_events_target ON security_events USING GIN (target_data);
"""

# 2. 已知身份表 (海马体)
# 策略: 冷数据，HNSW 索引，用于认人
# 注意: 向量维度从配置读取
CREATE_TABLE_IDENTITIES = f"""
CREATE TABLE IF NOT EXISTS known_identities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(20) DEFAULT 'family', -- family, guest, black

    -- 人脸向量 (用于打招呼)
    face_vec vector({VectorConfig.DIMENSION}),

    -- 体态向量 (用于背影追踪/ReID)
    -- 通常 ReID 维度可能不同(如2048)，这里暂用相同配置或需要在 Config 区分
    -- 假设 ReID 为 2048，若未配置则暂不创建或设为默认
    body_vec vector(2048), 

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMPTZ,
    notes TEXT
);

-- HNSW 索引: 实现毫秒级向量检索
-- opclass: vector_cosine_ops (余弦相似度)
CREATE INDEX IF NOT EXISTS idx_identities_face ON known_identities 
USING hnsw (face_vec vector_cosine_ops);
"""

# 3. 观察流表 (高频日志)
CREATE_TABLE_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS observation_stream (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    content TEXT,
    target VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_obs_time ON observation_stream(timestamp DESC);
"""


# 聚合所有初始化语句
def get_init_sqls():
    return [
        INIT_EXTENSIONS,
        CREATE_TABLE_EVENTS,
        CREATE_TABLE_IDENTITIES,
        CREATE_TABLE_OBSERVATIONS
    ]