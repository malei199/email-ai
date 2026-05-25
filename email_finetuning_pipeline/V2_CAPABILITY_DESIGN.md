# V2 能力设计文档（最终版）

> 创建日期：2026-05-01
> 最后更新：2026-05-07
> 状态：已实现，1000 条训练数据已生成（996 验证通过）
> 相关文档：V3_ROUTING_RULES.md, V2_QUESTION_GENERATION_SPEC.md

---

## 一、V2 定位

V2 是**查询策略与满足度判断模型**，本地部署（Qwen2.5-7B + LoRA），不依赖三方服务。

V2 只负责两件事：
1. 根据用户问题和历史查询结果，判断信息是否满足用户需求
2. 输出外部系统调用指令（查询工具或回答生成）

---

## 二、V2 输入

| 场景 | 输入内容 |
|-----|---------|
| 首轮查询 | 用户提问 |
| 后续轮次 | 用户提问 + 以前查询结果（外部系统保证不超出上下文） |

---

## 三、V2 输出（统一格式）

```json
{
  "thought": "判断过程...",
  "satisfied": true | false,
  "function_calls": [
    {
      "name": "xxx",
      "params": {...},
      "result": ["field1", "field2.sub_field"]
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|-----|------|------|------|
| `thought` | string | ✅ | 判断过程，说明为什么选这些工具 |
| `satisfied` | bool | ✅ | 信息是否满足用户需求 |
| `function_calls` | list | ✅ | 要执行的工具调用列表 |
| `function_calls[].name` | string | ✅ | 工具名（kg_query / rag_query / generate_answer） |
| `function_calls[].params` | dict | ✅ | 工具入参，必须包含 `"type": "接口类型"` |
| `function_calls[].result` | list | ✅ | **必填**，指定需要返回的字段，减少数据量 |

**关键原则**：
- 无论 `satisfied` 是 true 还是 false，V2 永远输出 `function_calls`
- V2 自身不生成回答，回答由外部系统的 `generate_answer` 方法生成
- V2 输出格式统一，不区分"查询轮"和"回答轮"
- **`result` 字段**：V2 精确控制"我要什么"，外部系统只返回指定字段，减少上下文占用

### 3.1 `result` 字段设计

V2 通过 `result` 字段声明需要从工具返回中保留的字段，支持点号路径：

```json
// 只返回款号和面料阶段事件
{
  "name": "kg_query",
  "params": {"type": "style_overview", "style_id": "AW25-KFWTS101"},
  "result": ["style_id", "by_category.面料"]
}

