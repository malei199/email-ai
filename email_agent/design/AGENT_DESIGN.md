# 邮件智能助手 Agent 设计文档

> 状态：已确认  
> 版本：V1.0  
> 日期：2026-04-26

---

## 1. 产品定位

面向服装跟单团队的内部智能助手，基于双轨RAG + 知识图谱 + 微调模型，提供：
- **被动问答**：术语翻译、款号进度查询、延期分析
- **主动推送**：每日上班早汇总（基于昨晚23点更新的数据库）

---

## 2. 用户旅程

```
首次打开
  │
  ▼
输入邮箱号 ──→ 查KG确认身份 ──→ 展示"早安，Paula，负责12个款号"
  │                              │
  ▼                              ▼
长期保持登录                    直接进入早推送页面
  │                              │
  ▼                              ▼
次日打开 ──→ 自动登录 ──→ 展示当日早推送
  │
  ▼
侧边栏操作 / 对话输入 / 反馈点赞点踩
```

---

## 3. 页面布局（布局B：侧边栏 + 主对话）

```
┌─────────────────────────────────────────────────────────────┐
│  🏠 服装智能助手                              [Paula ▼] [退出] │
├────────────┬────────────────────────────────────────────────┤
│            │                                                │
│ ▼ 今日汇总  │   [早推送内容 / 对话内容]                       │
│   (早推送)  │                                                │
│            │   [AI] 早安，Paula。今日概览：                   │
│            │        负责12个款号                             │
│            │        ⚠️ 2个延期风险...                        │
│            │        [查看详情 →]                             │
│            │                                                │
│ ▼ 我负责的  │   [User] CCSS230021进度                        │
│   ⭐ AW..   │                                                │
│   ⭐ CC..   │   [AI] 当前阶段：封样确认                       │
│     IN..    │        最新事件：5/15 客人确认 Lab Dip          │
│     ...     │        [来源：3封相关邮件 ▼]                    │
│            │                                                │
│ ▼ 历史会话  │   [User] 那这款会延期吗                        │
│   今天      │                                                │
│   ├─CC..   │   [AI] 分析：当前无延期记录...                   │
│   昨天-AW.. │        [简洁 | 详细]                            │
│   前天-CC.. │                                                │
│   4/24...  ├────────────────────────────────────────────────┤
│            │  [简洁 ▼] [输入框...]              [发送]       │
│            │                                                │
└────────────┴────────────────────────────────────────────────┘
```

### 3.1 侧边栏规范

| 区块 | 内容 | 交互 |
|------|------|------|
| **今日汇总** | 早推送完整内容，固定置顶 | 点击展开/折叠 |
| **我负责的** | KG查询出的款号列表 + 用户备注名 + 置顶标记 | 点击款号快速发起对话；长按/右键编辑备注、置顶/取消 |
| **历史会话** | 按日期分组，每组内按款号/主题聚合 | 点击恢复会话；超过2天显示完整时间 |

### 3.2 历史会话标题格式

```
今天
  ├─ CCSS230021 进度查询
  └─ 拉链英文怎么说
昨天-AW25-KFWTS101
  └─ 延期分析
前天-CCSS230021
  └─ 面料确认
4月24日15:33-INDOT27551
  └─ 出货安排
```

- **今天/昨天/前天**：自然语言日期
- **超过2天**：`M月D日HH:MM-款号` 或 `M月D日HH:MM-首句前10字`
- **无款号查询**（如术语翻译）：用首句前10字作为标题

---

## 4. 数据库Schema（SQLite）

### 4.1 用户表（users）

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,       -- 邮箱号，登录标识
    name        TEXT,                        -- 从KG匹配到的人员名
    kg_matched  BOOLEAN DEFAULT 0,           -- 是否成功匹配KG
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login  TIMESTAMP
);
```

### 4.2 会话表（sessions）

```sql
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    title       TEXT,                        -- 显示标题（款号或首句前10字）
    style_id    TEXT,                        -- 关联款号（如有）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.3 消息表（messages）

```sql
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,               -- 消息内容（Markdown）
    mode        TEXT DEFAULT 'detailed',     -- 'concise' | 'detailed'
    sources     TEXT,                        -- JSON数组：数据来源（术语/事件/邮件）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.4 款号备注表（style_notes）

```sql
CREATE TABLE style_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    style_id    TEXT NOT NULL,
    alias       TEXT,                        -- 备注名（如"秋冬外套-大客户"）
    is_pinned   BOOLEAN DEFAULT 0,           -- 是否置顶
    sort_order  INTEGER DEFAULT 0,           -- 排序权重
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, style_id)
);
```

### 4.5 反馈表（feedback）

```sql
CREATE TABLE feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    rating      INTEGER CHECK(rating IN (-1, 1)),  -- 1=👍, -1=👎
    comment     TEXT,                                -- 可选文字反馈
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.6 早推送记录表（morning_pushes）

