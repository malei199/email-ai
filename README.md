# 服装行业 AI 解决方案

面向服装跟单团队的内部智能助手系统，基于 **vLLM + 多 LoRA 微调模型 + 双轨 RAG + 知识图谱**。

> 基座模型：Qwen/Qwen2.5-7B-Instruct  
> 训练框架：LLaMA-Factory 0.9.5.dev0  
> 最后更新：2026-05-13

---

## 📦 项目结构

```
.
├── email_agent/                   # 邮件智能助手 Web 应用（FastAPI + SSE）
│   ├── main.py                          # FastAPI 入口
│   ├── config.py                        # 全局配置（vLLM 地址、模型参数、system prompt）
│   ├── database.py                      # SQLite ORM（含 OmittedData 续查表）
│   ├── HISTORY_DESIGN.md                # 分页续查架构设计
│   ├── API_REFERENCE.md                 # 本地查询接口总览
│   ├── models/                          # Pydantic 模型（auth/chat/feedback/morning_push/style）
│   ├── routers/                         # API 路由（auth/morning_push/chat/styles/feedback/sessions）
│   ├── services/                        # 业务逻辑
│   │   ├── auth_service.py              # 认证服务（UUID Token）
│   │   ├── morning_push_service.py      # 早推送生成
│   │   ├── kg_adapter.py                # KG 查询封装（12 个接口）
│   │   ├── rag_adapter.py               # RAG 查询封装（术语 RAG + 邮件事件 RAG）
│   │   ├── vllm_client.py               # vLLM OpenAI API 客户端（v1/v2/v3）
│   │   ├── v2_executor.py               # V2 function_calls 执行引擎（查询链 + result 过滤）
│   │   ├── v1_model_adapter.py          # V1 模型适配器（Markdown 报告生成）
│   │   ├── query_orchestrator.py        # 联合查询编排器（5 类路由 + 歧义消解）
│   │   ├── answer_generator.py          # V2 回答生成器（模板化 Markdown）
│   │   ├── context_manager.py           # Token 估算与上下文管理
│   │   └── result_truncator.py          # 结果截断工具（6 种策略 + 续查支持）
│   ├── agents/                          # Agent 核心
│   │   ├── intent_router.py             # V3 意图路由（基于微调模型 + 续查关键词检测）
│   │   ├── chat_agent.py                # 对话主入口（V1/V2/续查/直接回答）
│   │   ├── v1_orchestrator.py           # V1 外部编排器（多轮事件→Markdown 合并）
│   │   ├── v2_orchestrator.py           # V2 多轮查询编排器（messages 列表格式）
│   │   └── answer_builder.py            # 回答组装器（简洁/详细模式）
│   ├── test/                            # 测试套件
│   └── static/                          # 前端文件（登录页/主界面/对话/SSE 处理）
│
├── email_term_rag_pipeline/       # 术语 RAG 流水线（PDF 词典 → 向量库）
│   ├── src/
│   │   ├── extract_pdf_terms.py         # PDF 全量术语提取（491页，断点恢复+分类识别）
│   │   ├── build_term_kb.py             # ChromaDB 向量库构建
│   │   └── rag_qa.py                    # 术语检索与问答服务
│   ├── scripts/run_term_pipeline.sh     # 术语 RAG 一键构建
│   ├── configs/                         # 提取与建库配置
│   └── output/                          # 提取统计与建库报告
│
├── vector_db/                     # 共享向量数据库（ChromaDB）
│   ├── clothing_terms                   # 21,686 条服装术语
│   ├── email_events_new                 # 7,893 条邮件事件（V2 最新）
│   └── email_events                     # 4,668 条邮件事件（V1 旧版，兼容保留）
│
├── email_rag_pipeline/            # 邮件事件 RAG 构建流水线
│   ├── pre_filter_emails.py             # 前置过滤（V2 - 款号感知/去重/黑名单）
│   ├── build_email_event_rag.py         # LLM 提取 → 质量过滤 → 向量入库
│   ├── test_timeline_rag.py             # RAG 检索测试脚本
│   ├── scripts/run_full_pipeline.sh     # 邮件 RAG 一键构建
│   ├── src/term_rag_integration.py      # 术语RAG集成（邮件术语识别翻译）
│   └── output/new/                      # 事件数据、过滤统计、处理报告
│       ├── filtered_email_manifest.jsonl
│       ├── filter_stats.json
│       ├── events_raw.jsonl
│       ├── events_passed.json
│       ├── events_review.jsonl
│       └── processing_stats.json
│
├── email_kg_pipeline/             # 邮件知识图谱（NetworkX）
│   ├── src/
│   │   ├── kg_builder.py                # 图谱构建器（支持 Customer 节点）
│   │   ├── kg_query.py                  # 查询引擎（支持 Customer 查询）
│   │   └── kg_updater.py                # 增量更新器
│   ├── scripts/run_build.sh             # 一键构建脚本
│   ├── configs/schema.json              # 图谱 Schema 定义
│   ├── data/                            # 工厂映射 + 组织架构
│   └── output/
│       ├── kg_graph_with_customers.pkl  # 序列化图谱文件
│       └── kg_stats.json                # 图谱统计信息
│
├── email_finetuning_pipeline/     # 三模型微调流水线
│   ├── configs/                         # LLaMA-Factory 训练配置
│   │   ├── sft_v1_timeline_lora.yaml    # V1 SFT 配置
│   │   ├── sft_v2_multi_round_config.yaml # V2 SFT 配置
│   │   ├── dpo_v2_multi_round_config.yaml # V2 DPO 配置
│   │   ├── sft_v3_scheduler_config.yaml   # V3 SFT 配置
│   │   ├── dpo_v3_scheduler_config.yaml   # V3 DPO 配置
│   │   └── dataset_info.json            # 数据集注册
│   ├── datasets/                        # 数据集
│   │   ├── train/
│   │   │   ├── sft_v1_timeline.jsonl    # V1 SFT 训练 (500条)
│   │   │   ├── sft_v2_multiround.jsonl  # V2 SFT 训练 (786条)
│   │   │   ├── dpo_v2_multiround.jsonl  # V2 DPO 训练 (776对)
│   │   │   ├── sft_scheduler_v3.jsonl   # V3 SFT 训练 (800条)
│   │   │   └── dpo_scheduler_v3.jsonl   # V3 DPO 训练 (800对)
│   │   ├── val/                         # 验证集
│   │   └── test/                        # 测试集
│   ├── outputs/                         # 训练输出
│   │   ├── sft-v1/checkpoint-125        # V1 SFT 最佳模型
│   │   ├── sft-v2/checkpoint-175        # V2 SFT 最佳模型
│   │   ├── dpo-v2/checkpoint-243        # V2 DPO 最佳模型
│   │   ├── sft-v3/checkpoint-200        # V3 SFT 最佳模型
│   │   └── dpo-v3/checkpoint-225        # V3 DPO 最佳模型
│   ├── src/                             # 数据生成脚本
│   │   ├── build_v1_timeline_dataset.py
│   │   ├── build_v2_dataset.py
│   │   ├── build_v3_scheduler_dataset.py
│   │   ├── extract_v2_questions.py
│   │   └── validate_v2_questions.py
│   ├── scripts/                         # 辅助脚本
│   │   ├── merge_lora.py                # 合并 LoRA 到完整模型
│   │   ├── test_lora_direct.py          # 直接测试 LoRA 权重
│   │   ├── start_vllm_servers.sh        # vLLM 多模型服务启动
│   │   └── train.sh                     # 旧版 V1 一键训练（已过时）
│   └── evaluation/                      # 端到端评估
│       ├── test_end_to_end.py
│       └── test_cases.json
│
├── data/                          # 数据目录
│   ├── eml_files/                       # 原始邮件 (*.eml) — 7,359 封
│   ├── data-summary/                    # 邮件摘要（用于客户数据提取）
│   ├── processed/                       # 格式转换后的训练数据
│   ├── processed_data/                  # 中间处理数据
│   └── pdf/
│       └── 汉英英汉服装分类词汇.pdf       # 服装术语词典（491页）
│
├── DATA_ORGANIZATION.md           # 数据文件组织说明
├── EMAIL_RAG_STRATEGY.md          # 邮件 RAG 策略设计文档
├── MEMORY_SYSTEM_DESIGN.md        # 记忆系统设计文档
├── kg_email_detail.py             # 邮件详情知识图谱脚本
└── demo_conversation.md           # 演示对话
```