// 只返回人员款号列表（不含详情）
{
  "name": "kg_query",
  "params": {"type": "person_styles", "person_name": "Paula Cheng"},
  "result": ["styles.style_id", "total_styles"]
}
```

**规则**：
1. `result` 是**必填的**，训练数据中 100% 使用
2. 外部系统负责解析 `result` 并精简返回
3. V2 在训练数据中学会"按需索取"，减少不必要的数据传输

### 3.2 查询链（一级 + 二级）

V2 可在一个 function_calls 中同时输出**一级查询**（无款号范围查询）和**二级查询**（有款号详情查询）：

```json
{
  "thought": "先获取 Paula Cheng 的款号列表，再查每个款号的面料事件数",
  "satisfied": false,
  "function_calls": [
    {"name": "kg_query", "params": {"type": "person_styles", "person_name": "Paula Cheng"}, "result": ["styles.style_id", "total_styles"]},
    {"name": "kg_query", "params": {"type": "style_overview"}, "result": ["style_id", "by_category.面料"]}
  ]
}
```

**执行语义**（由外部系统处理）：
1. 先执行一级查询 `person_styles`，获取款号列表
2. 外部系统将款号列表**批量展开**到二级查询的 `style_id` 参数
3. 并行执行所有二级查询
4. **合并结果只返回二级数据 + `_meta` 元信息**，一级结果省略以减少上下文占用

**返回格式（查询链）**：
```json
{
  "status": "success",
  "style_overviews": [
    {"style_id": "S1", "by_category": {"面料": [...]}},
    {"style_id": "S2", "by_category": {"面料": [...]}}
  ],
  "_meta": {
    "primary_total": 50,
    "secondary_total": 50,
    "secondary_success": 48,
    "secondary_failed": 2
  }
}
```

**设计理由**：
- 一级结果（款号列表）的唯一作用是提供二级查询的依赖值
- 二级结果本身包含 `style_id`，V2 可以关联到具体款号
- 省略一级结果可大幅减少训练数据中的无效 token 占用

**V2 的职责**：决定"查什么"和"顺序"
**外部系统的职责**：处理依赖、批量展开、并行执行、结果合并、上下文截断

---

## 四、V2 做的 vs V2 不做的

### V2 做的

| 能力 | 说明 |
|-----|------|
| **查询策略生成** | 根据用户问题输出查什么、怎么查 |
| **满足度判断** | 基于当前上下文内信息判断是否满足用户提问 |
| **输出 function_calls** | `satisfied=true` 时调用 `generate_answer`，`satisfied=false` 时调用查询工具 |
| **result 字段控制** | 精确声明需要返回的字段 |

### V2 不做的

| 能力 | 归属 |
|-----|------|
| 分页/截断 | 外部系统 |
| 上下文长度管理 | 外部系统 |
| 续查处理 | 外部系统（绕过 V2） |
| 回答生成 | 外部系统的 `generate_answer` 方法 |

---

## 五、外部系统职责

```
1. 接收 V3 的 route_v2 决策
2. 调用 V2（可能多轮）
   - 每轮执行 V2 的 function_calls
   - 检查结果长度，超出则截断并标记 context_warning
   - 累积结果传给 V2 下一轮
3. V2 satisfied=true 时，执行最后的 generate_answer
4. 返回 Markdown 给用户
5. 续查意图直接绕过 V2
```

---

## 六、多轮交互示例

### 示例 1：正常多轮（使用 result 字段）

```
用户: "我跟的款号进度怎么样"
  ↓
Round 1:
  V2 输入: "我跟的款号进度怎么样"
  V2 输出: {
    "thought": "用户查询我的款号进度，需要先获取款号列表",
    "satisfied": false,
    "function_calls": [
      {"name": "kg_query", "params": {"type": "my_styles"}, "result": ["styles.style_id", "styles.latest_category", "total_styles"]}
    ]
  }
  外部系统执行 → 返回 5 个款号（精简字段）
  ↓
Round 2:
  V2 输入: "我跟的款号进度怎么样" + [5个款号]
  V2 输出: {
    "thought": "已获取5个款号，需要查摘要才能回答进度",
    "satisfied": false,
    "function_calls": [
      {"name": "kg_query", "params": {"type": "style_summaries", "style_ids": [...]}, "result": ["summaries.style_id", "summaries.status", "summaries.current_stage", "summaries.delay_days"]}
    ]
  }
  外部系统执行 → 返回 5 个摘要（精简字段）
  ↓
Round 3:
  V2 输入: "我跟的款号进度怎么样" + [5个款号 + 5个摘要]
  V2 输出: {
    "thought": "已获取所有款号的进度摘要，信息满足用户提问",
    "satisfied": true,
    "function_calls": [
      {"name": "generate_answer", "params": {"template": "my_styles_summary", "data": {"summaries": [...]}}}
    ]
  }
  外部系统生成 Markdown → 返回用户
```

### 示例 2：查询链（一级 + 二级）

```
用户: "Paula Cheng 面料阶段事件数>30的款号"
  ↓