```sql
CREATE TABLE morning_pushes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    push_date   DATE NOT NULL,               -- 推送日期
    content     TEXT NOT NULL,               -- 推送内容（Markdown）
    risk_count  INTEGER DEFAULT 0,           -- 风险款号数
    event_count INTEGER DEFAULT 0,           -- 新增事件数
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, push_date)
);
```

---

## 5. 核心API接口

### 5.1 认证

```
POST /api/auth/login
  Body: { "email": "paula@example.com" }
  Response: { "user_id": 1, "name": "Paula Cheng", "styles": ["CCSS230021", ...] }

POST /api/auth/logout
  Header: Authorization: Bearer <token>
```

### 5.2 早推送

```
GET /api/morning-push
  Header: Authorization: Bearer <token>
  Response: {
    "date": "2026-04-26",
    "greeting": "早安，Paula",
    "summary": {
      "total_styles": 12,
      "risk_count": 2,
      "event_count": 5
    },
    "risks": [
      { "style_id": "CCSS230021", "alias": "秋冬外套", "reason": "面料延期3天" },
      { "style_id": "INDOT27551", "alias": null, "reason": "7天无更新" }
    ],
    "events": [
      { "style_id": "AW25-KFWTS101", "alias": "春夏T恤", "event": "Lab Dip已确认" }
    ],
    "content": "# 早安，Paula..."  -- Markdown完整内容
  }
```

### 5.3 对话（SSE流式）

```
POST /api/chat
  Header: Authorization: Bearer <token>
         Content-Type: application/json
  Body: {
    "session_id": 123,           -- 可选，空则新建会话
    "message": "CCSS230021进度",
    "mode": "detailed"           -- "concise" | "detailed"
  }
  
  Response: SSE Stream
    event: thinking
    data: { "step": "intent_recognition", "detail": "识别为进度查询" }
    
    event: tool_call
    data: { "tool": "kg_query", "params": { "query": "timeline", "param": "CCSS230021" } }
    
    event: delta
    data: { "content": "当前阶段" }
    
    event: delta
    data: { "content": "：封样确认" }
    
    event: done
    data: {
      "message_id": 456,
      "content": "当前阶段：封样确认...",
      "sources": [
        { "type": "kg", "query": "timeline", "style_id": "CCSS230021" },
        { "type": "rag", "collection": "email_events_new", "count": 3 }
      ],
      "mode": "detailed"
    }
```

### 5.4 款号备注管理

```
GET /api/styles                  -- 获取我负责的款号列表（KG + 用户备注合并）
PUT /api/styles/:style_id        -- 更新备注名/置顶状态
  Body: { "alias": "秋冬外套", "is_pinned": true }
```

### 5.5 反馈

```
POST /api/feedback
  Body: { "message_id": 456, "rating": 1, "comment": "" }
```

### 5.6 历史会话

```
GET /api/sessions?page=1&size=20
GET /api/sessions/:id/messages
```

---

## 6. 对话状态机

```
用户输入
  │
  ▼
[Step 1: 意图识别]  ← 当前会话上下文（款号指代继承）
  │
  ├── 术语/翻译查询 ──→ [术语RAG] ──→ [回答组装] ──→ 输出
  │
  ├── 款号进度查询 ──→ [V3调度器]
  │                       │
  │                       ├── 简单状态 ──→ [KG查询: timeline] ──→ [回答组装]
  │                       │
  │                       ├── 需详细分析 ──→ [V1模型: 时间线推理] ──→ [回答组装]
  │                       │
  │                       └── 需多轮确认 ──→ [V2模型: 多轮工具调用] ──→ [回答组装]
  │
  ├── 人员/工厂/客户查询 ──→ [KG查询] ──→ [回答组装]
  │
  ├── 延期分析 ──→ [KG + RAG联合查询] ──→ [V1模型分析] ──→ [回答组装]
  │
  └── 闲聊/越界 ──→ [直接回答/拒绝]
```

### 6.1 上下文继承规则

| 场景 | 行为 |
|------|------|
| 首句含款号 | 提取款号，绑定到当前会话 |
| 首句无款号，但会话已绑定款号 | 继承会话款号 |
| 首句无款号，会话未绑定 | 意图识别后判断是否需要追问款号 |
| 用户说"那款""这个""它" | 指代解析 → 继承会话款号 |

---

## 7. 早推送生成逻辑

