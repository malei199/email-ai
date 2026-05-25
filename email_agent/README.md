# 邮件智能助手 (Email Agent)

面向服装跟单团队的内部智能助手 Web 应用，基于 **vLLM + 多 LoRA 微调模型 + 双轨 RAG + 知识图谱**。

---

## 功能特性

- **每日早推送**：上班时自动展示负责款号的风险提醒和昨日动态
- **对话式查询**：术语翻译、款号进度、延期分析、人员查询
- **深度个性化**：基于邮箱号关联 KG 人员数据，展示"我负责的款号"
- **来源溯源**：每个回答附带数据来源（KG 查询 / RAG 检索 / 术语库）
- **反馈机制**：👍/👎 点赞点踩，数据回流优化
- **分页续查**：查询结果过多时自动截断，支持"继续"、"剩下的"等续查指令

---

## 快速开始

### 1. 环境准备

确保 vLLM 服务已启动（单实例多 LoRA 模式）：

```bash
vllm serve <base_model_path> \
  --enable-lora \
  --lora-modules v3=<v3_lora_path> v2=<v2_lora_path> v1=<v1_lora_path> \
  --max-lora-rank 64 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --port 8001
```

### 2. 配置

编辑 `email_agent/config.py`：

```python
VLLM_BASE_URL = "http://localhost:8001/v1"  # 你的 vLLM 地址
```

### 3. 安装依赖

```bash
pip install -r email_agent/requirements.txt
```

### 4. 启动服务

```bash
python -m email_agent.main
# 或
uvicorn email_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后访问 http://localhost:8000

### 5. 首次使用

1. 输入邮箱号登录
2. 系统自动匹配 KG 人员数据，展示"我负责的款号"
3. 查看今日早推送
4. 在对话区输入问题

---

## 技术架构

```
email_agent/
├── main.py                    # FastAPI 入口
├── config.py                  # 全局配置（vLLM 地址、模型参数、system prompt）
├── database.py                # SQLite ORM（含 OmittedData 续查表）
├── HISTORY_DESIGN.md          # 分页续查架构设计
├── API_REFERENCE.md           # 本地查询接口总览
├── models/                    # Pydantic 模型
│   ├── auth.py                # 登录/用户相关
│   ├── chat.py                # 对话/会话相关
│   ├── feedback.py            # 反馈相关
│   ├── morning_push.py        # 早推送相关
│   └── style.py               # 款号备注相关
├── routers/                   # API 路由
│   ├── auth.py                # 登录/退出/当前用户
│   ├── morning_push.py        # 早推送
│   ├── chat.py                # SSE 流式对话 + 续查端点
│   ├── styles.py              # 款号备注管理
│   ├── feedback.py            # 反馈
│   └── sessions.py            # 历史会话
├── services/                  # 业务逻辑
│   ├── auth_service.py        # 认证服务（UUID Token）
│   ├── morning_push_service.py # 早推送生成
│   ├── kg_adapter.py          # KG 查询封装（12 个接口）
│   ├── rag_adapter.py         # RAG 查询封装（术语 RAG + 邮件事件 RAG）
│   ├── vllm_client.py         # vLLM OpenAI API 客户端（v1/v2/v3）
│   ├── v2_executor.py         # V2 function_calls 执行引擎（查询链 + result 过滤）
│   ├── v1_model_adapter.py    # V1 模型适配器（Markdown 报告生成）
│   ├── query_orchestrator.py  # 联合查询编排器（5 类路由 + 歧义消解）
│   ├── answer_generator.py    # V2 回答生成器（模板化 Markdown）
│   ├── context_manager.py     # Token 估算与上下文管理
│   └── result_truncator.py    # 结果截断工具（6 种策略 + 续查支持）
├── agents/                    # Agent 核心
│   ├── intent_router.py       # V3 意图路由（基于微调模型 + 续查关键词检测）
│   ├── chat_agent.py          # 对话主入口（V1/V2/续查/直接回答）
│   ├── v1_orchestrator.py     # V1 外部编排器（多轮事件→Markdown 合并）
│   ├── v2_orchestrator.py     # V2 多轮查询编排器（messages 列表格式）
│   └── answer_builder.py      # 回答组装器（简洁/详细模式）
├── test/                      # 测试
│   ├── run_all_tests.py
│   ├── test_integration.py
│   ├── test_kg_adapter.py
│   ├── test_query_orchestrator.py
│   └── test_rag_adapter.py
└── static/                    # 前端文件
    ├── index.html
    ├── css/style.css
    └── js/app.js
```

---

## 三模型协作架构

```
用户提问
  ↓
V3 调度器 (v3 LoRA)
  ├── decision: "direct_answer" → 直接回答
  ├── decision: "route_v1"     → V1 时间线分析（有款号）
  └── decision: "route_v2"     → V2 多轮查询（无款号/复杂查询）
  ↓
分支 1：route_v1
  V1 编排器 → 查 ChromaDB → 分轮调 V1 → 合并 Markdown 报告

