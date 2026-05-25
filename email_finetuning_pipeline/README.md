# 邮件数据微调流水线 (Email Finetuning Pipeline)

三模型微调系统：V3 调度器 → V2 查询引擎 → V1 时间线生成，均已训练完成并达到初版上线标准。

> 基座模型：Qwen/Qwen2.5-7B-Instruct  
> 训练框架：LLaMA-Factory 0.9.5.dev0  
> 训练服务器：NVIDIA RTX PRO 6000 (96GB)  
> 最后更新：2026-05-13


---

## 模型架构

```
用户提问
    │
    ▼
┌─────────────────────────────────────────┐
│  V3 调度器 (Scheduler)                   │
│  - 判断：直接回答 / V2 查询 / V1 分析     │
│  - 输出：{"decision": "route_v2|route_v1|direct_answer"} │
└─────────────────────────────────────────┘
    │
    ├──→ route_v2 ──→ V2 查询引擎 ──→ 多轮工具调用 ──┐
    │    - 查询策略生成                                │
    │    - 满足度判断 (satisfied)                      │
    │    - 工具调用 (function_calls)                   │
    │    - 查询链支持                                  │
    │                                                  │
    ├──→ route_v1 ──→ V1 时间线生成 ──→ 结构化报告 ──┤
    │    - 事件整理为 Markdown 表格                     │
    │    - 延期根因分析                                 │
    │    - 风险分级                                     │
    │                                                  │
    └──→ direct_answer ──→ 直接回答 ─────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  结果整合     │
                    │  生成最终回答 │
                    └──────────────┘
```

| 模型 | 职责 | 训练方式 | 状态 |
|-----|------|---------|------|
| **V3** | 意图识别 + 路由决策 | SFT + DPO | ✅ 可用 |
| **V2** | 多轮查询策略 + 工具调用 | SFT + DPO | ✅ 可用 |
| **V1** | 时间线整理 + 延期分析 | SFT | ✅ 可用 |

---

## 训练结果

### V3 调度器

| 阶段 | train_loss | eval_loss | 关键指标 |
|-----|-----------|-----------|---------|
| SFT | 0.296 | 0.0337 | 2 epoch 极速收敛 |
| DPO | 0.013 | 0.0052 | **accuracy 100%, margin 10.34** |

- 数据：800 条（route_v2 43%, route_v1 40%, direct_answer 12%, boundary 5%）
- 最佳 checkpoint：SFT step 200, DPO step 225
- 序列长度：平均 85 tokens，最大 111 tokens
- V3 SFT 配置：`cutoff_len: 1024`, `lora_rank: 8`, `lora_alpha: 16`, `LR: 1.0e-4`

### V2 查询引擎

| 阶段 | train_loss | eval_loss | 关键指标 |
|-----|-----------|-----------|---------|
| SFT | 0.277 | 0.3159 | eval 持续下降后平稳 |
| DPO | 0.021 | 0.0147 | **accuracy 100%, margin 8.51** |

- 数据：786 条 SFT, 776 对 DPO
- 最佳 checkpoint：SFT step 175, DPO step 243
- 序列长度：平均 7,500 tokens，最大 88K tokens（8192 cutoff）
- 多轮分布：2 轮 44%, 3 轮 26%, 4 轮 14%, 5+ 轮 16%

### V1 时间线生成

| 阶段 | train_loss | eval_loss | 关键指标 |
|-----|-----------|-----------|---------|
| SFT | 0.288 | **0.2784** | eval_gap 仅 -0.010 |

- 数据：500 条
- 最佳 checkpoint：step 125（约 2 epoch）
- 序列长度：平均 2,400 tokens，95% < 6144, 99% < 8192

---

## 项目结构