```python
def generate_morning_push(user_email: str, push_date: date) -> dict:
    # 1. 查用户身份
    person = kg_query_engine.get_person_by_email(user_email)
    
    # 2. 查负责的款号列表
    styles = kg_query_engine.get_styles_by_person(person["name"])
    
    # 3. 对每个款号分析风险
    risks = []
    events = []
    for style in styles:
        # 风险1: 已延期
        timeline = kg_query_engine.get_timeline(style["style_id"])
        delay_events = [e for e in timeline if e.get("delay_days", 0) > 0]
        if delay_events:
            risks.append({
                "style_id": style["style_id"],
                "reason": f"已延期{delay_events[-1]['delay_days']}天"
            })
        
        # 风险2: 长时间无更新
        last_update = kg_query_engine.get_last_update(style["style_id"])
        if last_update["days_since_update"] > 7:
            risks.append({
                "style_id": style["style_id"],
                "reason": f"{last_update['days_since_update']}天无更新"
            })
        
        # 风险3: 延期风险（来自邮件内容分析）
        # 需要email_rag_pipeline的事件字段支持risk_flag
        recent_events = rag_query(style["style_id"], days=7)
        for e in recent_events:
            if e.get("risk_flag"):  # 邮件内容中识别出的风险信号
                risks.append({
                    "style_id": style["style_id"],
                    "reason": e["risk_description"]
                })
        
        # 收集昨日新增事件（23点更新后的数据）
        new_events = [e for e in recent_events if e["date"] == push_date - 1 day]
        events.extend(new_events)
    
    # 4. 组装推送内容
    return assemble_push(person["name"], styles, risks, events)
```

---

## 8. 目录结构

```
email_agent/
├── README.md
├── requirements.txt
├── main.py                    # FastAPI入口
├── config.py                  # 配置（数据库路径、模型路径、KG/RAG连接）
├── database.py                # SQLAlchemy ORM + 数据库初始化
├── models/                    # Pydantic模型
│   ├── auth.py
│   ├── chat.py
│   ├── morning_push.py
│   └── style.py
├── routers/                   # API路由
│   ├── auth.py
│   ├── chat.py
│   ├── morning_push.py
│   ├── styles.py
│   ├── feedback.py
│   └── sessions.py
├── services/                  # 业务逻辑
│   ├── auth_service.py
│   ├── chat_service.py        # 对话状态机 + 流式输出
│   ├── morning_push_service.py
│   ├── style_service.py
│   └── feedback_service.py
├── agents/                    # Agent核心
│   ├── intent_router.py       # 意图识别 + V3调度
│   ├── term_agent.py          # 术语RAG问答
│   ├── timeline_agent.py      # 时间线查询（KG + V1）
│   ├── multi_round_agent.py   # 多轮工具调用（V2）
│   └── answer_builder.py      # 回答组装（简洁/详细模式）
├── static/                    # 前端静态文件
│   ├── index.html
│   ├── css/
│   └── js/
└── design/
    └── AGENT_DESIGN.md        # 本文件
```

---

## 9. 与下游系统的调用关系

```
email_agent/
  │
  ├──→ email_kg_pipeline/src/kg_query.py        (KG查询：人员、款号、时间线)
  │
  ├──→ email_term_rag_pipeline/src/rag_qa.py    (术语RAG：翻译、解释)
  │
  ├──→ vector_db/                                (ChromaDB：邮件事件检索)
  │      ├── email_events_new
  │      └── email_events
  │
  ├──→ email_finetuning_pipeline/rlhf/outputs/   (V1/V2/V3 LoRA模型)
  │      ├── v1-policy/      (时间线推理)
  │      ├── v2-policy/      (多轮工具调用)
  │      └── v3-policy/      (调度器)
  │
  └──→ email_rag_pipeline/output/new/            (事件JSON，备用数据源)
         └── events_passed.json
```

---

## 10. 待明确事项（实现阶段决策）

| 事项 | 当前状态 | 建议 |
|------|---------|------|
| `risk_flag` 字段 | email_rag_pipeline事件Schema中暂无 | V1先不做风险3，仅做风险1+2 |
| V1/V2/V3模型加载 | 需要确认LoRA路径和加载方式 | 实现时与email_finetuning_pipeline对齐 |
| 用户邮箱与KG人员匹配 | KG中人员节点是否有email字段？ | 实现时检查kg_query.py的返回结构 |
| 定时任务触发 | 23点跑pipeline是已有cron？ | 复用现有机制，Agent只负责"读取已更新数据" |
| 前端框架 | Vue3 vs 纯HTML+JS | 建议纯HTML+JS + SSE，最小依赖 |

---

## 11. 实现优先级

| 阶段 | 内容 | 预估工作量 |
|------|------|-----------|
| P0 | 数据库Schema + 基础API（登录、早推送、对话非流式） | 2天 |
| P1 | SSE流式对话 + 意图路由 + 术语RAG接入 | 2天 |
| P2 | KG查询接入 + V1/V2/V3模型接入 | 3天 |
| P3 | 简洁/详细模式 + 来源溯源卡片 + 反馈 | 1天 |
| P4 | 款号备注/置顶 + 历史会话 + 侧边栏交互 | 2天 |
| P5 | 前端UI美化 + 测试 + 调优 | 2天 |

**总计：约12个工作日**
