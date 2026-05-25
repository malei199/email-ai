# V2 问题生成技术方案

> 状态：已实现
> 对应文档：V2_CAPABILITY_DESIGN.md
> 创建日期：2026-04-29
> 最后更新：2026-05-07

---

## 一、目标

用 DeepSeek 根据本地 KG/RAG 接口能力和真实数据片段，生成**可回答的**用户问题。

生成的问题包含：问题文本 + 所需接口（含 result 字段）+ 推理说明。

---

## 二、核心决策

| 问题 | 决策 |
|-----|------|
| 接口描述详细程度 | **函数签名 + 入参出参字段说明 + result 字段** |
| 是否允许"未来接口" | **不允许**：严格现有接口能回答 |
| 数据采样方式 | **动态采样**：每次运行时重新查 KG/RAG |
| 是否输出 scene_type | **否**：使用 `chain_type`（查询链）或 `interface_type`（单轮）标识 |
| 是否输出 estimated_rounds | **否**：轮次数是调用方案的事，训练数据生成时处理 |

---

## 三、接口体系

### 3.1 接口到 name 的映射

```python
INTERFACE_TO_NAME = {
    "my_styles": "kg_query",
    "person_styles": "kg_query",
    "factory_styles": "kg_query",
    "find_styles_with_conditions": "kg_query",
    "style_overview": "kg_query",
    "style_summaries": "kg_query",
    "timeline": "kg_query",
    "collaborators": "kg_query",
    "factory_delays": "kg_query",
    "term_translation": "rag_query",
    "semantic_search": "rag_query",
    "semantic_search_by_date": "rag_query",
    "semantic_search_by_conditions": "rag_query",
}
```

### 3.2 result 字段预定义（13 种接口）

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

### 3.3 接口描述

```python
INTERFACE_DESCRIPTIONS = {
    "my_styles": "获取当前登录用户的款号列表（无需指定人名）",
    "person_styles": "获取指定人员的款号列表",
    "factory_styles": "获取指定工厂的款号列表",
    "find_styles_with_conditions": "按条件（阶段、延期天数等）筛选款号",
    "style_overview": "获取单个款号的完整概览（阶段分布、人员、事件数）",
    "style_summaries": "批量获取多个款号的摘要信息",
    "timeline": "获取单个款号的时间线事件",
    "collaborators": "获取与指定人员协作最多的同事列表",
    "factory_delays": "获取各工厂的延期统计排名",
    "term_translation": "翻译服装行业术语（中英对照）",
    "semantic_search": "基于语义相似度检索邮件事件",
    "semantic_search_by_date": "检索最近N天的邮件事件",
    "semantic_search_by_conditions": "按条件（阶段、延期天数等）检索邮件事件",
}
```

---

## 四、查询链配置（CALL_CHAIN_RULES）

V2 执行引擎 `v2_executor.py` 定义了 33 种合法查询链：

### 4.1 一级查询接口（7 种）

| 一级接口 | name | 说明 | 返回关键字段 |
|---------|------|------|-------------|
| `my_styles` | kg_query | 获取"我"的款号列表 | `styles[].style_id` |
| `person_styles` | kg_query | 获取某人员的款号列表 | `styles[].style_id` |
| `factory_styles` | kg_query | 获取某工厂的款号列表 | `styles[].style_id` |
| `find_styles_with_conditions` | kg_query | 按条件筛选款号 | `styles[].style_id` |
| `semantic_search` | rag_query | 语义检索 | `events[].style_id` |
| `semantic_search_by_date` | rag_query | 按日期语义检索 | `events[].style_id` |
| `semantic_search_by_conditions` | rag_query | 按条件语义检索 | `events[].style_id` |

### 4.2 二级查询接口（6 种）

| 二级接口 | name | 说明 | 需要入参 |
|---------|------|------|---------|
| `style_overview` | kg_query | 单个款号详情 | `style_id` |
| `style_summaries` | kg_query | 批量款号摘要 | `style_ids` |
| `timeline` | kg_query | 单个款号时间线 | `style_id` |
| `semantic_search` | rag_query | 语义检索 | `style_ids`（查询链中自动填充） |
| `semantic_search_by_date` | rag_query | 按日期检索 | `style_ids`（查询链中自动填充） |
| `semantic_search_by_conditions` | rag_query | 按条件检索 | `style_ids`（查询链中自动填充） |

### 4.3 33 种查询链组合