Round 1:
  V2 输出: {
    "thought": "需要：1) Paula Cheng的款号列表 2) 每个款号的面料事件数。先查款号列表，再批量查面料事件",
    "satisfied": false,
    "function_calls": [
      {"name": "kg_query", "params": {"type": "person_styles", "person_name": "Paula Cheng"}, "result": ["styles.style_id", "total_styles"]},
      {"name": "kg_query", "params": {"type": "style_overview"}, "result": ["style_id", "by_category.面料"]}
    ]
  }
  外部系统执行：
    1. 执行一级查询 person_styles → 提取 ["S1", "S2", ..., "S50"]
    2. 批量展开二级查询 → 50 个 style_overview 并行执行
    3. 合并返回（只保留二级结果 + _meta）：
       {"style_overviews": [{"style_id": "S1", "by_category": {"面料": [...]}}, ...], "_meta": {"primary_total": 50, "secondary_success": 48}}
  ↓
Round 2:
  V2 输入: 用户问题 + [48个款号的面料事件数（含_meta）]
  V2 输出: {
    "thought": "已获取所有款号的面料事件数，统计后发现没有超过30个的",
    "satisfied": true,
    "function_calls": [
      {"name": "generate_answer", "params": {"template": "style_list", "data": {"message": "Paula Cheng 的款号中，面料阶段事件数最多的为 XX 个，没有超过30个的款号"}}}
    ]
  }
```

### 示例 3：截断场景

```
用户: "我跟的款号进度怎么样"
  ↓
Round 1:
  V2 输出: kg_query("my_styles")
  外部系统执行 → 返回 15 个款号
  ↓
Round 2:
  V2 输出: kg_query("style_summaries", style_ids=[...])
  外部系统执行 → 15 个摘要超出上下文上限
  外部系统自动截断 → 返回 5 个摘要 + {"truncated": true, "context_warning": "接近上限，仅返回前5个"}
  ↓
Round 3:
  V2 看到 context_warning → 判断"部分满足，但还有未显示的"
  V2 输出: {
    "thought": "部分摘要已返回，基于现有信息做最佳回答",
    "satisfied": true,
    "function_calls": [
      {"name": "generate_answer", "params": {"template": "my_styles_summary", "data": {"summaries": [...], "note": "仅显示前5个，共15个款号"}}}
    ]
  }
  外部系统生成回答（带"还有10个款号未显示"提示）
```

### 示例 4：续查绕过 V2

```
用户: "我跟的款号进度怎么样"
  ↓
V2 多轮 → 返回前5个款号摘要 + "还有10个未显示"
  ↓
用户: "剩下的呢"
  ↓
【绕过 V2】外部系统查记忆 → 返回第6-10个
  ↓
用户: "还有呢"
  ↓
【绕过 V2】外部系统查记忆 → 返回第11-15个
```

---

## 七、与 V3 的衔接

```
用户输入
  ↓
【Layer 1: 预处理】续查/指代消解/多意图过滤
  ↓
V3: 判断 route_v1 / route_v2 / direct_answer
  ↓
route_v2 → 外部系统调用 V2 多轮编排
  ↓
