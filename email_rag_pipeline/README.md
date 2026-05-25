# 邮件事件型 RAG 构建流水线

本流水线用于将原始 `.eml` 邮件批量转化为结构化的业务事件，并构建可供检索的向量知识库。

## 核心流程

```
7359 封原始 .eml
    │
    ▼
[pre_filter_emails.py] 前置过滤（V2 - 款号感知）
    ├── 黑名单过滤（退信/自动回复/系统通知）
    ├── 短内容过滤（< 200 字符的系统提示邮件）
    ├── 业务关键词保护（含款号/订单/面料等关键词的短邮件保留）
    └── 智能去重（有款号邮件保留 3 封/款号，无款号按主题去重）
    │
    ▼
约 2500+ 封有效邮件
    │
    ▼
[build_email_event_rag.py] LLM 提取 + RAG 建库（V2 - 扩展分类）
    ├── 深度清洗（解码 / 去签名 / 去转发头 / 去 HTML）
    ├── 款号提取（CCSS / INDO / AW / SS / CCAW / CDIB / P_SERIES / 7位数字）
    ├── 订单号提取（6-9 位纯数字，过滤年份/日期格式）
    ├── DeepSeek API 批量提取结构化事件（15 分类 / 4 事件类型）
    ├── 质量过滤（confidence >= 0.7 通过，0.5~0.7 待复核，< 0.5 丢弃）
    └── ChromaDB 向量库（collection: email_events_new）
```

---

## 目录结构

```
email_rag_pipeline/
├── build_email_event_rag.py    # 主流水线：清洗 -> LLM提取 -> 质量过滤 -> ChromaDB入库
├── pre_filter_emails.py        # 前置过滤：去重 / 去系统邮件 / 款号感知 / 业务保护
├── test_timeline_rag.py        # RAG 检索测试脚本
├── README.md                   # 本文件
├── src/
│   └── term_rag_integration.py # 术语RAG集成（邮件术语识别翻译）
├── output/new/                 # 输出目录（自动生成，与 email_events_new collection 对应）
│   ├── filtered_email_manifest.jsonl   # 过滤后的邮件清单
│   ├── filter_stats.json               # 过滤统计
│   ├── events_raw.jsonl                # LLM提取原始结果
│   ├── events_passed.json              # 高置信度事件（入向量库）
│   ├── events_review.jsonl             # 待人工复核事件
│   └── processing_stats.json           # 处理统计报告
└── scripts/
    └── run_full_pipeline.sh    # 一键全量构建脚本（推荐）
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install chromadb sentence-transformers openai tqdm
```

### 2. 配置 API Key

```bash
export DEEPSEEK_API_KEY="your-api-key-here"
```

