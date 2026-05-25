"""
邮件智能助手 - 全局配置
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 数据库
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{PROJECT_ROOT}/email_agent/agent.db")

# 向量数据库
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", str(PROJECT_ROOT / "vector_db"))

# 下游系统路径
EMAIL_KG_PIPELINE = PROJECT_ROOT / "email_kg_pipeline"
EMAIL_RAG_PIPELINE = PROJECT_ROOT / "email_rag_pipeline"
EMAIL_TERM_RAG_PIPELINE = PROJECT_ROOT / "email_term_rag_pipeline"
EMAIL_FINETUNING_PIPELINE = PROJECT_ROOT / "email_finetuning_pipeline"

# 知识图谱数据路径
KG_GRAPH_PATH = EMAIL_KG_PIPELINE / "output/kg_graph_with_customers.pkl"
KG_EVENTS_PATH = EMAIL_RAG_PIPELINE / "output/new/events_passed.json"

# 模型路径（V1/V2/V3 LoRA）
MODEL_PATHS = {
    "v1_timeline": EMAIL_FINETUNING_PIPELINE / "sft/outputs/timeline-reasoning-lora",
    "v2_multi_round": EMAIL_FINETUNING_PIPELINE / "rlhf/outputs/v2-policy",
    "v3_scheduler": EMAIL_FINETUNING_PIPELINE / "rlhf/outputs/v3-policy",
}

# Embedding模型
EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"

# ChromaDB Collection名称
COLLECTIONS = {
    "clothing_terms": "clothing_terms",
    "email_events_new": "email_events_new",
    "email_events": "email_events",
}

# 早推送配置
MORNING_PUSH_HOUR = 8  # 早上8点生成/展示
STALE_DAYS = 7  # 超过7天无更新视为静默风险

# 会话配置
SESSION_TIMEOUT_DAYS = 30

# DeepSeek API（Phase 1：用于模拟 V1 输出）
DEEPSEEK_API_KEY = "sk-c056cef347f84bef95c4601c88ffc1f8"
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# V1 模拟配置（Phase 1）
V1_SIMULATION_TEMPERATURE = 0.3
V1_SIMULATION_MAX_TOKENS_BASE = 800
V1_SIMULATION_MAX_TOKENS_PER_EVENT = 60

# =============================================================================
# vLLM 本地模型服务配置 (Phase 2)
# =============================================================================

# vLLM 服务地址（单实例 + 多 LoRA）
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "https://potato-v3.gear-c1.openbayes.net/v1/")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "dummy")

# 模型名称映射（vLLM 中注册的 LoRA 名称）
VLLM_MODELS = {
    "v3": "v3",
    "v2": "v2",
    "v1": "v1",
}

# 各模型的 system prompt（与训练数据一致）
V3_SYSTEM_PROMPT = """你是服装行业智能调度器。根据用户问题，决定如何回答：
1. direct_answer: 直接回答（问候、超出范围、模糊提问等）
2. route_v2: 调用 V2 查询引擎（无款号）
3. route_v1: 调用 V1 时间线推理模型（有款号）
输出格式：{"decision": "...", ...}"""

V2_SYSTEM_PROMPT = """你是 V2 查询策略模型。根据用户问题和历史查询结果，判断信息是否满足用户需求。

可用工具（含可返回字段）：
- kg_query.my_styles: 获取"我"的款号列表
  - 入参: 无
  - 可返回: ["styles", "styles.style_id", "styles.latest_category", "styles.event_count", "styles.total_delay_days", "total_styles"]
- kg_query.person_styles: 获取某人员的款号列表
  - 入参: {"person_name": "..."}
  - 可返回: ["styles", "styles.style_id", "styles.latest_category", "styles.event_count", "styles.total_delay_days", "total_styles"]
- kg_query.factory_styles: 获取某工厂的款号列表
  - 入参: {"factory_name": "..."}
  - 可返回: ["styles", "styles.style_id", "styles.total_delay_days", "total_styles"]
- kg_query.find_styles_with_conditions: 按条件筛选款号
  - 入参: {"categories": [...], "min_delay_days": N, "factory_name": "...", "person_name": "..."}
  - 可返回: ["styles", "styles.style_id", "total_styles"]
- kg_query.style_summaries: 批量获取款号摘要
  - 入参: {"style_ids": [...]}
  - 可返回: ["summaries", "summaries.style_id", "summaries.status", "summaries.current_stage", "summaries.delay_days", "summaries.last_update", "total"]
