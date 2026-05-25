# SFT 训练框架对比：LLaMA-Factory vs 其他方案

> 讨论时间: 2026-04-22
> 当前方案: LLaMA-Factory v0.9.5 + LoRA 微调

---

## 一、你的当前方式是否"正规"

### 结论：正规，而且是主流做法

```
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -e ".[torch,metrics]"

# 准备数据
cp dataset_info.json data/
cp timeline_train.jsonl data/

# 修改 configs/llama_factory_timeline_lora.yaml
# 运行训练
llamafactory-cli train llama_factory_timeline_lora.yaml
```

**这种方式的正规性体现在：**

| 方面 | 说明 |
|------|------|
| **开源社区认可** | LLaMA-Factory GitHub 30k+ stars，国内最流行 |
| **标准化流程** | 数据注册(dataset_info.json) → 配置YAML → 命令行训练 |
| **可复现** | 固定seed、配置版本化、训练日志完整 |
| **可扩展** | 支持LoRA/QLoRA/全量/DPO/PPO等多种训练方式 |

**你的操作没有不规范的地方。**

---

## 二、企业级训练方式的完整图谱

```
训练方式
    │
    ├── 1. 开源框架（你现在的位置）
    │      ├── LLaMA-Factory ← 你在这里
    │      ├── Axolotl
    │      ├── Unsloth
    │      ├── transformers + PEFT（手写）
    │      └── DeepSpeed + Accelerate（手写）
    │
    ├── 2. 云厂商托管服务
    │      ├── 阿里云 PAI-DSW / PAI-DLC
    │      ├── 百度智能云 BML
    │      ├── 火山引擎方舟
    │      ├── AWS SageMaker
    │      └── Azure OpenAI Fine-tuning
    │
    ├── 3. 模型厂商官方平台
    │      ├── 阿里云百炼（Qwen官方）
    │      ├── 智谱 AI开放平台（ChatGLM）
    │      ├── 百度千帆（文心）
    │      └── OpenAI Fine-tuning API
    │
    └── 4. 企业自研平台
           ├── 基于K8s的训练调度平台
           ├── 内部MLflow + 自定义训练脚本
           └── 采购商业化AI平台（如第四范式、商汤）
```

---

## 三、各方案详细对比

### 3.1 方案一：开源框架（LLaMA-Factory 等）

**代表：** LLaMA-Factory、Axolotl、Unsloth、ms-swift（魔搭）

| 维度 | 详情 |
|------|------|
| **成本** | 低，只需要GPU服务器 |
| **灵活性** | 极高，可以改任何代码 |
| **数据隐私** | 数据不出内网，完全自主 |
| **学习曲线** | 中等，需要理解配置参数 |
| **维护成本** | 需要自己跟进版本更新、修bug |
| **适合规模** | 中小团队、技术能力强 |

**具体框架对比：**

| 框架 | 特点 | 你的适用性 |
|------|------|-----------|
| **LLaMA-Factory** | 配置驱动、支持方法最全、中文文档好 | ✅ 当前选择，合理 |
| **Axolotl** | YAML配置更简洁、社区活跃 | 类似LLaMA-Factory |
| **Unsloth** | 训练速度2-5倍提升、显存节省 | 适合追求效率时切换 |
| **ms-swift** | 阿里魔搭出品、中文模型支持好 | 如果用通义系列模型推荐 |
| **手写 transformers** | 完全可控、学习成本最高 | 除非有特殊需求，不推荐 |

**你的情况：** 技术能力足够、数据敏感（服装行业内部邮件）、训练频率不高（每季节一次）→ **开源框架是最优选择**

---

### 3.2 方案二：云厂商托管服务

**代表：** 阿里云PAI、百度BML、火山方舟、AWS SageMaker

| 维度 | 详情 |
|------|------|
| **成本** | 中-高，按GPU时长计费 |
| **灵活性** | 中等，厂商封装了部分细节 |
| **数据隐私** | 数据上传到云端，有合规风险 |
| **学习曲线** | 低，Web界面或简单SDK |
| **维护成本** | 低，厂商负责基础设施 |
| **适合规模** | 中大型企业、没有专门ML运维 |

**典型使用方式：**
```python
# 伪代码示例：阿里云PAI
from pai.toolkit import TrainingJob

job = TrainingJob(
    source_dir="./training_code",
    entry_point="train.py",
    instance_type="ecs.gn7i-c32g1.8xlarge",  # A10 * 1
    hyperparameters={
        "model_name": "Qwen2.5-7B-Instruct",
        "lora_r": 64,
        "learning_rate": 5e-5,
    }
)
job.run()
```

**你的情况：** 已经有A6000服务器、数据敏感 → **暂时不需要**

