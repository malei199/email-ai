# 微调方案完整性检查清单

> ⚠️ **本文档已过时**，反映的是早期 V1 单模型 pipeline 状态。当前三模型（V1/V2/V3）pipeline 请参考 `README.md` 和 `TRAINING_RESULTS_V1_V2_V3.md`。

> 用于确认所有文件和配置就绪，可直接上传到算力平台训练

---

## 一、数据文件 ✅

| 文件 | 路径 | 数量 | 大小 | 状态 |
|------|------|------|------|------|
| 训练集 | `datasets/timeline_train.jsonl` | 198 条 | 913.7 KB | ✅ |
| 验证集 | `datasets/timeline_val.jsonl` | 23 条 | 120.6 KB | ✅ |
| 黄金样本 | `datasets/timeline_gold_samples.jsonl` | 221 条 | 1034.3 KB | ✅ |

**数据格式**: ShareGPT (ChatML) 格式
```json
{
  "style_id": "CCSS240146",
  "mode": "general",
  "messages": [
    {"role": "system", "content": "你是服装行业业务分析师..."},
    {"role": "user", "content": "款号: CCSS240146\n事件记录：..."},
    {"role": "assistant", "content": "## 款号 CCSS240146 时间线梳理..."}
  ]
}
```

**模式分布**:
- general: 80 条 (40.4%)
- delay: 37 条 (18.7%)
- focus_大货订单: 29 条 (14.6%)
- focus_面料: 20 条 (10.1%)
- focus_样衣: 19 条 (9.6%)
- focus_出货: 13 条 (6.6%)

**覆盖款号**: 89 个唯一款号

---

## 二、配置文件 ✅

### 2.1 LLaMA-Factory 训练配置

**文件**: `configs/llama_factory_timeline_lora.yaml`

| 参数 | 值 | 说明 |
|------|-----|------|
| model_name_or_path | `Qwen/Qwen2.5-7B-Instruct` | Base 模型（可更换） |
| template | `qwen` | 对话模板 |
| dataset | `timeline_reasoning` | 数据集名称 |
| cutoff_len | `4096` | 序列截断长度 |
| per_device_train_batch_size | `2` | 单卡 batch size |
| gradient_accumulation_steps | `8` | 梯度累积步数 |
| learning_rate | `5.0e-5` | 学习率 |
| num_train_epochs | `3.0` | 训练轮数 |
| lora_rank | `64` | LoRA 秩 |
| lora_alpha | `128` | LoRA alpha |
| lora_dropout | `0.05` | LoRA dropout |
| output_dir | `outputs/timeline-reasoning-lora` | 输出目录 |
| val_size | `0.1` | 验证集比例 |
| bf16 | `true` | 使用 bf16 |

### 2.2 数据集注册

**文件**: `configs/dataset_info.json`

```json
{
  "timeline_reasoning": {
    "file_name": "timeline_train.jsonl",
    "formatting": "sharegpt",
    "columns": { "messages": "messages" },
    "tags": {
      "role_tag": "role",
      "content_tag": "content",
      "user_tag": "user",
      "assistant_tag": "assistant",
      "system_tag": "system"
    }
  }
}
```

---

## 三、脚本文件 ✅

| 文件 | 路径 | 功能 |
|------|------|------|
| 训练脚本 | `scripts/train.sh` | 一键启动 LLaMA-Factory 训练 |
| 数据集构造 | `src/build_timeline_dataset.py` | 从 events_passed.json 构造数据集 |

---

## 四、训练前准备清单

### 4.1 算力平台准备

```bash
# 1. 安装 LLaMA-Factory
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -e ".[torch,metrics]"

# 2. 准备数据目录
mkdir -p data
cp email_finetuning_pipeline/datasets/timeline_train.jsonl data/
cp email_finetuning_pipeline/datasets/timeline_val.jsonl data/
cp email_finetuning_pipeline/configs/dataset_info.json data/

# 3. 复制配置文件
cp email_finetuning_pipeline/configs/llama_factory_timeline_lora.yaml ./

# 4. 开始训练
llamafactory-cli train llama_factory_timeline_lora.yaml
```

### 4.2 模型选择