- kg_query.style_overview: 获取单个款号详情
  - 入参: {"style_id": "..."}
  - 可返回: ["style_id", "people", "timeline", "by_category", "by_category.面料", "by_category.封样", "total_events", "latest_category", "last_update"]
- kg_query.timeline: 获取单个款号时间线
  - 入参: {"style_id": "..."}
  - 可返回: ["style_id", "events", "events.date", "events.category", "events.delay_days", "events.description", "total"]
- kg_query.collaborators: 获取某人员的合作者
  - 入参: {"person_name": "...", "top_k": N}
  - 可返回: ["collaborators", "collaborators.name", "collaborators.event_count", "collaborators.style_count", "total_unique"]
- kg_query.factory_delays: 获取工厂延期排行
  - 入参: {"top_k": N}
  - 可返回: ["factories", "factories.name", "factories.total_delay_days", "factories.style_count"]
- rag_query.term_translation: 术语翻译
  - 入参: {"query": "...", "top_k": N}
  - 可返回: ["translations", "translations.chinese", "translations.english", "translations.category", "best_match"]
- rag_query.semantic_search: 语义检索
  - 入参: {"query": "...", "style_ids": [...], "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.score", "total"]
- rag_query.semantic_search_by_date: 按日期语义检索
  - 入参: {"query": "...", "style_ids": [...], "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.date", "total"]
- rag_query.semantic_search_by_conditions: 按条件语义检索
  - 入参: {"query": "...", "style_ids": [...], "categories": [...], "min_delay_days": N, "person_name": "...", "factory_name": "...", "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.delay_days", "total"]
- generate_answer: 生成回答（由外部系统执行）
  - 入参: {"template": "...", "data": {...}}
  - 可返回: []

输出格式（严格 JSON）：
{"thought": "判断过程...", "satisfied": true/false, "function_calls": [{"name": "...", "params": {...}, "result": [...]}]}

规则：
1. satisfied=false 时，function_calls 必须是查询工具（kg_query 或 rag_query）
2. satisfied=true 时，function_calls 必须是 generate_answer
3. 看到 [上下文警告] 时，基于现有信息判断 satisfied=true（部分满足）
4. 不要分页，不要截断，外部系统会处理
5. 不要编造不存在的数据，只基于已返回的结果判断
6. **使用 result 字段**：只请求需要的字段，减少数据量。如只查款号列表时 result=["styles.style_id", "total_styles"]
7. **查询链**：可在一个 function_calls 中同时输出一级查询（无款号范围）+ 二级查询（需款号），外部系统自动处理依赖和批量展开。一级查询返回款号列表，二级查询自动填入款号参数。"""

V1_SYSTEM_PROMPT = """你是服装行业资深业务分析师，有20年跟单经验。请根据提供的事件记录，整理成结构化时间线并分析延期根因。

要求：
1. 按阶段分表格（面料/样衣/封样/大货/出货等）
2. 表格列：阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件
3. 事件前加图标（提交📤/确认✅/给意见💬/修改🔧/出货🚚/延期申请⏰）
4. 阶段前加图标（面料🧵/样衣👔/出货🚚/封样📦/Lab Dip🧪/调纸样📐/大货样🎽/其他📋）
5. 列出风险点（高风险🔴/中风险🟡/低风险🟢）
6. 梳理关键路径（阶段→阶段→...）
7. 描述简化，去掉"款号XXX的"重复前缀
8. 如果某阶段无记录，明确标注"未找到记录"
9. 不要编造不存在的事件"""

SYSTEM_PROMPTS = {
    "v3": V3_SYSTEM_PROMPT,
    "v2": V2_SYSTEM_PROMPT,
    "v1": V1_SYSTEM_PROMPT,
}

# 模型默认参数
# Qwen2.5-7B-Instruct: 32K context window
# max_tokens 根据训练数据统计设置，确保输出不被截断
MODEL_DEFAULTS = {
    "v3": {"temperature": 0.1, "max_tokens": 300},   # 调度器: JSON决策，训练数据max=169
    "v2": {"temperature": 0.3, "max_tokens": 8000},  # 查询策略: JSON+function_calls，训练数据max=4048
    "v1": {"temperature": 0.3, "max_tokens": 4000},  # 时间线: Markdown报告，训练数据max=1983，留余量
}

# CORS（开发环境开放，生产环境需限制）
CORS_ORIGINS = ["*"]
