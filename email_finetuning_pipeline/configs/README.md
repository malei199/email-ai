# 模型微调配置说明

当前支持 **V1/V2/V3 三模型**的 LLaMA-Factory 训练配置，覆盖 SFT 和 DPO 两种训练阶段。

---

## 当前可用配置

| 配置文件 | 用途 | 关键参数 |
|---------|------|---------|
| `sft_v1_timeline_lora.yaml` | V1 时间线生成 SFT | `cutoff_len: 8192`, `lora_rank: 64`, `LR: 5.0e-5` |
| `sft_v2_multi_round_config.yaml` | V2 查询引擎 SFT | `cutoff_len: 8192`, `lora_rank: 16`, `LR: 2.0e-5` |
| `dpo_v2_multi_round_config.yaml` | V2 查询引擎 DPO | `cutoff_len: 8192`, `LR: 5.0e-7`, `pref_beta: 0.1` |
| `sft_v3_scheduler_config.yaml` | V3 调度器 SFT | `cutoff_len: 1024`, `lora_rank: 8`, `LR: 1.0e-4` |
| `dpo_v3_scheduler_config.yaml` | V3 调度器 DPO | `cutoff_len: 4096`, `lora_rank: 16`, `LR: 5.0e-7` |
| `dataset_info.json` | 数据集注册（LLaMA-Factory） | 15 个数据集条目 |

---

## 配置文件结构

```
configs/
├── sft_v1_timeline_lora.yaml          # V1 SFT 配置
├── sft_v2_multi_round_config.yaml     # V2 SFT 配置
├── dpo_v2_multi_round_config.yaml     # V2 DPO 配置
├── sft_v3_scheduler_config.yaml       # V3 SFT 配置
├── dpo_v3_scheduler_config.yaml       # V3 DPO 配置
├── dataset_info.json                  # LLaMA-Factory 数据集注册
└── README.md                          # 本文件
```

---

## 快速开始

### 安装 LLaMA-Factory

```bash
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -e ".[torch,metrics]"
```

### 训练命令

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

### 合并模型

```bash
llamafactory-cli export \
    --model_name_or_path Qwen/Qwen2.5-7B-Instruct \
    --adapter_name_or_path outputs/sft-v1 \
    --template qwen \
    --finetuning_type lora \
    --export_dir outputs/sft-v1-merged \
    --export_size 2 \
    --export_device cpu \
    --export_legacy_format False
```

---

## 显存需求参考 (7B 模型)

| 训练方式 | 序列长度 | 显存需求 | 推荐 GPU |
|---------|---------|---------|---------|
| V1 SFT LoRA (bs=2, cutoff=8192) | 8192 | ~28GB | RTX PRO 6000, A100 40GB |
| V2 SFT LoRA (bs=2, cutoff=8192) | 8192 | ~28GB | RTX PRO 6000, A100 40GB |
| V2 DPO LoRA (bs=1, cutoff=8192) | 8192 | ~32GB | RTX PRO 6000, A100 40GB |
| V3 SFT LoRA (bs=4, cutoff=1024) | 1024 | ~16GB | RTX 3090/4090, A100 40GB |
| V3 DPO LoRA (bs=1, cutoff=4096) | 4096 | ~20GB | RTX 3090/4090, A100 40GB |

> 如需 QLoRA 配置，可在对应 YAML 中添加 `quantization_bit: 4` 并调低 `per_device_train_batch_size`。

---

## 模型适配修改

如需更换 base 模型：

```yaml
model_name_or_path: your/model-path
template: model_template
```

### 常见模型模板对应

| 模型 | template |
|------|----------|
| Qwen2/Qwen2.5 | `qwen` |
| LLaMA3/3.1 | `llama3` |
| Mistral | `mistral` |
| Yi | `yi` |
| ChatGLM3 | `chatglm3` |
| GLM4 | `glm4` |
| DeepSeek | `deepseek` |

---

## 数据格式说明

### SFT 数据格式 (ShareGPT)

`dataset_info.json` 中已注册所有 SFT 数据集，格式为：

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

### DPO 数据格式 (Alpaca)

`dataset_info.json` 中已注册所有 DPO 数据集，格式为：

```json
{
  "instruction": "system prompt",
  "input": "user question",
  "chosen": "correct assistant response",
  "rejected": "wrong assistant response"
}
```

---

## 训练后使用

### 使用 transformers 加载

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-7B-Instruct",
    torch_dtype="auto",
    device_map="auto"
)
model = PeftModel.from_pretrained(model, "outputs/dpo-v3/checkpoint-225")
model = model.merge_and_unload()

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")

messages = [
    {"role": "system", "content": "你是服装行业智能调度器..."},
    {"role": "user", "content": "CCSS230013 的时间线"}
]

text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to(model.device)
outputs = model.generate(**inputs, max_new_tokens=256, temperature=0.7)
response = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(response)
```

---

## 常见问题

### 1. CUDA Out of Memory
- 添加 `quantization_bit: 4` 使用 QLoRA
- 减小 `per_device_train_batch_size`
- 增大 `gradient_accumulation_steps`
- 减小 `cutoff_len`（V1/V2 不建议低于 8192，V3 不建议低于 1024）

### 2. 训练 loss 不下降
- 检查 `dataset_info.json` 中数据集名称与 YAML 中 `dataset` 字段是否一致
- 检查学习率是否过大/过小
- 增加 `warmup_steps`
- 检查数据格式是否正确

### 3. 模型输出重复
- 降低 `temperature`
- 增加 `repetition_penalty`
- 检查训练数据是否有重复

---

## 更多资源

- [LLaMA-Factory 文档](https://github.com/hiyouga/LLaMA-Factory)
- [Hugging Face PEFT](https://huggingface.co/docs/peft)
- `TRAINING_RESULTS_V1_V2_V3.md` — 详细训练结果与曲线分析
