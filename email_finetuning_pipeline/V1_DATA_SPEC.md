# V1 时间线分析模型数据规范

## 定位

款号级时间线分析器。接收款号相关事件，输出结构化时间线分析。

## 数据流

```
用户问："CCSS230013 的时间线"
       ↓
V3 → route_v1 → style_id="CCSS230013"
       ↓
外部代码：
  1. 查 RAG 获取该款式所有事件
  2. 按 date 排序
  3. 计算 token，决定分几轮
       ↓
第 N 轮调用 V1:
  {
    "style_id": "CCSS230013",
    "round": N,
    "total_rounds": M,
    "events": [...]
  }
       ↓
V1 输出：Markdown 时间线表格 + 风险点 + 关键路径
       ↓
V3 按顺序展示各轮输出
```

## 输入格式

```json
{
  "style_id": "CCSS230013",
  "events": [
    {
      "category": "面料",
      "event_type": "提交",
      "date": "2022-11-02",
      "related_date": "",
      "delay_days": 0,
      "party_from": "工厂",
      "party_to": "客人",
      "description": "款号 CCSS230013 的面料于 2022-11-02 提交",
      "source_filename": "1577.eml",
      "source_subject": "转发: EB- CCSS230013 -- 面料提交"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| style_id | string | 是 | 款号 |
| events | array | 是 | 事件列表 |
| events[].category | string | 是 | 阶段（面料/样衣/出货...） |
| events[].event_type | string | 是 | 事件类型（提交/确认/给意见...） |
| events[].date | string | 是 | 事件日期 YYYY-MM-DD |
| events[].related_date | string | 否 | 计划/关联日期 |
| events[].delay_days | int | 否 | 延期天数，0表示无延期 |
| events[].party_from | string | 是 | 发起方 |
| events[].party_to | string | 是 | 接收方 |
| events[].description | string | 是 | 事件描述 |
| events[].source_filename | string | 是 | 来源邮件文件名 |
| events[].source_subject | string | 是 | 来源邮件主题 |

## 输出格式

```markdown
## 📋 款号 {style_id} 时间线分析（第 {round}/{total_rounds} 部分）

### 一、📅 时间线梳理

#### 1. {阶段图标} {阶段名}
| 阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件 |
|------|------|------|------|------|----------|
| {category} | {图标}{event_type} | {date} | {delay} | {简化描述} | 📧 {filename} |
| ... | ... | ... | ... | ... | ... |

#### 2. {阶段图标} {阶段名}
...

### 二、⚠️ 风险点
- {风险等级图标} **{风险标题}**：{风险描述}
- ...

### 三、🛤️ 关键路径
{阶段图标} {阶段}({date}) → {阶段图标} {阶段}({date}) → ...
```

### 图标映射

| 元素 | 图标 |
|------|------|
| 标题 | 📋 |
| 时间线 | 📅 |
| 面料 | 🧵 |
| 样衣 | 👔 |
| 出货 | 🚚 |
| 确认 | ✅ |
| 给意见 | 💬 |
| 修改 | 🔧 |
| 提交 | 📤 |
| 风险点 | ⚠️ |
| 高风险 | 🔴 |
| 中风险 | 🟡 |
| 低风险 | 🟢 |
| 关键路径 | 🛤️ |
| 来源邮件 | 📧 |

## 训练样本格式（sharegpt）

```json
{
  "style_id": "CCSS230013",
  "messages": [
    {
      "role": "system",
      "content": "你是服装行业业务分析师。请根据提供的事件记录，整理成结构化时间线表格并分析延期根因。输出必须包含：一、📅时间线梳理（按阶段分表格，表格含来源邮件列）；二、⚠️风险点；三、🛤️关键路径。如果某阶段无记录，请明确标注'未找到记录'，不要编造。"
    },
    {
      "role": "user",
      "content": "{\"style_id\":\"CCSS230013\",\"events\":[...]}"
    },
    {
      "role": "assistant",
      "content": "## 📋 款号 CCSS230013 时间线分析\n\n### 一、📅 时间线梳理\n\n#### 1. 🧵 面料阶段\n| 阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件 |\n|------|------|------|------|------|----------|\n| 面料 | 提交 | 2022-11-02 | - | 工厂提交面料 | 📧 1577.eml |\n...\n\n### 二、⚠️ 风险点\n- 🔴 **样衣反复修改**：...\n\n### 三、🛤️ 关键路径\n🧵 面料提交(2022-11-02) → ..."
    }
  ]
}
```

## 关键设计决策

| 决策 | 内容 |
|------|------|
| 查询职责 | 外部代码，不在 V1 内 |
| 分轮策略 | 按 token 上限分轮，每轮独立 |
| 多轮合并 | 不合并，V3 顺序展示 |
| 记忆系统 | 不需要，V1 每轮无状态 |
| 训练样本 | 单轮，包含全部事件 |
| 推理调用 | 外部代码拆多轮，每轮独立调用 |
| 来源邮件 | 放在表格最后一列 |

## 生成命令

```bash
# 训练集
python src/build_v1_timeline_dataset.py \
    --events ../../email_rag_pipeline/output/events_passed.json \
    --output-dir datasets \
    --target 500

# 独立验证集（边缘款号）
python src/build_v1_timeline_dataset.py \
    --events ../../email_rag_pipeline/output/events_passed.json \
    --output-dir datasets/val_v1 \
    --target 50 \
    --use-poor-styles
```