```
# KG 一级 → KG/RAG 二级（24 种）
my_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
person_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
factory_styles → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions
find_styles_with_conditions → style_overview / style_summaries / timeline / semantic_search / semantic_search_by_date / semantic_search_by_conditions

# RAG 一级 → KG 二级（9 种）
semantic_search → style_overview / style_summaries / timeline
semantic_search_by_date → style_overview / style_summaries / timeline
semantic_search_by_conditions → style_overview / style_summaries / timeline
```

### 4.4 单轮接口（13 种）

不在 CALL_CHAIN_RULES 中，或可作为独立调用：

```python
SINGLE_INTERFACE_TYPES = [
    "my_styles", "person_styles", "factory_styles", "find_styles_with_conditions",
    "collaborators", "factory_delays", "term_translation",
    "semantic_search", "semantic_search_by_date", "semantic_search_by_conditions",
    "style_overview", "style_summaries", "timeline",
]
```

### 4.5 非法查询链

- RAG 检索接口之间互相关联（如 semantic_search → semantic_search）
- 单轮查询作为一级配二级（如 collaborators → style_overview）

---

## 五、问题分布配置

### 5.1 QUESTION_DISTRIBUTION（253 条基数，可缩放至 1000+）

```python
QUESTION_DISTRIBUTION = {
    # === 查询链（33种）===
    "my_styles -> style_overview": 12,
    "my_styles -> style_summaries": 8,
    "my_styles -> timeline": 8,
    "my_styles -> semantic_search": 12,
    "my_styles -> semantic_search_by_date": 8,
    "my_styles -> semantic_search_by_conditions": 8,
    "person_styles -> style_overview": 6,
    "person_styles -> style_summaries": 4,
    "person_styles -> timeline": 4,
    "person_styles -> semantic_search": 6,
    "person_styles -> semantic_search_by_date": 4,
    "person_styles -> semantic_search_by_conditions": 4,
    "factory_styles -> style_overview": 3,
    "factory_styles -> style_summaries": 3,
    "factory_styles -> timeline": 3,
    "factory_styles -> semantic_search": 3,
    "factory_styles -> semantic_search_by_date": 3,
    "factory_styles -> semantic_search_by_conditions": 3,
    "find_styles_with_conditions -> style_overview": 3,
    "find_styles_with_conditions -> style_summaries": 3,
    "find_styles_with_conditions -> timeline": 3,
    "find_styles_with_conditions -> semantic_search": 3,
    "find_styles_with_conditions -> semantic_search_by_date": 3,
    "find_styles_with_conditions -> semantic_search_by_conditions": 3,
    "semantic_search -> style_overview": 4,
    "semantic_search -> style_summaries": 2,
    "semantic_search -> timeline": 2,
    "semantic_search_by_date -> style_overview": 4,
    "semantic_search_by_date -> style_summaries": 2,
    "semantic_search_by_date -> timeline": 2,
    "semantic_search_by_conditions -> style_overview": 4,
    "semantic_search_by_conditions -> style_summaries": 2,
    "semantic_search_by_conditions -> timeline": 2,

    # === 单轮查询（13种）===
    "my_styles": 20,
    "person_styles": 5,
    "factory_styles": 5,
    "find_styles_with_conditions": 5,
    "collaborators": 15,
    "factory_delays": 8,
    "term_translation": 12,
    "semantic_search": 8,
    "semantic_search_by_date": 8,
    "semantic_search_by_conditions": 8,
    "style_overview": 5,
    "style_summaries": 5,
    "timeline": 5,
}
```

### 5.2 实际生成分布（1000 条）

| 类型 | 数量 | 占比 |
|------|------|------|
| 查询链 | 577 | 57.7% |
| 单轮 | 423 | 42.3% |
| **总计** | **1000** | **100%** |

---

## 六、动态采样策略

### 6.1 采样流程

```
[启动]
  ↓
加载 CALL_CHAIN_RULES + QUESTION_DISTRIBUTION
  ↓
初始化 V2FunctionExecutor
  ↓
【遍历所有查询链配置】
  ├─ 对每个 primary_type -> secondary_type
  ├─ 调用 sample_chain_data() 采样真实数据
  ├─ 用 DeepSeek 生成问题
  ├─ 自动填充 requires_interface（含 result 字段）
  └─ 标记 chain_type
  ↓
【遍历所有单轮接口】
  ├─ 对每个 interface_type
  ├─ 调用 sample_single_data() 采样真实数据
  ├─ 用 DeepSeek 生成问题
  ├─ 自动填充 requires_interface（含 result 字段）
  └─ 标记 interface_type
  ↓
调用 v2_executor 验证问题可执行性
  ↓
保存结果到 v2_questions.json
```

