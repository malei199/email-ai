# Session History 与分页续查设计方案

## 背景

用户查询时，查询结果可能超过模型上下文窗口，需要进行截断。截断后用户可能说"剩下的呢"、"还有吗"等续查语句，需要从被截断的数据中继续输出。

## 核心设计原则

**续查 = 将 omitted_data 的内容转移到 session 中**

每次续查时：
- 从 `omitted_data` 读取剩余数据
- 调用截断工具重新计算信息密度
- 将截断后的数据输出到 session
- 更新 `omitted_data` 为剩余数据（覆盖）

**总数据守恒：**
```
首次查询：253个款号
    → session 显示：10个
    → omitted_data 存储：243个

第2轮续查：
    → 从 omitted_data 取 243个 → 截断工具计算 → 输出8个到 session
    → session 累计显示：18个
    → omitted_data 更新：235个

第3轮续查：
    → 从 omitted_data 取 235个 → 截断工具计算 → 输出12个到 session
    → session 累计显示：30个
    → omitted_data 更新：223个

...

最后一轮：
    → omitted_data 更新：0个
    → session 累计显示：253个
```

---

## 数据结构设计

### 1. 截断上下文包 (TruncationContext)

```python
@dataclass
class TruncationContext:
    # 对话信息（触发截断时的完整上下文，首次查询时生成，续查时不变）
    conversation: Dict
    # {
    #     "user_query": "我跟的款号有哪些",
    #     "v2_thought": "用户查询自己的款号列表",
    #     "v2_function_calls": [{"name": "kg_query.my_styles", "params": {}}],
    #     "query_result_summary": {"total": 253, "truncated_to": 15},
    #     "timestamp": "2026-05-09T14:30:00"
    # }
    
    # 数据部分
    displayed_data: List[Dict]      # 当前显示的数据（截断后）
    omitted_data: List[Dict]        # 被截断的数据（完整列表）
    
    # 分页状态
    current_page: int = 0           # 当前显示到第几页
    page_size: int = 15
    total_pages: int = 0
```

### 2. 对话信息 (Conversation)

触发截断时的完整对话上下文，包含：

| 字段 | 说明 | 示例 |
|------|------|------|
| `user_query` | 用户原始问题 | "我跟的款号有哪些" |
| `v2_thought` | V2 模型的思考过程 | "用户查询自己的款号列表" |
| `v2_function_calls` | V2 调用的工具 | `[{"name": "kg_query.my_styles", "params": {}}]` |
| `query_result_summary` | 查询结果摘要 | `{"total": 253, "truncated_to": 15}` |
| `timestamp` | 截断时间 | "2026-05-09T14:30:00" |

---

## 数据库设计

### 1. `sessions` 表（新增字段）

```python
class Session(Base):
    # ... 现有字段 ...
    
    # 关联当前活动的 omitted_data
    omitted_data_id = Column(Integer, ForeignKey("omitted_data.id"))
    
    # 分页状态
    truncation_current_page = Column(Integer, default=0)
    truncation_page_size = Column(Integer, default=15)
```

**设计说明：**
- `omitted_data_id`：关联当前活动的 omitted_data（新查询时更新）
- `truncation_current_page`：当前显示到第几页（续查时递增）
- `truncation_page_size`：每页大小（由截断工具动态计算，可能变化）

### 2. `omitted_data` 表（新建）

```python
class OmittedData(Base):
    __tablename__ = "omitted_data"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    
    # 对话信息（首次查询的上下文，不变）
    conversation = Column(Text)       # JSON：user_query, v2_thought, function_calls, timestamp
    
    # 当前剩余数据（每次截取后覆盖更新，逐渐减少）
    remaining_data = Column(Text)     # JSON：当前剩余的完整列表
    
    # 元信息
    original_count = Column(Integer)      # 首次查询的总数量
    query_type = Column(String)           # 查询类型，如 "kg_query.my_styles"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
```