返回回答
```

---

## 八、训练数据格式

### 8.1 工具契约（Tools Spec）

V2 训练时必须知道每个工具的**入参、出参、可返回字段**：

```python
RESULT_FIELDS = {
    "kg_query.my_styles": [
        "styles", "styles.style_id", "styles.latest_category", "styles.event_count",
        "styles.total_delay_days", "total_styles"
    ],
    "kg_query.person_styles": [
        "styles", "styles.style_id", "styles.latest_category", "styles.event_count",
        "styles.total_delay_days", "total_styles"
    ],
    "kg_query.factory_styles": [
        "styles", "styles.style_id", "styles.total_delay_days", "total_styles"
    ],
    "kg_query.find_styles_with_conditions": [
        "styles", "styles.style_id", "styles.matched_categories", "styles.total_delay_days", "total"
    ],
    "kg_query.style_overview": [
        "style_id", "people", "timeline", "by_category", "by_category.面料", "by_category.封样",
        "total_events", "latest_category", "last_update"
    ],
    "kg_query.style_summaries": [
        "summaries", "summaries.style_id", "summaries.status", "summaries.current_stage",
        "summaries.delay_days", "summaries.last_update", "total"
    ],
    "kg_query.timeline": [
        "events", "events.description", "events.date", "events.delay_days", "events.category"
    ],
    "kg_query.collaborators": [
        "collaborators", "collaborators.name", "collaborators.event_count", "collaborators.style_count", "total_unique"
    ],
    "kg_query.factory_delays": [
        "factories", "factories.name", "factories.total_delay_days", "factories.avg_delay", "total_factories"
    ],
    "rag_query.term_translation": [
        "translations", "translations.chinese", "translations.english", "translations.category", "best_match"
    ],
    "rag_query.semantic_search": [
        "events", "events.style_id", "events.description", "events.category", "events.score", "events.delay_days", "total"
    ],
    "rag_query.semantic_search_by_date": [
        "events", "events.id", "events.description", "events.style_id", "events.category",
        "events.date", "events.delay_days", "total"
    ],
    "rag_query.semantic_search_by_conditions": [
        "events", "events.id", "events.description", "events.style_id", "events.category",
        "events.date", "events.delay_days", "total"
    ],
}
```

**模型决策时**：
1. 看入参 → 我需要提供什么
2. 看出参 → 我能得到什么
3. 看 `result` 字段 → 我只取需要的，减少数据量

### 8.2 SFT 数据格式（ShareGPT）

```json
{
  "messages": [
    {"role": "system", "content": "你是V2查询策略模型..."},
    {"role": "user", "content": "[用户提问] 我跟的款号进度怎么样"},
    {"role": "assistant", "content": "{\"thought\":\"用户查询我的款号进度，需要先获取款号列表\",\"satisfied\":false,\"function_calls\":[{\"name\":\"kg_query\",\"params\":{\"type\":\"my_styles\"},\"result\":[\"styles.style_id\",\"styles.latest_category\",\"total_styles\"]}]}"},
    {"role": "user", "content": "[工具返回] {\"styles\": [{\"style_id\":\"CCSS230021\",\"latest_category\":\"出货\"},...],\"total\":5}"},
    {"role": "assistant", "content": "{\"thought\":\"已获取5个款号，需要查摘要才能回答进度\",\"satisfied\":false,\"function_calls\":[{\"name\":\"kg_query\",\"params\":{\"type\":\"style_summaries\",\"style_ids\":[...]},\"result\":[\"summaries.style_id\",\"summaries.status\",\"summaries.current_stage\",\"summaries.delay_days\"]}]}"},
    {"role": "user", "content": "[工具返回] {\"summaries\": [{\"style_id\":\"CCSS230021\",\"status\":\"正常\",\"current_stage\":\"出货\"},...],\"total\":5}"},
    {"role": "assistant", "content": "{\"thought\":\"已获取所有款号的进度摘要，信息满足用户提问\",\"satisfied\":true,\"function_calls\":[{\"name\":\"generate_answer\",\"params\":{\"template\":\"my_styles_summary\",\"data\":{\"summaries\":[...]}}}]}"}
  ]
}
```

### 8.3 标记约定

| 标记 | 含义 | 来源 |
|-----|------|------|
| `[用户提问]` | 用户的原始问题 | 用户输入 |
| `[工具返回]` | 外部系统执行查询后的结果（已按 `result` 字段精简） | 系统反馈 |
| `[上下文警告]` | 外部系统标记的截断/长度警告 | 系统反馈 |

### 8.4 DPO 数据格式

```json
{
  "instruction": "你是V2查询策略模型...",
  "input": "[用户提问] 我跟的款号进度怎么样\n[工具返回] {\"styles\": [\"S1\", \"S2\", \"S3\"], \"count\": 3}",
  "chosen": "{\"thought\":\"已获取3个款号，需要查摘要\",\"satisfied\":false,\"function_calls\":[{\"name\":\"kg_query\",\"params\":{\"type\":\"style_summaries\",\"style_ids\":[\"S1\",\"S2\",\"S3\"]},\"result\":[\"summaries.style_id\",\"summaries.status\",\"summaries.current_stage\"]}]}",
  "rejected": "{\"thought\":\"已获取款号列表，直接回答\",\"satisfied\":true,\"function_calls\":[{\"name\":\"generate_answer\",\"params\":{\"template\":\"style_list\",\"data\":{\"styles\":[\"S1\",\"S2\",\"S3\"]}}}]}"
}
```

**rejected 错误**：有款号但没查摘要就回答，无法满足"进度"需求。

### 8.5 查询链训练示例

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "[用户提问] Paula Cheng 面料阶段事件数>30的款号"},
    {"role": "assistant", "content": "{\"thought\":\"需要：1) Paula Cheng的款号列表 2) 每个款号的面料事件数。使用查询链，先查款号列表，再批量查面料事件，只返回需要的字段\",\"satisfied\":false,\"function_calls\":[{\"name\":\"kg_query\",\"params\":{\"type\":\"person_styles\",\"person_name\":\"Paula Cheng\"},\"result\":[\"styles.style_id\",\"total_styles\"]},{\"name\":\"kg_query\",\"params\":{\"type\":\"style_overview\"},\"result\":[\"style_id\",\"by_category.面料\"]}]}"},
    {"role": "user", "content": "[工具返回] {\"status\":\"success\",\"style_overviews\":[{\"style_id\":\"S1\",\"by_category\":{\"面料\":[...]}},...],\"_meta\":{\"primary_total\":50,\"secondary_success\":48}}"},
    {"role": "assistant", "content": "{\"thought\":\"已获取所有款号的面料事件数，统计后发现没有超过30个的\",\"satisfied\":true,\"function_calls\":[{\"name\":\"generate_answer\",\"params\":{\"template\":\"style_list\",\"data\":{\"message\":\"Paula Cheng 的款号中，面料阶段事件数最多的为 XX 个，没有超过30个的款号\"}}}]}"}
  ]
}
```

