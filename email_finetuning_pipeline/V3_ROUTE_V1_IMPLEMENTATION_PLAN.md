# V3 触发 router_v1 调用外部服务方案（v2.0 极简版）

> 讨论日期：2026-05-01
> 状态：已确认（v2.0 重构：V3 退化为纯路由决策器）
> 相关文档：V3_ROUTING_RULES.md (v2.0), V1_DATA_SPEC.md

---

## 一、背景

V3（调度器）的职责已简化为**纯路由决策**：根据用户输入判断该走 `route_v1`、`route_v2` 还是 `direct_answer`。

**V3 不再参与后续流程**：
- 不接收 V1 结果回传
- 不接收 V2 结果回传
- 不做多轮查询编排
- 不做结果质量判断

---

## 二、完整交互流程（v2.0）

### 2.1 `route_v1` 链路

```
用户: "CCSS230013 的时间线"
    ↓
V3 (唯一一轮):
  输入: 用户问题
  输出: {"decision": "route_v1", "style_id": "CCSS230013"}
    ↓
【外部系统】接收 V3 输出，全权处理：
  1. 查 RAG/KG → 获取该款式所有事件
  2. 按 date 排序
  3. 计算 token，决定分 M 轮
  4. FOR round = 1..M:
       调用 V1(style_id, round, total_rounds, events_slice)
       收集 V1 返回的 Markdown
  5. 合并 M 轮 Markdown（用 \n\n---\n\n 拼接）
  6. 直接返回给用户
    ↓
用户看到最终回答（V3 不参与）
```

**关键变更（v2.0）**：
- ❌ 删除 V3 Round 2（不再接收 `[V1分析结果-xxx]`）
- ❌ 删除 V3 的 `direct_answer` 汇总输出
- ✅ 外部系统直接展示 V1 结果

---

### 2.2 `route_v2` 链路

```
用户: "Iris Jiang 的款号进度怎么样"
    ↓
V3 (唯一一轮):
  输入: 用户问题
  输出: {"decision": "route_v2"}
    ↓
【V2 引擎】接收原始用户问题，全权处理：
  1. 解析用户意图
  2. 选择查询工具（kg_query / rag_query / email_extract）
  3. 多轮查询自治（如需要）
  4. 分页截断（如款号过多）
  5. 批量摘要生成（如返回款号列表）
  6. 直接返回给用户
    ↓
用户看到最终回答（V3 不参与）
```

**关键变更（v2.0）**：
- ❌ 删除 V3 的 function_calls（V3 不指定查什么）
- ❌ 删除 V3 的多轮判断（V2 内部自治）
- ❌ 删除 V3 的模板选择（V2 负责格式化）
- ✅ V2 引擎自治，V3 只触发

---

### 2.3 `direct_answer` 链路

```
用户: "你好"
    ↓
V3 (唯一一轮):
  输入: 用户问题
  输出: {"decision": "direct_answer", "answer": "你好！我是服装行业智能助手..."}
    ↓
直接返回给用户
```

---

## 三、各环节职责划分（v2.0）

| 环节 | 负责方 | V3 是否参与 |
|-----|--------|-----------|
| **路由决策** | V3 | ✅ 唯一职责 |
| **输入预处理**（指代消解、改写） | 外部系统 | ❌ V3 之前 |
| **V1 事件查询** | 外部系统 | ❌ |
| **V1 排序/分轮** | 外部系统 | ❌ |
| **V1 模型调用** | 外部系统 | ❌ |
| **V1 结果合并/展示** | 外部系统 | ❌ |
| **V2 意图解析** | V2 引擎 | ❌ |
| **V2 工具选择** | V2 引擎 | ❌ |
| **V2 多轮查询** | V2 引擎 | ❌ |
| **V2 分页截断** | V2 引擎 | ❌ |
| **V2 批量摘要** | V2 引擎 | ❌ |
| **V2 结果展示** | V2 引擎 | ❌ |
| **记忆管理**（续查、上下文） | 外部系统 | ❌ |
| **兜底处理** | V2 引擎 / 外部系统 | ❌ |

---

## 四、V3 输出格式规范（v2.0）

### 4.1 `route_v1`

```json
{
  "decision": "route_v1",
  "style_id": "CCSS230013",
  "event": "延期"
}
```