**设计说明：**
- `conversation`：首次查询时生成，续查时不变（用于确认上下文）
- `remaining_data`：每次续查后覆盖更新，逐渐减少
- 一个 session 可以有多个 omitted_data（多次查询），但 session 只关联最近的一个
- 续查时通过 `session.omitted_data_id` 找到当前活动的 omitted_data

---

## 续查流程

```
用户输入："剩下的呢"
    ↓
[1] 检测续查意图（intent_router 或 chat_agent）
    ↓
[2] 查 session → 获取 omitted_data_id
    SELECT omitted_data_id FROM sessions WHERE id = ?
    ↓
[3] 查 omitted_data → 获取 remaining_data
    SELECT remaining_data, conversation FROM omitted_data WHERE id = ?
    ↓
[4] 确认上下文（可选）
    检查 conversation.user_query 是否与当前 session 匹配
    ↓
[5] 调用截断工具（输入 remaining_data）
    truncator = ResultTruncator()
    result = truncator.truncate(
        raw_result=remaining_data,
        query_type=omitted_data.query_type,
        user_intent="overview",
        original_query=omitted_data.conversation["user_query"],
        conversation=omitted_data.conversation,
    )
    ↓
[6] 更新数据
    - session：
        truncation_current_page += 1
        # 累计显示数据由前端或业务层维护
    - omitted_data：
        remaining_data = result.omitted_data（覆盖更新）
        updated_at = now()
    ↓
[7] 返回 result.displayed_data（不调模型，直接输出）
```

---

## 关键设计决策

### 1. 为什么 omitted_data 每次更新（覆盖）？

- 续查时从 omitted_data 取数据，截断后放回
- omitted_data 的内容在减少，session 的内容在增加
- 总数据守恒：session 增加 = omitted_data 减少

### 2. 为什么截断工具每次都要调用？

- 每次续查时上下文不同（剩余数据量变化）
- 信息密度可能不同（剩余数据的分布变化）
- 截断工具根据当前上下文动态计算输出数量
- 不是固定切片（如每次10个），而是动态计算

### 3. 为什么 session 只关联一个 omitted_data？

- 用户通常只关心最近一次查询的续查
- 新查询时更新 `session.omitted_data_id`
- 简化状态管理

### 4. 新查询后说"继续"，找哪个 omitted_data？

```
第1轮：查询A → omitted_data_A (243个)
    → session.omitted_data_id = A

第2轮：继续A → omitted_data_A (235个)
    → session.omitted_data_id = A（不变）

第3轮：查询B（新问题）→ omitted_data_B (50个)
    → session.omitted_data_id = B（更新）

第4轮：继续 → 找 omitted_data_B (50个)
    → session.omitted_data_id = B
```

**设计：** 新查询创建新的 omitted_data，更新 `session.omitted_data_id`。续查时总是找 `session.omitted_data_id` 指向的 omitted_data。

---

## 代码修改清单

### 1. 截取工具 (result_truncator.py)

- `TruncationResult` 增加 `conversation` 字段
- `truncate()` 方法接收 `conversation` 参数
- 所有采样策略返回完整的 `omitted_data`

### 2. 数据库 (database.py)

- `Session` 表新增 `omitted_data_id`、`truncation_current_page`、`truncation_page_size`
- 新建 `OmittedData` 表

### 3. V2 执行引擎 (v2_executor.py)

- 调用截取工具时传入完整对话信息
- 新建 `OmittedData` 记录
- 更新 `session.omitted_data_id`

### 4. Chat Agent (chat_agent.py)

- 检测续查意图
- 查询 `session.omitted_data_id`
- 读取 `omitted_data.remaining_data`
- 调用截断工具
- 更新 `omitted_data.remaining_data`（覆盖）
- 返回截断结果（不调模型）

### 5. Intent Router (intent_router.py)

- 识别续查关键词（"剩下的"、"还有吗"、"继续"等）
- 返回 `continuation` 意图

---

## 续查关键词