### 6.2 查询链采样（sample_chain_data）

```python
def sample_chain_data(primary_type, secondary_type, executor, default_person="Paula Cheng"):
    # 1. 执行一级查询
    primary_call = _build_primary_call(primary_type, default_person)
    primary_result = executor.execute([primary_call])
    
    # 2. 提取依赖值（styles[].style_id 或 events[].style_id）
    dependency_values = _extract_dependency_values(primary_result, primary_type)
    
    # 3. 执行二级查询（用第一个依赖值作为示例）
    secondary_call = _build_secondary_call(secondary_type, dependency_values[0])
    secondary_result = executor.execute([secondary_call])
    
    return {
        "chain_type": f"{primary_type} -> {secondary_type}",
        "primary_data": truncated_primary_result,
        "secondary_example": truncated_secondary_result,
        "dependency_count": len(dependency_values),
    }
```

### 6.3 单轮采样（sample_single_data）

```python
def sample_single_data(interface_type, executor, default_person="Paula Cheng"):
    call = _build_single_call(interface_type, default_person)
    result = executor.execute([call])
    
    return {
        "interface_type": interface_type,
        "data": truncated_result,
    }
```

### 6.4 关键采样参数

| 参数 | 值 | 说明 |
|-----|-----|------|
| `semantic_search_by_date.days` | 365 | 默认 365 天（避免 7 天常返回空） |
| `semantic_search_by_conditions` | 总是包含 categories | 确保有筛选条件 |
| `style_summaries.style_ids` | 最多 5 个 | 避免过长 |
| `semantic_search.style_ids` | 最多 10 个 | 避免过长 |

---

## 七、DeepSeek Prompt 设计

### 7.1 查询链 Prompt

```
你是服装行业跟单员。基于以下真实业务数据，生成 {count} 个自然、口语化的用户问题。

【查询能力】
系统支持查询链：先执行一级查询获取范围，再自动执行二级查询获取详情。
当前查询链：{primary_type} -> {secondary_type}

一级查询（{primary_type}）：{primary_desc}
二级查询（{secondary_type}）：{secondary_desc}

【真实数据片段】
一级查询结果（示例）：
{primary_data}

二级查询结果（示例，基于一级第一个结果）：
{secondary_example}

【任务】
生成 {count} 个用户问题，要求：
1. 自然、口语化，像真实跟单员提问
2. 必须能用当前查询链回答
3. 不出现具体款号或订单号
4. 问题中不要提到人名（如Paula Cheng），用"我"代替
5. 如果一级是my_styles，问题要说"我的款号""我跟的款号"等
6. 如果一级是person_styles，问题可以说"Paula Cheng的款号"或"我跟的款号"

输出格式（JSON）：
{"questions": [
  {"question": "...", "reasoning": "为什么这个查询链能回答"}
]}
```

### 7.2 单轮 Prompt

```
你是服装行业跟单员。基于以下真实业务数据，生成 {count} 个自然、口语化的用户问题。

【查询能力】
单轮查询：{interface_type}
描述：{interface_desc}

【真实数据片段】
{data}

【任务】
生成 {count} 个用户问题，要求：
1. 自然、口语化，像真实跟单员提问
2. 必须能用当前接口回答
3. 不出现具体款号或订单号
4. 问题中不要提到人名（如Paula Cheng），用"我"代替
5. 如果查询的是当前用户，问题要说"我的款号""我跟的款号"等

输出格式（JSON）：
{"questions": [
  {"question": "...", "reasoning": "为什么这个接口能回答"}
]}
```

---

## 八、自动构建 requires_interface

### 8.1 查询链的 requires_interface

```python
def _build_chain_interfaces(primary_type, secondary_type, default_person):
    primary_call = _build_primary_call(primary_type, default_person)
    secondary_call = {
        "name": INTERFACE_TO_NAME[secondary_type],
        "params": {"type": secondary_type},  # 不含 style_id，由查询链自动填充
        "result": RESULT_FIELDS[f"{INTERFACE_TO_NAME[secondary_type]}.{secondary_type}"]
    }
    return [primary_call, secondary_call]
```

**示例**：
```json
[
  {"name": "kg_query", "params": {"type": "my_styles"}, "result": ["styles", "styles.style_id", "styles.latest_category", "styles.event_count", "styles.total_delay_days", "total_styles"]},
  {"name": "kg_query", "params": {"type": "style_overview"}, "result": ["style_id", "people", "timeline", "by_category", "by_category.面料", "by_category.封样", "total_events", "latest_category", "last_update"]}
]
```

### 8.2 单轮的 requires_interface