```
email_finetuning_pipeline/
├── README.md                           # 本文件
├── TRAINING_RESULTS_V1_V2_V3.md        # 详细训练结果分析
├── FINETUNE_CHECKLIST.md               # 微调检查清单
├── configs/                            # 训练配置
│   ├── dataset_info.json               # 数据集注册
│   ├── sft_v1_timeline_lora.yaml       # V1 SFT 配置
│   ├── sft_v2_multi_round_config.yaml  # V2 SFT 配置
│   ├── dpo_v2_multi_round_config.yaml  # V2 DPO 配置
│   ├── sft_v3_scheduler_config.yaml    # V3 SFT 配置
│   └── dpo_v3_scheduler_config.yaml    # V3 DPO 配置
├── datasets/                           # 数据集
│   ├── train/
│   │   ├── sft_v1_timeline.jsonl       # V1 SFT 训练 (500条)
│   │   ├── sft_v2_multiround.jsonl     # V2 SFT 训练 (786条)
│   │   ├── dpo_v2_multiround.jsonl     # V2 DPO 训练 (776对)
│   │   ├── sft_scheduler_v3.jsonl      # V3 SFT 训练 (800条)
│   │   └── dpo_scheduler_v3.jsonl      # V3 DPO 训练 (800对)
│   ├── val/                            # 验证集
│   └── test/                           # 测试集
├── outputs/                            # 训练输出
│   ├── sft-v1/checkpoint-125           # V1 SFT 最佳模型
│   ├── sft-v2/checkpoint-175           # V2 SFT 最佳模型
│   ├── dpo-v2/checkpoint-243           # V2 DPO 最佳模型
│   ├── sft-v3/checkpoint-200           # V3 SFT 最佳模型
│   └── dpo-v3/checkpoint-225           # V3 DPO 最佳模型
├── src/                                # 数据生成脚本
│   ├── extract_v2_questions.py
│   ├── validate_v2_questions.py
│   ├── build_v2_dataset.py
│   ├── build_v1_timeline_dataset.py
│   └── build_v3_scheduler_dataset.py
├── scripts/                            # 辅助脚本
│   ├── merge_lora.py                   # 合并 LoRA 到完整模型
│   ├── test_lora_direct.py             # 直接测试 LoRA 权重
│   ├── start_vllm_servers.sh           # vLLM 多模型服务启动
│   └── train.sh                        # 旧版 V1 一键训练（已过时）
└── evaluation/                         # 评估
    ├── test_end_to_end.py
    └── test_cases.json
```

---

## 快速开始

### 训练（如需重新训练）

```bash
# V1 SFT
llamafactory-cli train configs/sft_v1_timeline_lora.yaml

# V2 SFT
llamafactory-cli train configs/sft_v2_multi_round_config.yaml

# V2 DPO
llamafactory-cli train configs/dpo_v2_multi_round_config.yaml

# V3 SFT
llamafactory-cli train configs/sft_v3_scheduler_config.yaml

# V3 DPO
llamafactory-cli train configs/dpo_v3_scheduler_config.yaml
```

> 注：`scripts/train.sh` 为旧版 V1 单模型一键脚本，当前三模型请使用上述独立命令。

### 推理加载

```python
# V3 调度器（示例）
from llamafactory.chat import ChatModel

model = ChatModel(
    model_name_or_path="Qwen/Qwen2.5-7B-Instruct",
    adapter_name_or_path="./outputs/dpo-v3/checkpoint-225",
    template="qwen"
)
```

---

## 模型输出格式

### V3 调度器

```json
{
  "thought": "用户询问款号进度，包含款号 8859114，应路由到 V1",
  "decision": "route_v1",
  "style_id": "8859114"
}
```

### V2 查询引擎

```json
{
  "thought": "已获取 total_styles=253，直接满足用户问题",
  "satisfied": true,
  "function_calls": [
    {
      "name": "generate_answer",
      "params": {"template": "my_styles_count", "data": {"total_styles": 253}}
    }
  ]
}
```

### V1 时间线生成

Markdown 表格 + 风险分析 + 关键路径（详见 V1 数据规范）

---

## 三模型对比

| 维度 | V1 | V2 | V3 |
|------|-----|-----|-----|
| **任务** | 结构化生成 | 多轮决策 | 三分类路由 |
| **复杂度** | 中 | 高 | 低 |
| **平均长度** | ~2,400 tokens | ~7,500 tokens | ~85 tokens |
| **SFT eval_loss** | 0.2784 | 0.3159 | 0.0337 |
| **SFT eval_gap** | -0.010 ✅ | +0.039 | -0.262 |
| **DPO accuracy** | N/A | **100%** | **100%** |
| **DPO margin** | N/A | 8.51 | **10.34** |
| **训练时长(SFT)** | ~47min | ~1.3h | ~1.7min |
| **训练时长(DPO)** | N/A | ~2.3h | ~9min |
| **数据量** | 500 | 786 | 800 |
| **是否需要 RL** | 否 | DPO 已足够 | DPO 已足够 |

---

## 后续优化方向

| 优先级 | 方向 | 预期效果 |
|-------|------|---------|
| 1 | **收集线上 bad case，扩充训练数据** | 持续提升泛化能力 |
| 2 | **V2 数据预处理（超长样本截断问题）** | loss -0.03 ~ -0.05 |
| 3 | **V2 rank 提升到 32** | 增强复杂决策表达能力 |
| 4 | **基座模型升级到 14B/32B** | 大幅提升，但成本高 |
| 5 | **V3 类别平衡（增加 boundary 样本）** | 提升拒答能力 |

---

## 参考文档

- `TRAINING_RESULTS_V1_V2_V3.md` — 详细训练结果与曲线分析
- `configs/` — 所有训练配置
- `V3_ROUTING_RULES.md` — V3 路由规则（v2.0 极简版）
- `V3_ROUTE_V1_IMPLEMENTATION_PLAN.md` — V3 v2.0 简化方案
- `V2_CAPABILITY_DESIGN.md` — V2 能力设计文档
- `V1_DATA_SPEC.md` — V1 输入输出格式规范
- `email_agent/` — 上游推理系统（V3→V2→V1 调用链路）