```python
CONTINUATION_KEYWORDS = [
    "剩下的", "还有吗", "继续", "然后呢", "接着",
    "下一页", "更多", "其余的", "未完",
]
```

---

## 示例

### 第1轮：正常查询

```
用户：我跟的款号有哪些

V2 调用：kg_query.my_styles
查询结果：253 条
截断后显示：10 条（按阶段采样）

数据库存储：
- sessions.omitted_data_id = 1
- sessions.truncation_current_page = 0
- sessions.truncation_page_size = 10

- omitted_data.id = 1
- omitted_data.conversation = {
    "user_query": "我跟的款号有哪些",
    "v2_thought": "用户查询自己的款号列表",
    "v2_function_calls": [{"name": "kg_query.my_styles", "params": {}}],
    "query_result_summary": {"total": 253, "truncated_to": 10},
    "timestamp": "2026-05-09T14:30:00"
  }
- omitted_data.remaining_data = [243条JSON]（完整列表）
- omitted_data.original_count = 253
- omitted_data.query_type = "kg_query.my_styles"

系统回答：显示10条款号列表 + "共253条，显示10条（按阶段采样）"
```

### 第2轮：续查

```
用户：剩下的呢

检测：续查意图
查找：session.omitted_data_id = 1
获取：omitted_data.remaining_data（243条）

调用截断工具：
    输入：243条
    计算信息密度 → 输出8条
    剩余：235条

更新：
- sessions.truncation_current_page = 1
- omitted_data.remaining_data = [235条JSON]（覆盖更新）

系统回答：显示8条款号列表
```

### 第3轮：继续续查

```
用户：还有吗

检测：续查意图
查找：session.omitted_data_id = 1
获取：omitted_data.remaining_data（235条）

调用截断工具：
    输入：235条
    计算信息密度 → 输出12条
    剩余：223条

更新：
- sessions.truncation_current_page = 2
- omitted_data.remaining_data = [223条JSON]（覆盖更新）

系统回答：显示12条款号列表
```

### 第N轮：无更多数据

```
用户：继续

检测：续查意图
查找：session.omitted_data_id = 1
获取：omitted_data.remaining_data（5条）

调用截断工具：
    输入：5条
    计算信息密度 → 输出5条
    剩余：0条

更新：
- sessions.truncation_current_page = 17
- omitted_data.remaining_data = []（空列表）

系统回答：显示最后5条 + "已显示全部253条款号"
```

### 新查询后续查

```
用户：8859114 的时间线

V2 调用：kg_query.timeline
查询结果：50条事件
截断后显示：20条

新建 omitted_data.id = 2
更新 sessions.omitted_data_id = 2

系统回答：显示20条事件

---

用户：继续

检测：续查意图
查找：session.omitted_data_id = 2（指向新的 omitted_data）
获取：omitted_data.remaining_data（30条）

调用截断工具 → 输出15条 → 剩余15条
更新 omitted_data.remaining_data = [15条]

系统回答：显示15条事件
```

---

## 注意事项

1. **session 过期处理**：如果 session 超过 `SESSION_TIMEOUT_DAYS`，清理关联的 `omitted_data`
2. **数据清理**：定期清理 `remaining_data` 为空的 `omitted_data`（已显示完毕）
3. **并发安全**：续查时更新 `remaining_data` 需要事务保护
4. **异常处理**：如果 `omitted_data` 被删除，续查时降级为"数据已过期，请重新查询"
5. **空列表处理**：如果 `remaining_data` 为空，返回"已显示全部内容"

---

## 待实现

- [ ] `result_truncator.py` 增加 conversation 字段
- [ ] `database.py` 新增 `omitted_data` 表和 `session` 字段
- [ ] `v2_executor.py` 保存 truncation context（新建 omitted_data）
- [ ] `intent_router.py` 识别续查意图
- [ ] `chat_agent.py` 续查逻辑（绕过模型，直接读取 omitted_data）