---

## 九、查询链配置（CALL_CHAIN_RULES）

V2 执行引擎 `v2_executor.py` 定义了 33 种合法查询链：

### 9.1 一级查询接口（7 种）

| 一级接口 | 说明 | 返回 |
|---------|------|------|
| `my_styles` | 获取"我"的款号列表 | `styles[].style_id` |
| `person_styles` | 获取某人员的款号列表 | `styles[].style_id` |
| `factory_styles` | 获取某工厂的款号列表 | `styles[].style_id` |
| `find_styles_with_conditions` | 按条件筛选款号 | `styles[].style_id` |
| `semantic_search` | 语义检索 | `events[].style_id` |
| `semantic_search_by_date` | 按日期语义检索 | `events[].style_id` |
| `semantic_search_by_conditions` | 按条件语义检索 | `events[].style_id` |

### 9.2 二级查询接口（6 种）

| 二级接口 | 说明 | 需要入参 |
|---------|------|---------|
| `style_overview` | 单个款号详情 | `style_id` |
| `style_summaries` | 批量款号摘要 | `style_ids` |
| `timeline` | 单个款号时间线 | `style_id` |
| `semantic_search` | 语义检索 | `style_ids`（可选，查询链中自动填充） |
| `semantic_search_by_date` | 按日期检索 | `style_ids`（可选，查询链中自动填充） |
| `semantic_search_by_conditions` | 按条件检索 | `style_ids`（可选，查询链中自动填充） |

### 9.3 单轮接口（13 种）

| 单轮接口 | 说明 |
|---------|------|
| `my_styles` | 我的款号列表 |
| `person_styles` | 某人员的款号列表 |
| `factory_styles` | 某工厂的款号列表 |
| `find_styles_with_conditions` | 按条件筛选款号 |
| `style_overview` | 单个款号详情 |
| `style_summaries` | 批量款号摘要 |
| `timeline` | 单个款号时间线 |
| `collaborators` | 某人员的合作者 |
| `factory_delays` | 工厂延期排行 |
| `term_translation` | 术语翻译 |
| `semantic_search` | 语义检索 |
| `semantic_search_by_date` | 按日期语义检索 |
| `semantic_search_by_conditions` | 按条件语义检索 |