分支 2：route_v2
  V2 编排器 → 多轮交互循环
    Round 1：V2 输出 function_calls → 执行查询 → [截断] → 累积上下文
    Round 2：V2 输出 function_calls → 执行查询 → [截断] → 累积上下文
    ...
    Round N：V2 输出 generate_answer → 生成 Markdown 回答

分支 3：continuation（续查）
  检测"继续"/"剩下的" → 查 OmittedData → 截取下一页 → 直接返回
```

| 模型 | 职责 | 输入 | 输出 | max_tokens |
|------|------|------|------|-----------|
| **V3** | 意图调度 | 用户问题 | `{"decision": "route_v1/v2/direct_answer", ...}` | 300 |
| **V2** | 查询策略 | 用户问题 + 历史查询结果 | `{"thought": "...", "satisfied": false/true, "function_calls": [...]}` | 8000 |
| **V1** | 时间线分析 | 款号事件列表 | Markdown 报告 | 4000 |

---

## 下游系统依赖

| 系统 | 用途 |
|------|------|
| `email_kg_pipeline` | 人员-款号关联、时间线查询 |
| `email_term_rag_pipeline` | 术语翻译/解释 |
| `email_rag_pipeline` | 邮件事件检索（events_passed.json） |
| `vector_db/` | ChromaDB 共享向量数据库 |

---

## 配置说明

编辑 `email_agent/config.py`：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `VLLM_BASE_URL` | vLLM 服务地址 | `https://potato-v3.gear-c1.openbayes.net/v1/` |
| `VLLM_API_KEY` | vLLM API 密钥 | `dummy` |
| `VLLM_MODELS` | vLLM 中注册的 LoRA 名称映射 | `{"v3": "v3", "v2": "v2", "v1": "v1"}` |
| `DATABASE_URL` | SQLite 数据库路径 | `email_agent/agent.db` |
| `VECTOR_DB_PATH` | ChromaDB 路径 | `vector_db/` |
| `KG_GRAPH_PATH` | 知识图谱文件 | `email_kg_pipeline/output/kg_graph_with_customers.pkl` |
| `KG_EVENTS_PATH` | 事件 JSON 文件 | `email_rag_pipeline/output/new/events_passed.json` |
| `MORNING_PUSH_HOUR` | 早推送生成时间 | 8 |
| `STALE_DAYS` | 静默风险阈值 | 7 |
| `SESSION_TIMEOUT_DAYS` | 会话过期天数 | 30 |
| `MODEL_PATHS` | V1/V2/V3 LoRA 本地路径 | 见 config.py |
| `COLLECTIONS` | ChromaDB Collection 名称 | `clothing_terms`, `email_events_new`, `email_events` |
| `CORS_ORIGINS` | CORS 允许来源 | `["*"]` |

### 模型参数

| 模型 | temperature | max_tokens | 说明 |
|------|-------------|-----------|------|
| V3 | 0.1 | 300 | 调度器，JSON 决策 |
| V2 | 0.3 | 8000 | 查询策略，JSON + function_calls |
| V1 | 0.3 | 4000 | 时间线，Markdown 报告 |

---

## 数据库 Schema

| 表名 | 说明 |
|------|------|
| `users` | 用户（邮箱、姓名、KG 匹配状态、最后登录时间） |
| `sessions` | 会话（标题、关联款号、续查状态：omitted_data_id / truncation_current_page / truncation_page_size） |
| `messages` | 消息（角色、内容、模式、来源） |
| `omitted_data` | **被截断数据存储**（conversation、remaining_data、original_count、query_type、created_at、updated_at） |
| `style_notes` | 款号备注（别名、置顶、排序权重） |
| `morning_pushes` | 早推送记录 |
| `feedback` | 反馈（点赞点踩、可选文字评论） |

### OmittedData 续查表

```python
class OmittedData(Base):
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    conversation = Column(Text)      # JSON: user_query, v2_thought, function_calls
    remaining_data = Column(Text)    # JSON: 当前剩余数据（每次续查覆盖更新）
    original_count = Column(Integer) # 首次查询总数量
    query_type = Column(String)      # 如 "kg_query.my_styles"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 登录（返回 token + 用户信息 + 款号列表） |
| `/api/auth/logout` | POST | 退出 |
| `/api/auth/me` | GET | 当前用户 |
| `/api/morning-push` | GET | 获取今日早推送 |
| `/api/chat` | POST | SSE 流式对话 |
| `/api/chat/continue` | POST | **续查**（"继续"/"剩下的"） |
| `/api/chat/history/{session_id}` | GET | 会话历史（含完整 session_flow） |
| `/api/styles` | GET | 我负责的款号列表（KG + 用户备注合并） |
| `/api/styles/{id}` | PUT | 更新款号备注（别名/置顶） |
| `/api/feedback` | POST | 提交反馈（👍/👎 + 可选评论） |
| `/api/sessions` | GET | 历史会话列表（分页） |
| `/api/sessions/{id}/messages` | GET | 会话消息 |
| `/api/health` | GET | 健康检查 |

---

## 分页续查设计

**核心原则**：续查 = 将 omitted_data 的内容转移到 session 中

```
首次查询：253 个款号
    → session 显示：15 个
    → OmittedData.remaining_data 存储：238 个