- `style_id`：必填
- `event`：可选，用户关注的事件类型

### 4.2 `route_v2`

```json
{
  "decision": "route_v2"
}
```

**极简**。不输出 function_calls、不输出查询参数。

### 4.3 `direct_answer`

```json
{
  "decision": "direct_answer",
  "answer": "你好！我是服装行业智能助手..."
}
```

---

## 五、与 v1.x 的变更点

| v1.x | v2.0 |
|------|------|
| V3 有 Round 2（接收 V1 结果 → 输出 direct_answer） | **V3 只有 1 轮**，V1 结果由外部系统直接展示 |
| V3 输出 function_calls 指定 V2 查什么 | **V3 只输出 `route_v2`**，V2 自己决定 |
| V3 判断 V2 结果"够不够用" | **V3 不做判断**，V2 自治返回完整结果 |
| V3 参与多轮查询编排 | **V3 不参与**，V2 内部自治 |
| V3 训练数据 3-5 轮 | **V3 训练数据 1 轮** |
| V3 需要学模板选择 | **V3 不学模板** |

---

## 六、训练数据规格（v2.0）

### 6.1 单条样本结构

**只有 3 个 message**：

```json
{
  "scene": "route_v1",
  "messages": [
    {"role": "system", "content": "你是服装行业智能调度器。根据用户问题，决定如何回答：\n1. direct_answer: 直接回答\n2. route_v2: 调用 V2 查询引擎（无款号）\n3. route_v1: 调用 V1 时间线推理模型（有款号）\n输出格式：{\"decision\": \"...\", ...}"},
    {"role": "user", "content": "CCSS230013 的时间线"},
    {"role": "assistant", "content": "{\"decision\": \"route_v1\", \"style_id\": \"CCSS230013\"}"}
  ]
}
```

```json
{
  "scene": "route_v2",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Iris Jiang 的款号进度怎么样"},
    {"role": "assistant", "content": "{\"decision\": \"route_v2\"}"}
  ]
}
```

```json
{
  "scene": "direct_answer",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "{\"decision\": \"direct_answer\", \"answer\": \"你好！我是服装行业智能助手...\"}"}
  ]
}
```

### 6.2 场景分布

| 场景 | 比例 |
|-----|------|
| `route_v1` | ~40% |
| `route_v2` | ~43% |
| `direct_answer` | ~12% |
| `boundary` | ~5% |

### 6.3 DPO 错误模式

| 正确决策 | 错误决策（rejected） |
|---------|-------------------|
| `route_v1`（有款号） | `route_v2`（有款号却走 V2） |
| `route_v2`（无款号） | `direct_answer`（无款号却拒绝服务） |
| `route_v2`（无款号） | `route_v1`（无款号却走 V1） |
| `direct_answer`（问候） | `route_v2`（问候却走 V2） |

---

## 七、实施步骤

1. **修改 `build_v3_scheduler_dataset.py`**：
   - 删除所有多轮逻辑
   - 删除 V1 报告生成（DeepSeek 调用）
   - 删除 V2 mock 数据生成
   - 简化为单轮决策样本

2. **修改 `email_agent/agents/chat_agent.py`**：
   - V3 只调用一次，获取 decision
   - 根据 decision 直接调 V1/V2/返回 answer
   - 删除 V3 Round 2 的调用逻辑

3. **修改 `email_agent/agents/v1_orchestrator.py`**：
   - 确认外部系统直接展示 V1 结果，不回传 V3

4. **修改 `email_agent/agents/v2_engine.py`**（如有）：
   - V2 接收原始用户问题，自治查询

5. **重新生成训练数据**：
   - `python build_v3_scheduler_dataset.py`
   - 验证所有样本只有 3 条 messages

6. **重新训练 V3**：
   - 用新数据训练/微调
   - 验证 V3 只输出 decision，不参与后续

---

## 八、参考文档

- `V3_ROUTING_RULES.md` (v2.0) — V3 路由规则（极简版）
- `V1_DATA_SPEC.md` — V1 输入输出格式
- `src/build_v3_scheduler_dataset.py` — V3 训练数据生成（待重构）
- `src/build_v1_timeline_dataset.py` — V1 训练数据生成

---

*规则确认日期：2026-05-01*