### 9.4 查询链组合（33 种）

```
my_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
person_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
factory_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
find_styles_with_conditions → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
semantic_search → style_overview / style_summaries / timeline
semantic_search_by_date → style_overview / style_summaries / timeline
semantic_search_by_conditions → style_overview / style_summaries / timeline
```

**非法查询链**（执行引擎会拒绝）：
- RAG 检索接口之间互相关联（如 semantic_search → semantic_search）
- 单轮查询作为一级配二级（如 collaborators → style_overview）

---

## 十、训练数据分布（1000 条）

| 类型 | 数量 | 说明 |
|------|------|------|
| **查询链** | 577 | 33 种组合，覆盖 KG→KG、KG→RAG、RAG→KG |
| **单轮** | 423 | 13 种单轮接口 |
| **总计** | 1000 | 996 验证通过，4 条采样空结果 |

### 10.1 高频查询链（前 10）

| 查询链 | 数量 |
|-------|------|
| my_styles → style_overview | 81 |
| my_styles → semantic_search | 47 |
| my_styles → style_summaries | 31 |
| my_styles → timeline | 31 |
| my_styles → semantic_search_by_date | 31 |
| my_styles → semantic_search_by_conditions | 31 |
| person_styles → style_overview | 23 |
| person_styles → semantic_search | 23 |
| semantic_search → style_overview | 15 |
| semantic_search_by_date → style_overview | 15 |

### 10.2 高频单轮（前 5）

| 单轮接口 | 数量 |
|---------|------|
| my_styles | 79 |
| collaborators | 59 |
| term_translation | 47 |
| factory_delays | 31 |
| semantic_search | 31 |

---

## 十一、关键设计原则

| 原则 | 说明 |
|-----|------|
| **V2 输出格式统一** | 永远是 `function_calls`，不区分查询/回答 |
| **V2 精确控制返回字段** | 通过 `result` 字段声明"我要什么"，外部系统只返回指定字段 |
| **V2 支持查询链** | 可在一个 function_calls 中输出一级+二级查询，外部系统处理依赖和批量展开；返回只保留二级结果 + `_meta` |
| **V2 不感知分页** | 外部系统截断后标记 `context_warning`，V2 基于此判断 |
| **续查绕过 V2** | "剩下的呢"等续查直接查记忆返回，不经过 V2 |
| **外部系统控制轮次上限** | 实际推理无上限（外部系统截断），DeepSeek 模拟时 10 轮兜底 |
| **V2 不生成回答** | 回答由外部系统的 `generate_answer` 生成 |
| **V2 不做统计计算** | 聚合统计（如"事件数>30"）由外部系统或 KG 层处理，V2 只负责"查什么" |

---

## 十二、训练数据生成方案（DeepSeek 模拟）

### 12.1 核心思路

用 DeepSeek 完全模拟 V2 的判断能力，基于真实数据生成训练数据：

```
v2_questions.json（已验证通过的问题）
    ↓
按 chain_type / interface_type 分层采样
    ↓
DeepSeek 模拟 V2 Round 1：输出查询策略（含 result 字段）
    ↓
本地执行查询（V2FunctionExecutor，支持查询链 + result 过滤）
    ↓
DeepSeek 模拟 V2 Round 2：看到精简结果 → 判断继续或满足
    ↓
本地执行查询（如需）→ 按 result 精简返回
    ↓
DeepSeek 模拟 V2 Round N：satisfied=true → 输出 generate_answer
    ↓
组装成 ShareGPT / DPO 格式的训练数据
```

### 12.2 数据划分