> 如果没有 DeepSeek API Key，可前往 [DeepSeek 开放平台](https://platform.deepseek.com/) 注册获取。

### 3. 前置过滤（强烈建议先跑）

```bash
python email_rag_pipeline/pre_filter_emails.py
```

运行后会输出：
- `email_rag_pipeline/output/new/filtered_email_manifest.jsonl`：通过过滤的邮件清单
- `email_rag_pipeline/output/new/filter_stats.json`：过滤统计报告

**默认过滤规则（V2）：**
- 黑名单主题：`Undeliverable`, `Delivery Status`, `Out of Office`, `Auto Reply`, `系统自动回复`, `验证码` 等
- 黑名单发件人：`postmaster@`, `mailer-daemon@` 等（**注意**：不会误杀 `donotreply@editrack.com`）
- 短内容过滤：非系统邮件清洗后正文 < **200 字符**直接丢弃；`editrack.com` 系统邮件 < **300 字符**丢弃
- **业务关键词保护**：即使邮件很短，如果包含款号、订单号、面料名称等业务关键词，**强制保留**
- **智能去重**：
  - 有款号邮件：同一款号保留 **3 封**（避免过度去重丢失上下文）
  - 无款号邮件：忽略 `回复:/Re:` 前缀后相同主题，只保留**最新 1 封**

你可以调整阈值：
```bash
# 提高内容长度门槛
python email_rag_pipeline/pre_filter_emails.py --min-length 300

# 同主题保留最新 2 封
python email_rag_pipeline/pre_filter_emails.py --max-per-subject 2
```

### 4. 样本测试（基于过滤后的邮件）

```bash
python email_rag_pipeline/build_email_event_rag.py --use-filtered --sample 10 --skip-rag
```

**样本测试结果参考**：10 封邮件成功提取出 **20 个高质量事件**，全部通过 `confidence >= 0.7` 门槛，0 条待复核。`category` 和 `delay_days` 识别准确。

运行后检查输出目录：
- `email_rag_pipeline/output/new/events_raw.jsonl`：原始提取结果
- `email_rag_pipeline/output/new/events_passed.json`：高置信度事件
- `email_rag_pipeline/output/new/events_review.jsonl`：待复核事件
- `email_rag_pipeline/output/new/processing_stats.json`：统计报告

### 5. 全量运行（推荐方式）

**推荐使用一键脚本**，自动完成清理旧数据 -> 全量提取 -> 提示复核 -> 重建向量库：

```bash
./email_rag_pipeline/scripts/run_full_pipeline.sh
```

脚本会自动：
1. 检查 `DEEPSEEK_API_KEY` 和过滤清单是否存在
2. 清理旧的中间结果
3. 全量调用 DeepSeek API 提取事件（带 `--resume` 断点恢复）
4. 检查 `events_review.jsonl`，提示人工复核
5. 重建 `email_events_new` ChromaDB collection

**预计耗时与费用：**
- 时间：**1.5~2 小时**（含 Embedding 编码和 ChromaDB 写入）
- 费用：**约 15~40 元**（基于 2500+ 封过滤后邮件）
- 预计事件数：**7000~8000 个**（实际提取约 7,893 个，通过约 7,000+ 个）

如果你不想用脚本，也可以手动分步执行：
```bash
# Step 1: 全量提取（跳过建库）
python email_rag_pipeline/build_email_event_rag.py --use-filtered --skip-rag --resume

# Step 2: 人工复核 events_review.jsonl 后，重建向量库
python email_rag_pipeline/build_email_event_rag.py --use-filtered --skip-extraction
```

### 6. 断点恢复

如果中途断网或报错：

```bash
python email_rag_pipeline/build_email_event_rag.py --use-filtered --skip-rag --resume
```

---

## 常见问题与解决

### Q1: 提示 "未设置 DEEPSEEK_API_KEY 环境变量"

**原因**：当前 shell 进程没有拿到 API Key。

**解决**：
```bash
# 方式 A：直接带在命令前面
DEEPSEEK_API_KEY="your-key" python email_rag_pipeline/build_email_event_rag.py --use-filtered --sample 10

# 方式 B：先 export 再运行
export DEEPSEEK_API_KEY="your-key"
python email_rag_pipeline/build_email_event_rag.py --use-filtered --sample 10
```

### Q2: 提示 "PyTorch >= 2.4 is required but found 2.2.2"

**原因**：新版 `transformers` 要求 PyTorch >= 2.4，但 macOS x86_64 最高只能装到 2.2.2。

**解决**：降级到兼容版本
```bash
pip install transformers==4.39.3 sentence-transformers==2.7.0
```

### Q3: macOS 上 embedding 模型初始化时报 `libiomp5.dylib` / `pthread_mutex_init` 错误

**原因**：PyTorch 和 NumPy 的 OpenMP 库冲突。

**解决**：已在 `build_email_event_rag.py` 中内置修复（自动设置 `KMP_DUPLICATE_LIB_OK=TRUE` 和 `OMP_NUM_THREADS=1`）。如果仍然报错，可手动在运行前设置：
```bash
export KMP_DUPLICATE_LIB_OK=TRUE
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

### Q4: 加载 `BAAI/bge-large-zh-v1.5` 时 Hugging Face 连接超时

**原因**：国内网络访问 `huggingface.co` 不稳定。

**解决**：设置镜像源
```bash
export HF_ENDPOINT=https://hf-mirror.com
python email_rag_pipeline/build_email_event_rag.py --use-filtered --sample 10
```

或者**分步执行**：先跑 `--skip-rag` 完成 LLM 提取，等网络好转时再单独跑 `--skip-extraction` 建库。

### Q5: 7 位纯数字（如 `3539899`）被误识别为款号

**原因**：New Look 的 7 位数字既可能是款号（`9251268`），也可能是 PO 号。

**影响**：由于检索时通常使用明确的字母+数字款号（如 `INDOT27551`、`AW25-KFWTS101`）查询，这类误识别**不会干扰核心使用场景**。如后续影响较大，可进一步优化 Prompt 增加区分规则。

---

## 输出文件说明

### 前置过滤输出

| 文件 | 说明 |
|------|------|
| `filtered_email_manifest.jsonl` | 通过过滤的邮件清单，包含 `filepath`, `subject`, `content_length`, `style_ids`, `is_system_sender` 等 |
| `filter_stats.json` | 过滤统计：原始数量、黑名单移除、短内容移除、去重移除、款号感知保留、最终保留数量 |

### LLM 提取输出

| 文件 | 说明 |
|------|------|
| `events_raw.jsonl` | 每封邮件的 LLM 提取原始结果，包含 `events`、`api_response`、`style_ids`、`order_ids` 等 |
| `events_passed.json` | `confidence >= 0.7` 的事件，最终写入 ChromaDB（含 `source_filename`/`source_subject`） |
| `events_review.jsonl` | `0.5 <= confidence < 0.7` 的事件，需要你人工复核 |
| `processing_stats.json` | 最终统计：邮件处理状态、事件分级数量、分类分布、覆盖款号数、订单号统计 |

---

## 事件字段说明

每个提取出的事件包含以下字段：

```json
{
  "style_id": "INDOT27551",
  "order_id": "310052",
  "category": "Lab Dip",
  "event_type": "确认",
  "date": "2025-05-15",
  "related_date": "2025-05-12",
  "delay_days": 3,
  "party_from": "客人",
  "party_to": "工厂",
  "description": "款号 INDOT27551 的 Lab Dip 于 5/15 获得客人确认",
  "confidence": 0.92,
  "source_filename": "xxx.eml",
  "source_subject": "回复: INDOT27551 Lab Dip 确认"
}
```

| 字段 | 说明 |
|------|------|
| `style_id` | 款号（字母开头为主，如 CCSS/AW/INDO/CCAW/SS） |
| `order_id` | 订单号（6-9 位纯数字，一个订单可能包含多个款号） |
| `category` | 业务阶段（见下方扩展分类） |
| `event_type` | 具体事件（见下方扩展类型） |
| `date` | 事件实际日期（YYYY-MM-DD） |
| `related_date` | 原计划日期或对比日期 |
| `delay_days` | 延期天数（正数=延期，负数=提前，0=无延期，null 时 ChromaDB 中存储为 -999） |
| `party_from` | 发起方 |
| `party_to` | 接收方 |
| `confidence` | LLM 提取置信度（0.0~1.0） |
| `source_filename` | 来源邮件文件名（如 `1577.eml`） |
| `source_subject` | 来源邮件主题 |

> **注意**：`source_filename` 和 `source_subject` 已存入 ChromaDB metadata，支持按邮件文件名精确过滤查询。

---

## 扩展分类（V2）

### 业务分类（24 个）

| 分类 | 说明 | 典型场景 |
|------|------|---------|
| 调纸样 | 纸样调整、版型修改 | "纸样需要调整" |
| 核料 | 核料单、用料计算 | "核料单请确认" |
| 面辅料价格 | 面料/辅料价格确认 | "面料价格多少" |
| 工价 | 加工价格确认 | "工价确认" |
| 试身样 | 试穿样衣确认 | "试身样通过" |
| 修改样 | 修改后样衣确认 | "修改样确认" |
| 封样 | 封样确认、签字样 | "封样已确认" |
| 产前样 | 产前样确认 | "产前样通过" |
| 测试样 | 测试样确认 | "测试样通过" |
| 船样 | 船样确认、出货前样 | "船样通过" |
| 定面料 | 面料订购确认 | "定面料" |
| 定辅料 | 辅料订购确认 | "定辅料" |
| 产前会议 | 产前会议安排 | "产前会议" |
| 开裁 | 开裁安排 | "已安排开裁" |
| 验货 | 质量检查、验货 | "QC 验货通过" |
| 出货 | 出货安排、物流跟踪 | "已安排出货" |
| 补货 | 追加订单、补单 | "补货安排" |
| Lab Dip | 色卡确认、染色小样 | "Lab Dip 通过" |
| 大货样 | 大货产前样确认 | "大货样通过" |
| 样衣 | 样衣制作、试穿反馈 | "样衣已寄出" |
| 面料 | 面料确认、色卡 | "面料颜色确认" |
| 大货订单 | 大货生产订单 | "大货订单确认" |
| 一般沟通 | 日常业务沟通 | "请查收附件" |
| 其他 | 无法归类的业务 | - |

### 事件类型（15 个）

| 事件类型 | 说明 |
|---------|------|
| 提交 | 提交样衣/文件/资料 |
| 确认 | 确认通过/批准 |
| 回传 | 回传文件/资料 |
| 出货 | 安排/确认出货 |
| 延期申请 | 申请延期 |
| 给意见 | 给出修改意见 |
| 批复 | 批复申请 |
| 打样 | 安排打样 |
| 修改 | 修改样衣/设计 |
| 完成 | 完成某阶段 |
| 邮寄 | 样品/文件邮寄 |
| 等待反馈 | 等待客户/工厂回复 |
| 补货 | 追加订单、补单 |
| 抽查 | 质量抽查、随机检验 |
| 其他 | 其他事件类型 |

---

## 款号提取规则（V2）

基于全量 7359 封邮件分析，使用以下正则规则：

| 前缀 | 正则 | 示例 | 来源 | 占比 |
|------|------|------|------|------|
| CCSS | `\bCCSS\d{5,6}[A-Z]?\b` | CCSS230011, CCSS240158S | Everbelle | ~30% |
| INDO | `\bINDO[A-Z]\d{3,6}\b` | INDOT26919, INDOB26835 | Indochine | ~25% |
| AW | `\bAW\d{2}-[A-Z]+\d+\b` | AW25-KFWTS101 | 季节-类别编码 | ~15% |
| SS | `\bSS\d{2}[A-Z]+\d+\b` | SS25IACB201 | 季节编码 | ~5% |
| CCAW | `\bCCAW\d{5,6}\b` | CCAW230050 | Everbelle AW | ~5% |
| CDIB | `\bCDIB\d+\b` | CDIB18384 | 参考编号 | ~3% |
| P_SERIES | `\bP\d{3}-[A-Z0-9]+-\d+\b` | P009-H5L94-00001 | 面料编号 | ~2% |
| NL_STYLE | `\b\d{7}\b` | 9251268, 9290764 | New Look 系统 7 位款号 | ~15% |

> **注**：实际业务中 80%+ 款号为字母开头（CCSS/AW/INDO/CCAW/SS），纯数字订单号很少单独查询。

### 订单号提取规则

| 规则 | 正则 | 示例 | 过滤 |
|------|------|------|------|
| 6-9 位数字 | `\b\d{6,9}\b` | 310052, 2023621 | 排除 4 位年份（2024/2025）、排除日期格式（MMDD） |

---

## 关于系统邮件的处理策略

你的邮件中有大量来自 `editrack.com`（New Look 的 ediTRACK 系统）的自动邮件，例如：

- `Sample Feedback from New Look ediTRACK`（约 1700+ 封）
- `Additional Approvals Comments from New Look ediTRACK`（约 240+ 封）
- `Updated Purchase Orders from New Look on ediTRACK`（约 26 封）
- `PO Amendment Feedback`（约 22 封）

**处理策略：**
- **`Sample Feedback`** 类邮件内容极短（只有 "Sample Comments are now available..."），属于**纯提示型邮件**，会被短内容过滤自动移除
- **`Additional Approvals Comments`** / **`PO Amendment Feedback`** 类邮件包含具体表格、日期、审批意见、PO 变更记录，属于**高价值结构化数据**，会被保留并提取事件
- **业务关键词保护**：即使 ediTRACK 邮件很短，如果包含款号、订单号等业务信息，**强制保留**

这样既避免了 API 费用浪费，又保留了有价值的系统业务数据。

---

## 实际运行结果（V2）

本次运行统计：

| 指标 | 数值 |
|------|------|
| 原始邮件 | 7,359 封 |
| 过滤后有效邮件 | 2,492 封 |
| LLM 提取事件 | 9,533 个 |
| 高置信度通过 | 7,893 个 |
| 待人工复核 | 1,283 个 |
| 低置信度丢弃 | 357 个 |
| 覆盖款号 | 1,167 个 |
| 唯一订单号 | 1,188 个 |

### 事件分类分布（V2 - 扩展后）

| 分类 | 数量（参考） |
|------|------------|
| 出货 | 1,199 |
| 面料 | 910 |
| 一般沟通 | 590 |
| 大货订单 | 636 |
| 样衣 | 571 |
| 面辅料价格 | 488 |
| 定面料 | 470 |
| 测试样 | 365 |
| 核料 | 262 |
| 调纸样 | 221 |
| 定辅料 | 219 |
| Lab Dip | 214 |
| 修改样 | 210 |
| 产前样 | 199 |
| 工价 | 186 |
| 试身样 | 167 |
| 船样 | 121 |
| 封样 | 108 |
| 大货样 | 59 |
| 开裁 | 24 |
| 验货 | 17 |
| 补货 | 4 |

---

## 与知识图谱的协作

RAG 和知识图谱是互补关系：

| 能力 | RAG（本流水线） | 知识图谱 |
|------|----------------|---------|
| 存储内容 | 事件文本 + 向量嵌入 + metadata | 实体节点 + 关系边 |
| 查询方式 | 语义相似度检索 / 元数据精确过滤 | 精确关系遍历 |
| 优势场景 | "拉链的英文是什么"、"出货详情描述"、按款号+阶段过滤 | "CCSS230021 的客户是谁"、"Heidi 有哪些款号"、"某款号的所有订单号" |
| 数据量 | 7,893 事件 | 10,610 节点 / 34,328 关系 |
| 可过滤字段 | style_id, order_id, category, event_type, date, delay_days, party_from, party_to, **source_filename**, **source_subject** | 节点属性 + 关系属性 |

**典型协作流程：**
1. 用户查询 "CCSS230011 的进度如何"
2. 意图路由器判断为**时间线查询**
3. 知识图谱提供：客户（Heidi/Michelle）、工厂（东台鸿丰）、负责人（Tancy Qin）、**关联订单号**
4. RAG 提供：具体事件描述、延期原因、邮件原文片段、**原始邮件文件名和主题**
5. LLM 综合生成完整回答

**RAG 独立查询示例：**
```python
import chromadb
from chromadb.config import Settings

client = chromadb.PersistentClient(path='vector_db', settings=Settings(anonymized_telemetry=False))
coll = client.get_collection('email_events_new')

# 按款号查询
results = coll.get(where={"style_id": "CCAW240015"}, include=["documents", "metadatas"])

# 按款号 + 阶段查询
results = coll.get(where={"$and": [
    {"style_id": "CCAW240015"},
    {"category": "船样"}
]}, include=["metadatas"])

# 按邮件文件名查询（追溯原始邮件）
results = coll.get(where={"source_filename": "1577.eml"}, include=["metadatas"])

# metadata 包含：style_id, order_id, category, event_type, date, 
#   related_date, delay_days, party_from, party_to, confidence,
#   source_filename, source_subject
```

---

## 后续步骤

完成本流水线后，下一步是：

1. **复核 `events_review.jsonl`**：将确认无误的事件补充进 `events_passed.json`，重新运行入库
2. **构建知识图谱**：基于 `events_passed.json` + `factory_mapping.csv` + `organization.json` + `email_summary.json` 构建邮件知识图谱
3. **两阶段检索测试**：验证 `style_id` 过滤 + 向量语义检索 + `category/date` 聚合的效果
4. **端到端测试**：验证微调模型 + RAG + KG 的完整链路

## ChromaDB Metadata 字段说明

`email_events_new` collection 的每条记录包含以下 metadata 字段：

| 字段 | 类型 | 说明 | 可过滤 |
|------|------|------|--------|
| `style_id` | string | 款号 | ✅ |
| `order_id` | string | 订单号 | ✅ |
| `category` | string | 业务阶段 | ✅ |
| `event_type` | string | 事件类型 | ✅ |
| `date` | string | 事件日期 (YYYY-MM-DD) | ✅ |
| `related_date` | string | 计划/对比日期 | ✅ |
| `delay_days` | int | 延期天数 | ✅ |
| `party_from` | string | 发起方 | ✅ |
| `party_to` | string | 接收方 | ✅ |
| `confidence` | float | 提取置信度 | ✅ |
| `source_filename` | string | 来源邮件文件名 | ✅ |
| `source_subject` | string | 来源邮件主题 | ✅ |

> **注意**：ChromaDB 的 `where` 过滤仅支持精确匹配和 `$and`/`$or` 组合，不支持数值范围（如 `delay_days > 0`）或日期范围。需要范围查询时，建议先按 `style_id` 召回，再用 Python 过滤。