---

### 3.3 方案三：模型厂商官方平台

**代表：** 阿里云百炼、智谱AI、百度千帆、OpenAI

| 维度 | 详情 |
|------|------|
| **成本** | 按token或训练时长计费 |
| **灵活性** | 低，只能用厂商支持的参数 |
| **数据隐私** | 数据必须上传到厂商平台 |
| **学习曲线** | 极低，上传文件点按钮 |
| **维护成本** | 极低 |
| **适合场景** | 快速验证、不想管基础设施 |

**OpenAI Fine-tuning API 示例：**
```bash
# 上传数据
openai api fine_tunes.create -t timeline_train.jsonl -m gpt-3.5-turbo

# 等邮件通知训练完成
# 拿到模型ID直接调用
```

**国内厂商类似：** 上传JSONL → 选择基础模型 → 配置参数 → 点击训练

**你的情况：** 用Qwen模型、需要LoRA、数据敏感 → **不推荐**，除非做快速原型验证

---

### 3.4 方案四：企业自研平台

**代表：** 基于K8s的调度平台、MLflow + 自定义脚本、采购商业化平台

| 维度 | 详情 |
|------|------|
| **成本** | 高（人力+硬件+软件） |
| **灵活性** | 极高（自研）或中等（采购） |
| **数据隐私** | 完全自主 |
| **学习曲线** | 高 |
| **维护成本** | 高，需要专门团队 |
| **适合规模** | 大型企业、多团队共用、高频训练 |

**典型架构：**
```
用户（算法工程师）
    │
    ▼
Web UI / Jupyter Notebook
    │
    ▼
任务调度（K8s / Volcano）
    │
    ├── GPU节点1（训练）
    ├── GPU节点2（训练）
    └── GPU节点3（推理）
    │
    ▼
模型仓库（Harbor / MLflow Model Registry）
    │
    ▼
推理服务（K8s Deployment + Triton/TF Serving）
```

**你的情况：** 只有1-2个人、每季节训练一次 → **严重过度设计**

---

## 四、四方案对比总表

| 维度 | 开源框架 | 云厂商托管 | 模型厂商平台 | 企业自研 |
|------|----------|-----------|-------------|----------|
| **初期投入** | 低 | 中 | 低 | 高 |
| **长期成本** | 中（人力维护） | 高（持续付费） | 高（按量付费） | 高（团队+硬件） |
| **灵活性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **数据隐私** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **易用性** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **可扩展性** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **适合你的程度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ |

---

## 五、你的演进路线建议

### 当前阶段（现在）
```
LLaMA-Factory + A6000 服务器
├── 数据在本地
├── 手动触发训练
└── 模型文件手动管理
```
**没问题，继续用。**

### 下一阶段（3-6个月后，如果业务扩大）
```
改进点：
├── 引入 MLflow 或 Weights & Biases 记录实验
├── 用 Docker 封装训练环境（避免"在我机器上能跑"）
├── 简单的 Web UI 触发训练（不用ssh登录服务器）
└── 模型版本管理（v1, v2, v3...）
```

### 再下一阶段（1年后，如果多团队使用）
```
考虑：
├── 内部部署开源MLOps平台（如Kubeflow、ClearML）
├── 或者采购商业化平台
└── 或者迁移到云厂商托管（如果数据合规允许）
```

---

## 六、一个常见的认知误区

> "用开源框架 = 不正规，企业应该用商业平台"

**事实是：**
- 字节跳动、阿里、腾讯内部大量用自研或开源框架
- OpenAI自己训练GPT也用PyTorch + 自研工具链
- "正规"不等于"付费"，等于"可复现、可维护、有文档"

**你的LLaMA-Factory方案完全正规，只要做好：**
1. ✅ 配置文件版本化（git管理）
2. ✅ 训练数据版本化（每次训练的数据集留档）
3. ✅ 模型输出版本化（v1, v2标注清楚对应的数据和配置）
4. ✅ 训练日志保存（loss曲线、超参数、硬件信息）

---

## 七、如果你现在想尝试其他框架

### 推荐：Unsloth（同样的数据，更快训练）

```bash
# 安装
pip install unsloth

# 训练代码（比LLaMA-Factory更简洁）
from unsloth import FastLanguageModel
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="Qwen/Qwen2.5-7B-Instruct",
    max_seq_length=4096,
    load_in_4bit=False,  # A6000 48GB 不需要量化
)

model = FastLanguageModel.get_peft_model(
    model,
    r=64,
    lora_alpha=128,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", 
                    "gate_proj", "up_proj", "down_proj"],
)

# 训练（比LLaMA-Factory快2-5倍）
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=4096,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        num_train_epochs=3,
        learning_rate=5e-5,
        output_dir="outputs",
    ),
)
trainer.train()
```