用户："继续"
    → 查 OmittedData（238 个）
    → ResultTruncator 截取 → 输出 15 个
    → OmittedData.remaining_data 更新：223 个（覆盖）

...直到 remaining_data 为空
```

**数据守恒**：session 累计显示 + OmittedData.remaining_data = 原始总数

---

## Session 流程设计

```
用户提问
  ↓
【chat.py - Session 管理】
  创建/获取 session
  记录 user_message 到 Message 表
  ↓
V3 路由 (intent_router.py)
  输入：user_message
  输出：{"decision": "route_v1/route_v2/continuation/direct_answer", ...}
  ↓
【chat.py - Session 记录】
  记录 V3 输出到 Message 表
  ↓
分支 1：route_v1
  V1 编排器 → 查 ChromaDB → 分轮调 V1 → Markdown 报告
  ↓ 记录 V1 输出 + assistant 回答到 Message 表

分支 2：route_v2
  V2 编排器 → 多轮交互
    → 每轮：V2 输出 → 执行查询 → [ContextManager 截断] → 累积上下文
    → 最终：generate_answer → Markdown 回答
  ↓ 记录 V2 输出、tool 返回、assistant 回答到 Message 表
  ↓ [如有截断] 保存 OmittedData

分支 3：continuation
  查 session.omitted_data_id → 读 OmittedData.remaining_data
  → ResultTruncator 截取下一页
  → 直接返回（不调用模型）
  → 更新 OmittedData.remaining_data（覆盖）
  ↓ 记录 user + assistant 到 Message 表
```

### Session 记录内容示例

```json
{
  "session_id": "uuid-123",
  "messages": [
    {"role": "user", "content": "我跟的款号进度怎么样"},
    {"role": "v3", "content": "{\"decision\": \"route_v2\"}"},
    {"role": "v2", "content": "{\"thought\": \"...\", \"satisfied\": false, \"function_calls\": [...]}"},
    {"role": "tool", "content": "[工具返回] {\"styles\": [...]}"},
    {"role": "v2", "content": "{\"thought\": \"...\", \"satisfied\": true, \"function_calls\": [{\"name\": \"generate_answer\"}]}"},
    {"role": "assistant", "content": "共查询到 5 个款号：..."}
  ]
}
```

---

## 组件实现状态

### 已完整实现

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| FastAPI 应用 + SSE 流式 | `main.py`, `routers/chat.py` | ✅ | 完整 SSE 对话 + 续查端点 |
| vLLM 客户端 | `services/vllm_client.py` | ✅ | 三模型统一调用，支持 messages 列表格式 |
| V3 意图路由 | `agents/intent_router.py` | ✅ | 基于微调模型 + 续查关键词检测 |
| V2 多轮编排 | `agents/v2_orchestrator.py` | ✅ | messages 列表格式，与训练数据一致 |
| V1 编排器 | `agents/v1_orchestrator.py` | ✅ | 多轮事件查询 → V1 分析 → Markdown 合并 |
| V1 模型适配器 | `services/v1_model_adapter.py` | ✅ | 调用本地 V1 LoRA 生成报告 |
| V2 执行引擎 | `services/v2_executor.py` | ✅ | 查询链（一级+二级）、result 字段过滤、并行执行 |
| 查询编排器 | `services/query_orchestrator.py` | ✅ | 5 类查询路由 + 歧义消解 |
| 回答生成器 | `services/answer_generator.py` | ✅ | 模板化 Markdown 生成 |
| 上下文管理 | `services/context_manager.py` | ✅ | Token 估算、溢出检测、[上下文警告] |
| 结果截断 | `services/result_truncator.py` | ✅ | 6 种策略、9 种规则、omitted_data 存储 |
| 续查处理 | `routers/chat.py` | ✅ | `_handle_continuation_stream` + `/api/chat/continue` |
| KG 适配器 | `services/kg_adapter.py` | ✅ | 12 种 KG 查询函数 |
| RAG 适配器 | `services/rag_adapter.py` | ✅ | 术语 RAG + 邮件事件 RAG |
| Session 管理 | `database.py`, `routers/sessions.py` | ✅ | SQLite ORM + 分页续查字段 |
| 认证系统 | `routers/auth.py`, `services/auth_service.py` | ✅ | UUID Token 存储 |
| 早推送 | `routers/morning_push.py`, `services/morning_push_service.py` | ✅ | 每日风险提醒 |
| 前端页面 | `static/` | ✅ | 登录页/主界面/对话/SSE 处理 |

---

## 参考文档

- `email_agent/HISTORY_DESIGN.md` — 分页续查架构设计
- `email_agent/API_REFERENCE.md` — 本地查询接口总览（KG/RAG/编排器/截断器）
- `email_agent/design/AGENT_DESIGN.md` — Agent 设计文档（产品定位、用户旅程、页面布局）
- `email_finetuning_pipeline/TIMELINE_FINETUNE_DESIGN.md` — V1 时间线微调设计

---

*最后更新：2026-05-13*