---

## 🚀 快速开始

### 1. 术语 RAG（服装词汇检索）

```bash
# 一键构建术语知识库（约 8-12 分钟）
./email_term_rag_pipeline/scripts/run_term_pipeline.sh

# 测试查询
python email_term_rag_pipeline/scripts/quick_test.py
```

### 2. 邮件事件 RAG（业务时间线追踪）

```bash
# 配置 API Key
export DEEPSEEK_API_KEY="your-api-key"

# 前置过滤（强烈建议先跑）
python email_rag_pipeline/pre_filter_emails.py

# 一键全量构建（约 1.5~2 小时，费用约 15~40 元）
./email_rag_pipeline/scripts/run_full_pipeline.sh
```

### 3. 知识图谱构建

```bash
# 一键构建（含 Customer 节点）
./email_kg_pipeline/scripts/run_build.sh
```

### 4. 模型微调（如需重新训练）

```bash
# V1 SFT
llamafactory-cli train email_finetuning_pipeline/configs/sft_v1_timeline_lora.yaml

# V2 SFT + DPO
llamafactory-cli train email_finetuning_pipeline/configs/sft_v2_multi_round_config.yaml
llamafactory-cli train email_finetuning_pipeline/configs/dpo_v2_multi_round_config.yaml

# V3 SFT + DPO
llamafactory-cli train email_finetuning_pipeline/configs/sft_v3_scheduler_config.yaml
llamafactory-cli train email_finetuning_pipeline/configs/dpo_v3_scheduler_config.yaml
```