| 数据集 | 比例 | 数量 | 用途 |
|--------|------|------|------|
| 训练集 | 80% | ~800 | SFT 主训练 |
| 验证集 | 10% | ~100 | 训练过程中评估 loss |
| 测试集 | 10% | ~100 | 最终模型效果评估 |

**分层采样**：按 `chain_type` / `interface_type` 分层，确保各接口组合比例一致。

### 12.3 DeepSeek Prompt 设计

**System Prompt**：包含所有工具的入参、出参、可返回字段、输出格式规则、查询链说明。

**Few-shot 示例**：4 个完整多轮示例覆盖主要场景：
1. 我的款号进度（多轮 + result 精简）
2. 查询链（一级 + 二级）
3. 术语翻译（单轮搞定）
4. 语义检索（RAG+KG 联合）

### 12.4 多轮上限

| 场景 | 上限 | 说明 |
|-----|------|------|
| **实际 V2 推理** | 无上限 | 外部系统截断后标记 context_warning，V2 看到后判断 satisfied=true |
| **DeepSeek 模拟** | 10 轮 | 防止死循环，兜底机制 |

### 12.5 并发策略

| 粒度 | 策略 | 说明 |
|-----|------|------|
| **不同用户提问** | ✅ 并发 | 多个问题同时生成数据，互不影响 |
| **单个具体问题** | ❌ 串行 | 单条问题的多轮交互必须串行，每轮等待 DeepSeek 返回后才能进入下一轮 |

**并发控制**：
- 全局并发数：20（`--max-workers` 参数）
- 单个问题：严格串行

### 12.6 结果截断策略

训练数据生成时使用 `ResultTruncator` + `ContextManager` 做 token 级截断：

- **查询链结果**：只截断二级数据，保留 `_meta`
- **单轮结果**：按接口类型选择截断规则（events/styles/summaries/collaborators/factories/translations）
- **截断标记**：超出限制时添加 `[上下文警告]`，训练模型学会在部分信息下判断 satisfied=true

---

## 十三、已实现清单

- [x] V2 问题抽取脚本（`extract_v2_questions.py`）— 1000 条问题，33 查询链 + 13 单轮
- [x] V2 问题验证脚本（`validate_v2_questions.py`）— 996 验证通过
- [x] V2 训练数据生成脚本（`build_v2_dataset.py`）— DeepSeek 模拟多轮，本地 KG/RAG 执行
- [x] 结果截取工具（`result_truncator.py`）— 配置化规则
- [x] 上下文管理工具（`context_manager.py`）— token 估算、溢出检测、警告标记
- [x] 支持新的 function_calls 格式（`result` 字段、查询链）
- [x] 更新 KG/RAG 适配器支持 `result` 字段过滤和查询链批量展开
- [x] 查询链返回格式简化：省略一级结果，只保留二级结果 + `_meta`
- [x] `build_v2_dataset.py` 截断逻辑适配新格式（查询链只截断二级）
- [x] 训练数据去掉 `scene` 字段（纯 `messages` 格式）
- [ ] V2 SFT 训练（ShareGPT 格式，含 `result` 字段）
- [ ] V2 DPO 训练（单轮决策偏好对，含 `result` 字段）
- [ ] V2 模型评估（多轮触发率、满足度判断准确率、result 字段使用率）
- [ ] 外部系统 V2 编排器（多轮调用、查询链处理、轮次上限、结果累积）
- [ ] 与 V3 的集成测试

---

## 十四、参考文档

- `V3_ROUTING_RULES.md` — V3 路由规则
- `V2_QUESTION_GENERATION_SPEC.md` — 问题生成技术方案
- `email_agent/services/v2_executor.py` — V2 执行引擎（33 种查询链配置）
- `email_finetuning_pipeline/src/extract_v2_questions.py` — 问题生成脚本
- `email_finetuning_pipeline/src/build_v2_dataset.py` — 训练数据生成脚本

---

*文档创建日期：2026-05-01*
*最后更新：2026-05-07*
