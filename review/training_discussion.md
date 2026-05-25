# 时间线推理 LoRA 微调技术讨论记录

> 讨论时间: 2026-04-21 ~ 2026-04-22
> 模型: Qwen/Qwen2.5-7B-Instruct
> 训练框架: LLaMA-Factory v0.9.5
> 硬件: NVIDIA RTX A6000 48GB

---

## 一、训练配置与执行

### 1.1 最终配置

```yaml
# 阶段配置
stage: sft
do_train: true

# 模型配置
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
template: qwen

# 数据配置
dataset: timeline_reasoning
cutoff_len: 4096

# 输出配置
output_dir: ./outputs/timeline-reasoning-lora
logging_steps: 10
save_steps: 5

# 训练配置
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
learning_rate: 5.0e-5
num_train_epochs: 3.0
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true

# LoRA配置
finetuning_type: lora
lora_target: all
lora_rank: 64
lora_alpha: 128
lora_dropout: 0.05
use_rslora: false
```

### 1.2 踩坑记录

| 问题 | 原因 | 解决 |
|------|------|------|
| `load_best_model_at_end` 报错 | eval 和 save 策略不匹配 | 注释掉验证相关配置 |
| `lora_use_rslora` / `deiang_mode` 报错 | 参数名错误或不存在 | 改为 `use_rslora`，删除 `deiang_mode` |
| `Undefined dataset` | `dataset_info.json` 未复制到服务器 | 复制到 LLaMA-Factory data 目录 |
| 输出目录为空 | `save_steps=100` > 总步数 33 | 改为 `save_steps=5` |
| 训练没执行 | 缺少 `stage: sft` 和 `do_train: true` | 添加阶段配置 |
| OOM (24GB) | bs=2 + seq=4096 + r=64 超显存 | 升级到 A6000 48GB |

---

## 二、数据量问题：198 条 SFT 数据够用吗？

### 2.1 数据金字塔

```
原始邮件          7,000+ 封
    │
    ▼  提取、清洗、结构化
事件数据          4,600+ 条（email_rag_pipeline）
    │
    ▼  筛选、去重、格式化
SFT 训练数据      198 条（timeline_train.jsonl）
    │
    ▼  微调
LoRA Adapter      616 MB
```

### 2.2 为什么 198 条够用

| 因素 | 说明 |
|------|------|
| 任务单一 | 只做"时间线整理+延期分析"，不是通用对话 |
| 输出格式固定 | Markdown 表格 + 根因结论，模式高度结构化 |
| LoRA 高效 | 只训练 616MB 参数，不是全量微调 |
| 数据质量高 | 基于真实业务事件，非合成数据 |
| Base 模型强 | Qwen2.5-7B 已有强大的中文理解和表格生成能力 |

### 2.3 Loss 曲线

| Step | Epoch | Loss | Learning Rate |
|------|-------|------|---------------|
| 10 | 0.90 | 0.2735 | 4.70e-5 |
| 20 | 1.72 | 0.0681 | 2.75e-5 |
| 30 | 2.54 | 0.0195 | 5.67e-6 |

Loss 下降 93%，说明模型学会了固定模式。

### 2.4 企业内部复用条件

**✅ 适合**：任务边界清晰、输出格式固定、Base 模型能覆盖基础能力、数据质量可控

**⚠️ 风险**：
- 过拟合到训练款号（90 个）
- 时间漂移（新季节款号格式变化）
- 边界 case 覆盖不足
- 多轮对话能力弱（单轮 QA 训练）

---

## 三、LoRA 参数、验证方法、学习率调度

### 3.1 LoRA 参数选择逻辑

| 条件 | 情况 | 选择 |
|------|------|------|
| 数据量 | 198 条，少 | r=64 中等偏大，防过拟合不能更大 |
| 任务复杂度 | 单一任务，固定格式 | 不需要全量微调 |
| Base 模型 | Qwen2.5-7B 很强 | 只需"引导"输出格式 |
| 算力 | A6000 48GB | 可以支持 r=64 |

**α/r = 2.0** 是经验默认值，适合需要较强引导信号的场景。

### 3.2 验证方法

数据量太少（198 条），自动评估统计意义不大。推荐：

1. **格式检查**（自动化）：是否含 Markdown 表格、是否有根因结论
2. **人工抽检**（业务人员）：时间线逻辑、延期归因合理性
3. **冷启动测试**（关键）：训练集外的款号，测试泛化能力

### 3.3 学习率调度

```yaml
learning_rate: 5.0e-5      # LoRA 常用值，比全量微调高
lr_scheduler_type: cosine   # 平滑，适合短训练
warmup_ratio: 0.1           # 36 steps 中 warmup 3 步
```

选择逻辑：数据少 → lr 不能太低；LoRA → 可用比全量更高的 lr；步数少 → cosine 足够。

---

## 四、增量微调：效果不理想 vs 新季节数据

### 4.1 两类问题的区别

| 场景 | 原因 | 解决思路 |
|------|------|----------|
| 效果不理想 | 模型没学好（欠拟合/过拟合/分布外） | 诊断 → 针对性修复 → 重训 |
| 新季节数据 | 数据分布变化（时间漂移） | 增量训练 → 合并新旧数据 |

### 4.2 推荐方案：全量重训 + RAG 兜底

```
原始邮件 → 事件提取 → 质量过滤 → 种子筛选 → QA 构造 → 人工抽检 → SFT
   ↑________________________________________________________↓
                        定期回流（每月/每季）
```

**为什么推荐全量重训**：
- 数据量小（198 → 300-400），重训只要 20 分钟
- 避免灾难性遗忘
- 数据质量可控
- 可复现

### 4.3 Error Analysis 流程（针对效果不理想）

```
用户投诉
    │
    ▼
还原链路：邮件 → 事件 → Prompt → 输出
    │
    ▼
定位错误环节：
    ├── A. 事件提取错（RAG pipeline）
    ├── B. Prompt 格式错（截断/排序）
    └── C. 模型输出错（格式/事实/编造）
    │
    ▼
针对性修复：
    ├── A → 修 build_email_event_rag.py
    ├── B → 修 build_timeline_dataset.py
    └── C → 补充训练样本，全量重训
```

### 4.4 Active Learning 闭环

```
线上运行
    │
    ▼
自动监控（validate_output）发现错误
    │
    ▼
人工确认（业务人员判断类型 A/B/C）
    │
    ▼
自动归类入库（提取问题库 / 训练候选集）
    │
    ▼
定期（每周/每月）：
    ├── 提取问题库 → 修 pipeline
    └── 训练候选集达 N 条 → 触发全量重训
```

---

## 五、关键原则总结

| 原则 | 说明 |
|------|------|
| 数据驱动 | 不凭感觉调模型，先看 badcase 是数据问题还是模型问题 |
| 全量优于增量 | 数据量小，全量重训成本极低，效果更好 |
| 版本管理 | 每个季节保留一个 adapter 版本，可回滚 |
| RAG 兜底 | 模型学"格式和模式"，具体事实查 RAG，减少重训压力 |
| 低成本迭代 | 198 条数据重训 20 分钟，修 pipeline 比调模型快 |

---

## 六、输出文件说明

| 文件 | 说明 |
|------|------|
| `debug_style.py` | 还原某款号的完整处理链路，定位错误环节 |
| `validate_output.py` | 自动检查模型输出的格式、一致性、完整性 |
| `training_discussion.md` | 本文件，技术讨论记录 |