```python
def _build_single_call(interface_type, default_person):
    name = INTERFACE_TO_NAME[interface_type]
    result = RESULT_FIELDS[f"{name}.{interface_type}"]
    
    if interface_type == "my_styles":
        return {"name": name, "params": {"type": "my_styles"}, "result": result}
    elif interface_type == "person_styles":
        return {"name": name, "params": {"type": "person_styles", "person_name": default_person}, "result": result}
    # ... 其他接口类似
```

---

## 九、输出格式

### 9.1 查询链问题

```json
{
  "question": "我跟的款号里，有没有哪个款号的面料阶段出过问题？",
  "reasoning": "先获取我的款号列表，再查每个款号的面料阶段事件",
  "requires_interface": [
    {"name": "kg_query", "params": {"type": "my_styles"}, "result": [...]},
    {"name": "kg_query", "params": {"type": "style_overview"}, "result": [...]}
  ],
  "chain_type": "my_styles -> style_overview",
  "validation": {
    "status": "success",
    "executed_at": "2026-05-07T15:46:01.890998",
    "result": "执行成功返回有数据"
  }
}
```

### 9.2 单轮问题

```json
{
  "question": "我的合作者有哪些？",
  "reasoning": "直接用 collaborators 接口查询",
  "requires_interface": [
    {"name": "kg_query", "params": {"type": "collaborators", "person_name": "Paula Cheng", "top_k": 10}, "result": [...]}
  ],
  "interface_type": "collaborators",
  "validation": {
    "status": "success",
    "executed_at": "2026-05-07T15:46:02.050979",
    "result": "执行成功返回有数据"
  }
}
```

### 9.3 字段说明

| 字段 | 类型 | 说明 |
|-----|------|------|
| `question` | str | 用户问题（自然语言） |
| `reasoning` | str | 为什么这些接口能回答 |
| `requires_interface` | [dict] | 回答该问题需要的接口列表，每个接口含 name/params/result |
| `chain_type` | str | 查询链类型（如 `my_styles -> style_overview`），仅查询链问题有 |
| `interface_type` | str | 单轮接口类型（如 `collaborators`），仅单轮问题有 |
| `validation` | dict | 验证结果（status/executed_at/result） |

---

## 十、验证流程

### 10.1 验证脚本（validate_v2_questions.py）

```python
def validate_questions(input_path, output_path=None):
    # 1. 加载问题数据
    # 2. 初始化 V2FunctionExecutor
    # 3. 逐个执行 requires_interface
    # 4. 更新 validation 字段
    # 5. 保存结果
```

### 10.2 验证标准

| 结果 | 条件 |
|-----|------|
| success | 执行成功且返回有数据 |
| failed | 执行失败、返回为空、或执行异常 |

### 10.3 实际验证结果

| 指标 | 数值 |
|------|------|
| 总问题数 | 1000 |
| 验证通过 | 996 (99.6%) |
| 验证失败 | 4 (采样空结果，可重试) |

---

## 十一、性能估算

| 项目 | 估算 |
|-----|------|
| 接口组合数 | 33 查询链 + 13 单轮 = 46 种 |
| 每种采样 + 生成 | ~5-15 秒 |
| DeepSeek 调用 | 每批次 3 条问题 |
| 总生成时间（1000 条）| ~30-60 分钟 |
| 验证时间（1000 条）| ~5-10 分钟 |

---

## 十二、与训练数据生成的衔接

| 脚本 | 输入 | 输出 | 说明 |
|-----|------|------|------|
| `extract_v2_questions.py` | CALL_CHAIN_RULES + KG/RAG 数据 | `v2_questions.json` | 生成问题 + 验证 |
| `validate_v2_questions.py` | `v2_questions.json` | 更新后的 `v2_questions.json` | 重新验证 |
| `build_v2_dataset.py` | `v2_questions.json` | `train/val/test/sft_v2_multiround.jsonl` + `dpo_v2_multiround.jsonl` | DeepSeek 模拟多轮，生成训练数据 |

---

## 十三、参考文档

- `V2_CAPABILITY_DESIGN.md` — V2 能力设计
- `email_agent/services/v2_executor.py` — V2 执行引擎（CALL_CHAIN_RULES）
- `email_finetuning_pipeline/src/extract_v2_questions.py` — 问题生成脚本
- `email_finetuning_pipeline/src/validate_v2_questions.py` — 问题验证脚本
- `email_finetuning_pipeline/src/build_v2_dataset.py` — 训练数据生成脚本

---

*文档创建日期：2026-04-29*
*最后更新：2026-05-07*