**优点：** 训练速度显著提升、显存更省
**缺点：** 功能没LLaMA-Factory全、社区支持略少

**建议：** 当前LLaMA-Factory够用，如果以后训练时间成为瓶颈，再考虑Unsloth。

---

## 八、总结

| 问题 | 答案 |
|------|------|
| 你的方式正规吗？ | ✅ 正规，而且是主流 |
| 企业还有别的训练方式吗？ | 有，云托管、厂商平台、自研平台 |
| 你需要换吗？ | 暂时不需要，LLaMA-Factory完全够用 |
| 什么时候考虑换？ | 团队扩大、训练频率提高、需要多GPU并行 |
| 现在该做什么？ | 把实验管理做好（版本化、日志、文档） |

---

---

## 九、用户理解校正（2026-04-22 补充）

### 用户的原始理解

1. **"微调算法有最优解，所以有了 Factory 项目，微调就更新配置即可"**
2. **"直接 clone 项目修改数据和配置，而不是把 LLaMA-Factory 做成工具包调用，是因为配置过多、数据更新不频繁"**

### 校正后的理解

#### 关于第1点

| 用户理解 | 校正 |
|----------|------|
| "微调算法有最优解" | ❌ 不是"最优解"，是"成熟的标准做法"。不同场景选不同算法（LoRA/QLoRA/全量/DoRA） |
| "Factory 就是更新配置" | ⚠️ 对，但不完整。Factory 的价值还包括：数据格式统一、分布式训练支持、模型合并导出等 |

**算法选择是场景匹配，不是唯一最优：**

| 算法 | 适用场景 | 你的情况 |
|------|----------|----------|
| LoRA | 小数据、快速迭代、节省显存 | ✅ 在用 |
| QLoRA | 显存极度受限 | 不需要，A6000够 |
| 全量微调 | 大数据、追求极致 | 数据太少，没必要 |
| DoRA | LoRA改进版 | 可尝试 |

#### 关于第2点

| 用户理解 | 校正 |
|----------|------|
| "不是工具包直接调用" | ⚠️ Factory 也可以当工具包调用（Python API），只是社区更常用命令行 |
| "配置过多、调用不频繁" | ✅ 合理，但更重要的原因是：YAML即文档、可复现、非程序员友好 |
| "clone后修改项目数据" | ❌ 最佳实践是：数据和配置放在项目**外部**，通过路径引用 |

**LLaMA-Factory 两种使用方式：**

```python
# 方式A：命令行（社区主流，你现在的用法）
llamafactory-cli train config.yaml

# 方式B：Python API（也存在）
from llamafactory.train.tuner import run_exp
run_exp(dict(model_name_or_path="Qwen/...", ...))
```

**为什么选方式A？**
- 配置即文档（git diff 能看到改了什么）
- 非程序员友好
- 和 Docker/K8s 集成方便

**为什么不推荐修改项目内部文件？**
- 升级版本时修改会被覆盖
- 团队协作状态不一致
- 不利于 CI/CD

### 推荐的工作流改进

```
# 当前（不太理想）
LLaMA-Factory/
├── data/dataset_info.json      ← 你改的（在项目里）
└── configs/your_config.yaml    ← 你改的（在项目里）

# 推荐（更清晰）
your-project/                    ← 你的项目（git管理）
├── email_finetuning_pipeline/
│   ├── configs/llama_factory_timeline_lora.yaml
│   └── datasets/
│       ├── dataset_info.json
│       └── timeline_train.jsonl
│
LLaMA-Factory/                   ← 框架目录（保持干净）
└── src/...

# 运行命令
cd LLaMA-Factory
llamafactory-cli train \
  ../email_finetuning_pipeline/configs/llama_factory_timeline_lora.yaml \
  --dataset_dir ../email_finetuning_pipeline/datasets
```

### 总结

| 用户理解 | 判断 |
|----------|------|
| 微调算法成熟统一，Factory避免重复造轮子 | ✅ 正确 |
| 配置驱动、无需写代码 | ✅ 正确（但Python API也存在） |
| 直接clone后修改项目内的数据和配置 | ⚠️ 能用，但不是最佳实践 |
| 不频繁调用所以不当工具包 | ✅ 合理，但原因更偏向"配置即文档" |

**核心建议：把数据和配置移出 LLaMA-Factory 目录，保持框架干净。**

---

还有什么想细化的？比如：
- 具体怎么引入MLflow做实验管理
- Docker封装训练环境的Dockerfile
- 多GPU训练（DDP/DeepSpeed）的配置