### 5. 启动智能助手 Web 应用

```bash
# 确保 vLLM 服务已启动（单实例多 LoRA 模式）
vllm serve <base_model_path> \
  --enable-lora \
  --lora-modules v3=<v3_lora_path> v2=<v2_lora_path> v1=<v1_lora_path> \
  --max-lora-rank 64 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --port 8001

# 配置 vLLM 地址
# 编辑 email_agent/config.py: VLLM_BASE_URL = "http://localhost:8001/v1"

# 安装依赖并启动
pip install -r email_agent/requirements.txt
python -m email_agent.main
# 或 uvicorn email_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后访问 http://localhost:8000

---

## 📊 核心数据指标

| 模块 | 指标 | 数值 |
|------|------|------|
| **原始邮件** | 总量 | **7,359 封** |
| **过滤后邮件** | 有效邮件 | **2,492 封** |
| **邮件事件** | LLM 提取事件 | **9,533 个** |
| **邮件事件** | 高置信度事件（入向量库） | **7,893 个** |
| **邮件事件** | 待人工复核 | **1,283 个** |
| **邮件事件** | 低置信度丢弃 | **357 个** |
| **邮件事件** | 覆盖款号数 | **1,167 个** |
| **邮件事件** | 唯一订单号 | **1,188 个** |
| **术语词条** | 向量库总量 | **21,686 条** |
| **术语词条** | 来源 | 《汉英英汉服装分类词汇》491页 |
| **知识图谱** | 节点总数 | **10,610** |
| **知识图谱** | 关系总数 | **34,328** |
| **知识图谱** | 客户节点 | **27** |
| **微调数据** | V1 SFT | **500 条** |
| **微调数据** | V2 SFT / DPO | **786 条 / 776 对** |
| **微调数据** | V3 SFT / DPO | **800 条 / 800 对** |

---

## 🏗️ 系统架构：三模型协作 + 双轨 RAG + 知识图谱

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

| 模型 | 职责 | 训练方式 | 状态 | max_tokens |
|------|------|---------|------|-----------|
| **V3** | 意图调度 | SFT + DPO | ✅ 可用 | 300 |
| **V2** | 查询策略 + 工具调用 | SFT + DPO | ✅ 可用 | 8000 |
| **V1** | 时间线分析 + 延期根因 | SFT | ✅ 可用 | 4000 |

### 三模型对比

| 维度 | V1 | V2 | V3 |
|------|-----|-----|-----|
| **任务** | 结构化生成 | 多轮决策 | 三分类路由 |
| **复杂度** | 中 | 高 | 低 |
| **平均长度** | ~2,400 tokens | ~7,500 tokens | ~85 tokens |
| **SFT eval_loss** | 0.2784 | 0.3159 | 0.0337 |
| **SFT eval_gap** | -0.010 ✅ | +0.039 | -0.262 |
| **DPO accuracy** | N/A | **100%** | **100%** |
| **DPO margin** | N/A | 8.51 | **10.34** |
| **数据量** | 500 | 786 | 800 |

### 为什么分两个 RAG？

| 维度 | 术语 RAG | 邮件事件 RAG |
|------|---------|-------------|
| 数据形态 | 结构化词条（中/英/分类） | 非结构化业务事件（含时间/款号/阶段） |
| 检索目标 | 精准匹配、Top-1 即可 | 语义相关、需多片段聚合 |
| 答案类型 | 翻译、定义 | 流程说明、时间线、延期根因 |
| 更新频率 | 低（词典固定） | 高（新邮件持续产生） |
| 核心场景 | "拉链的英文是什么？" | "款号 INDOT27551 为什么延期？" |

---

## 🎯 核心能力

### 术语检索（RAG）
- **中英双语互查**：支持中文 → 英文、英文 → 中文
- **语义模糊匹配**："coat 相关词汇" → 大衣、毛皮大衣、军大衣
- **分类过滤**：按 8 个主要分类检索

### 邮件事件追踪（RAG）
- **款号时间线聚合**：跨 5~20 封邮件聚合同一款号的全流程事件
- **延期根因分析**：对比计划时间 vs 实际时间，定位关键瓶颈
- **多阶段覆盖**：Lab Dip、大货样、样衣、封样、出货等 24 个业务分类

### 知识图谱查询
- **人员-款号关联**："Paula Cheng 负责哪些款号"
- **客户-款号关联**："Heidi 有哪些款号"
- **工厂延期统计**：全局聚合分析
- **组织架构遍历**："Paula 的下属"

### 智能助手 Web 应用
- **每日早推送**：上班时自动展示负责款号的风险提醒和昨日动态
- **对话式查询**：术语翻译、款号进度、延期分析、人员查询
- **深度个性化**：基于邮箱号关联 KG 人员数据，展示"我负责的款号"
- **来源溯源**：每个回答附带数据来源（KG 查询 / RAG 检索 / 术语库）
- **反馈机制**：👍/👎 点赞点踩，数据回流优化
- **分页续查**：查询结果过多时自动截断，支持"继续"、"剩下的"等续查指令

---

## 💡 典型使用场景

### 场景 1：快速查询术语
> "拉链的英文怎么说？"

使用 **术语 RAG**，无需训练，即开即用。

### 场景 2：款号延期根因追踪
> "款号 INDOT27551，工厂要求延期，帮我查一下是哪个环节导致的。"

**结合邮件事件 RAG + 知识图谱 + V1 时间线模型**：
1. 知识图谱提供：客户、工厂、负责人、关联订单号
2. RAG 提供：具体事件描述、延期原因、邮件原文片段
3. V1 模型生成结构化 Markdown 表格 + 根因分析

### 场景 3：对话式智能助手
> "我跟的款号进度怎么样"

**V3→V2 多轮查询**：
1. V3 路由到 V2（无款号）
2. V2 调用 `kg_query.my_styles` 获取款号列表
3. V2 调用 `kg_query.style_summaries` 获取各款号摘要
4. 生成 Markdown 回答

---

## 📚 详细文档

| 文档 | 内容 |
|------|------|
| [邮件智能助手](email_agent/README.md) | Web 应用架构、三模型协作、API 接口、分页续查设计 |
| [术语 RAG 流水线](email_term_rag_pipeline/README.md) | PDF 术语提取、ChromaDB 建库、检索问答 |
| [邮件 RAG 流水线](email_rag_pipeline/README.md) | 邮件过滤、LLM 事件提取、ChromaDB 入库、扩展分类 |
| [知识图谱](email_kg_pipeline/README.md) | NetworkX 图谱构建、查询引擎、Customer 节点、增量更新 |
| [微调流水线](email_finetuning_pipeline/README.md) | V1/V2/V3 训练结果、LLaMA-Factory 配置、数据生成 |
| [数据组织说明](DATA_ORGANIZATION.md) | 数据目录结构、处理流程、路径引用 |
| [RAG 策略设计](EMAIL_RAG_STRATEGY.md) | 双轨架构设计、事件提取策略、微调方向 |
| [记忆系统设计](MEMORY_SYSTEM_DESIGN.md) | 记忆系统架构设计 |

---

## ⚠️ 注意事项

1. **首次运行术语 RAG**：需下载 BGE 嵌入模型（约 1-2GB），国内用户建议 `export HF_ENDPOINT=https://hf-mirror.com`
2. **首次运行邮件 RAG**：需配置 `DEEPSEEK_API_KEY`，全量提取费用约 15-40 元
3. **首次运行微调**：需下载基础模型（约 14GB for 7B 模型）
4. **macOS OpenMP 报错**：已内置 `KMP_DUPLICATE_LIB_OK=TRUE` 修复
5. **存储空间**：建议预留 100GB+

---

## 🔧 系统要求

| 组件 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 4核 | 8核+ |
| 内存 | 16GB | 32GB+ |
| GPU | 无需（推理可远程） | RTX 3090 / A100 |
| 存储 | 10GB | 100GB+ |

---

## 📄 License

MIT License