| 模型 | 模板 | 显存需求 | 推荐度 |
|------|------|---------|--------|
| Qwen2.5-7B-Instruct | `qwen` | ~24-28GB | ⭐⭐⭐⭐⭐ |
| Qwen2.5-14B-Instruct | `qwen` | ~40-48GB | ⭐⭐⭐⭐ |
| DeepSeek-R1-Distill-Qwen-7B | `deepseek` | ~24-28GB | ⭐⭐⭐⭐⭐ |
| LLaMA3.1-8B-Instruct | `llama3` | ~24-28GB | ⭐⭐⭐⭐ |

### 4.3 显存估算

**Qwen2.5-7B + LoRA r=64, cutoff=4096**:
- 模型权重: ~14 GB (bf16)
- LoRA 参数: ~100 MB
- 激活值 (bs=2, seq=4096): ~8-12 GB
- 优化器状态: ~2 GB
- **总计: ~24-28 GB**

**推荐算力**:
- ✅ 1x A100 40GB
- ✅ 1x A100 80GB (更稳，可增大 batch)
- ⚠️ 1x RTX 4090 24GB (需调小 bs=1 或 QLoRA)
- ⚠️ 1x V100 32GB (需 fp16 + bs=1)

---

## 五、训练后输出

| 输出 | 路径 | 说明 |
|------|------|------|
| LoRA 权重 | `outputs/timeline-reasoning-lora/` | 适配器文件 |
| 合并模型 | `outputs/timeline-reasoning-merged/` | 完整模型（可选） |
| 训练日志 | `outputs/timeline-reasoning-lora/trainer_state.json` | loss/learning_rate |
| TensorBoard | `outputs/timeline-reasoning-lora/runs/` | 可视化 |

---

## 六、验证训练效果

训练完成后，用以下 Prompt 测试：

```python
messages = [
    {"role": "system", "content": "你是服装行业业务分析师。请根据提供的事件记录，整理成结构化时间线表格并分析延期根因。如果某阶段无记录，请明确标注'未找到记录'，不要编造。输出必须使用 Markdown 表格。"},
    {"role": "user", "content": """款号: AW25-KFWTS101

事件记录：
[事件1] 面料 | 提交 | 2025-06-10 | 工厂 → 客人 | 面料订单提交，包括 Butter PU 和 210T 衬布
[事件2] Lab Dip | 确认 | 2025-06-25 | 工厂 → 客人 | Lab Dip 已确认
[事件3] 面料 | 确认 | 2025-06-27 | 工厂 → 客人 | 面料订单确认
[事件4] 样衣 | 提交 | 2025-07-09 | 工厂 → 客人 | 样衣寄出
[事件5] 面料 | 提交 | 2025-07-09 | 工厂 → 客人 | 拉链尺寸表提交
[事件6] 面料 | 其他 | 2025-07-10 | 工厂 → 客人 | 拉链全码尺寸表提供
[事件7] 出货 | 出货 | 2025-07-30 | 工厂 → 客人 | 预计出货

请整理成时间线表格。"""}
]
```

**期望输出**: Markdown 表格，包含面料/样衣/出货三个阶段，标注时间和事件类型。

---

## 七、文件打包清单

上传到算力平台需要打包的文件：

```
email_finetuning_pipeline/
├── configs/
│   ├── llama_factory_timeline_lora.yaml    # 训练配置
│   └── dataset_info.json                    # 数据集注册
├── datasets/
│   ├── timeline_train.jsonl                 # 训练集 (必需)
│   └── timeline_val.jsonl                   # 验证集 (必需)
└── scripts/
    └── train.sh                             # 训练脚本 (可选)
```

**最小必需文件**: `timeline_train.jsonl` + `llama_factory_timeline_lora.yaml` + `dataset_info.json`

---

## 八、状态总结

| 检查项 | 状态 |
|--------|------|
| 训练数据 (198+23 条) | ✅ 就绪 |
| 数据格式 (ShareGPT) | ✅ 正确 |
| 训练配置 (YAML) | ✅ 就绪 |
| 数据集注册 (JSON) | ✅ 就绪 |
| 训练脚本 (Shell) | ✅ 就绪 |
| 显存估算 (24-28GB) | ✅ 明确 |
| 模型选择 (Qwen2.5-7B) | ✅ 推荐 |

**结论**: ✅ **所有文件就绪，可直接上传算力平台训练**

conda create -n llama-factory python=3.11 -y
conda activate llama-factory
cd /path/to/LLaMA-Factory
pip install -e .
pip install tensorboardX