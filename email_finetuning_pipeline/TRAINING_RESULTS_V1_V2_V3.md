# V1/V2/V3 SFT + V2/V3 DPO 训练结果分析

> 记录时间: 2026-05-08
> 训练服务器: NVIDIA RTX PRO 6000 (96GB)
> 框架: LLaMA-Factory 0.9.5.dev0

---

## 一、V1 时间线生成模型

### 1.1 SFT 配置

| 配置项 | 值 |
|--------|-----|
| 基座模型 | Qwen/Qwen2.5-7B-Instruct |
| cutoff_len | 8192 |
| per_device_train_batch_size | 2 |
| gradient_accumulation_steps | 4 |
| 有效 batch | 8 |
| learning_rate | 5.0e-5 |
| num_train_epochs | 3.0 |
| lora_rank | 64 |
| lora_alpha | 128 |
| lora_dropout | 0.05 |
| weight_decay | 0.01 |

### 1.2 SFT 训练结果

| 指标 | 数值 | 评价 |
|------|------|------|
| train_loss | 0.288 | 收敛充分 |
| eval_loss | 0.278 | 略低于 train，gap 极小 |
| eval vs train gap | -0.010 | 几乎重合，健康 |
| 最佳 checkpoint | step 125 | 1.32 epoch |
| 训练时长 | 2,828s (~47min) | 比 A6000 快 2.2x |
| 总步数 | 189 | 3 epoch |

### 1.3 SFT 训练曲线分析

**train_loss**: 0.56 → 0.20，平滑下降，几乎无震荡
**eval_loss**: 0.363 → 0.278，持续下降后稳定

| step | eval_loss | 趋势 |
|------|-----------|------|
| 25 | 0.363 | 快速下降 |
| 50 | 0.311 | 持续下降 |
| 75 | 0.301 | 趋缓 |
| 100 | 0.284 | 继续下降 |
| 125 | **0.278** | ✅ 最低点 |
| 150 | 0.280 | 轻微回升 |
| 175 | 0.279 | 稳定 |
| 189 | 0.279 | 最终点 |

**关键观察**:
- step 125 (约 2 epoch) 是最佳点，之后 eval 轻微回升但幅度极小
- batch=2 使梯度非常稳定，train_loss 曲线几乎无震荡
- cutoff=8192 覆盖了 99% 样本，长样本不再被截断

### 1.4 与 A6000 批次对比

| 指标 | A6000 (batch=1, cutoff=6144, 4epoch) | PRO 6000 (batch=2, cutoff=8192, 3epoch) |
|------|--------------------------------------|----------------------------------------|
| train_loss | 0.351 | **0.288** ✅ |
| eval_loss | 0.304 | **0.278** ✅ |
| eval_gap | -0.047 (eval < train) | **-0.010** ✅ |
| 训练时长 | 6,334s | **2,828s** ✅ (快 2.2x) |
| 最佳点 | step 50 (唯一 eval) | **step 125** ✅ |

---

## 二、V2 多轮查询模型

### 2.1 SFT 配置

| 配置项 | 值 |
|--------|-----|
| 基座模型 | Qwen/Qwen2.5-7B-Instruct |
| cutoff_len | 8192 |
| per_device_train_batch_size | 2 |
| gradient_accumulation_steps | 4 |
| 有效 batch | 8 |
| learning_rate | 2.0e-5 |
| num_train_epochs | 2.5 |
| lora_rank | 16 |
| lora_alpha | 32 |
| lora_dropout | 0.05 |
| weight_decay | 0.01 |

### 2.2 SFT 训练结果

| 指标 | 数值 | 评价 |
|------|------|------|
| train_loss | 0.277 | 收敛充分 |
| eval_loss | 0.316 | 高于 train，存在 gap |
| eval vs train gap | +0.039 | 中等，任务复杂导致 |
| 最佳 checkpoint | step 175 | 2.19 epoch |
| 训练时长 | 4,692s (~1.3h) | 比 A6000 快 |
| 总步数 | 180 | 2.5 epoch |

### 2.3 SFT 训练曲线分析

**train_loss**: 0.37 → 0.20，整体下降但有震荡
**eval_loss**: 0.490 → 0.316，持续下降后趋于平缓

| step | eval_loss | 趋势 |
|------|-----------|------|
| 25 | 0.490 | 快速下降 |
| 50 | 0.394 | 持续下降 |
| 75 | 0.352 | 继续下降 |
| 100 | 0.332 | 趋缓 |
| 125 | 0.321 | 继续下降 |
| 150 | 0.317 | 趋缓 |
| 175 | **0.316** | ✅ 最低点 |
| 180 | 0.316 | 最终点 |

**关键观察**:
- eval 曲线健康：持续下降 → 平缓，无反弹
- train_loss 仍有震荡：batch=2 改善了 batch=1 的噪声，但多轮对话数据本身方差大（轮数 1-11，token 数 1K-88K），震荡未完全消除
- 相比 A6000 批次显著改善：eval_loss 0.342→0.316，gap +0.048→+0.039

### 2.4 与 A6000 批次对比

| 指标 | A6000 (batch=1, LR=1.5e-5) | PRO 6000 (batch=2, LR=2e-5) |
|------|---------------------------|----------------------------|
| train_loss | 0.294 | **0.277** ✅ |
| eval_loss | 0.342 | **0.316** ✅ |
| eval_gap | +0.048 | **+0.039** ✅ |
| 训练时长 | 6,524s | **4,692s** ✅ |

### 2.5 SFT 问题与限制

- eval_gap (+0.039) 仍大于 V1 (+0.010)，这是多轮决策任务的固有复杂度导致
- 786 条训练数据对复杂工具决策可能仍偏少
- 最长样本 88K tokens 在 8192 cutoff 下被严重截断

---

### 2.6 DPO 配置

| 配置项 | 值 |
|--------|-----|
| SFT 初始化 | ./outputs/sft-v2 |
| cutoff_len | 8192 |
| per_device_train_batch_size | 1 (OOM 限制) |
| gradient_accumulation_steps | 8 |
| 有效 batch | 8 |
| learning_rate | 5.0e-7 |
| num_train_epochs | 2.5 |
| pref_beta | 0.1 |
| pref_loss | sigmoid |

### 2.7 DPO 训练结果

| 指标 | 数值 | 评价 |
|------|------|------|
| train_loss | 0.0209 | DPO loss 低，偏好区分明显 |
| eval_loss | 0.0147 | 低于 train，泛化好 |
| eval_rewards/accuracies | **1.0** | 验证集 100% 正确 |
| eval_rewards/chosen | 10.97 | chosen reward 高 |
| eval_rewards/rejected | 2.46 | rejected reward 低 |
| eval_rewards/margins | **8.51** | 差距大，区分度高 |
| 最佳 checkpoint | step 243 | 最终点 |
| 训练时长 | 8,251s (~2.3h) | DPO 需 policy+ref 双模型 |
| 总步数 | 243 | 2.5 epoch |

### 2.8 DPO 关键观察

- **accuracy = 100%**：验证集上完美区分 chosen 和 rejected
- **reward margin = 8.51**：chosen 和 rejected 的 reward 差距显著
- **eval 曲线健康**：eval_loss 从 0.036 → 0.015，平滑下降，无过拟合
- **train_loss 有轻微震荡**：batch=1 导致，但 DPO 的极低 LR (5e-7) 使更新稳定

### 2.9 DPO 特有指标解读

```
eval_logps/chosen:  -307.9  (policy 对 chosen 的 log 概率)
eval_logps/rejected: -64.6   (policy 对 rejected 的 log 概率)
```

注意：DPO 优化的是**相对排序**而非绝对概率。只要 margin 增大即正确。

---

## 三、V3 调度器模型

### 3.1 SFT 配置

| 配置项 | 值 |
|--------|-----|
| 基座模型 | Qwen/Qwen2.5-7B-Instruct |
| cutoff_len | 1024 |
| per_device_train_batch_size | 4 |
| gradient_accumulation_steps | 2 |
| 有效 batch | 8 |
| learning_rate | 1.0e-4 |
| num_train_epochs | 2.0 |
| lora_rank | 8 |
| lora_alpha | 16 |
| lora_dropout | 0.0 |
| weight_decay | 0.0001 |

### 3.2 SFT 训练结果

| 指标 | 数值 | 评价 |
|------|------|------|
| train_loss | 0.296 | 收敛快 |
| eval_loss | 0.034 | 极低 |
| eval vs train gap | +0.262 | 正常（任务极简单） |
| 最佳 checkpoint | step 200 | 最终点 |
| 训练时长 | 103s (~1.7min) | 极快 |
| 总步数 | 200 | 2 epoch |

### 3.3 SFT 训练曲线分析

**train_loss**: 2.5 → 0.03，极速收敛
**eval_loss**: 0.047 → 0.034，持续下降

| step | eval_loss | 趋势 |
|------|-----------|------|
| 100 | 0.047 | 快速下降 |
| 200 | **0.034** | ✅ 最终点 |

**关键观察**:
- 任务极轻量：平均 85 tokens，最大 111 tokens，三分类路由
- loss 极速收敛：2 epoch 内从 2.5 → 0.03
- 配置精简：1024 cutoff、rank=8 对 85 tokens 的任务已足够
- 数据分布不均：route_v2 (43%) + route_v1 (40%) 占 83%，direct_answer + boundary 仅 17%

---

### 3.4 DPO 配置

| 配置项 | 值 |
|--------|-----|
| SFT 初始化 | ./outputs/sft-v3 |
| cutoff_len | 4096 |
| per_device_train_batch_size | 1 |
| gradient_accumulation_steps | 8 |
| 有效 batch | 8 |
| learning_rate | 5.0e-7 |
| num_train_epochs | 3.0 |
| pref_beta | 0.1 |
| pref_loss | sigmoid |

### 3.5 DPO 训练结果

| 指标 | 数值 | 评价 |
|------|------|------|
| train_loss | 0.0127 | 极低 |
| eval_loss | 0.0052 | 极低 |
| eval_rewards/accuracies | **1.0** | 验证集 100% 正确 |
| eval_rewards/chosen | 13.38 | chosen reward 高 |
| eval_rewards/rejected | 3.05 | rejected reward 低 |
| eval_rewards/margins | **10.34** | 比 V2 更高 |
| 最佳 checkpoint | step 225 | 最终点 |
| 训练时长 | 525s (~9min) | 极快 |
| 总步数 | 225 | 3 epoch |

### 3.6 DPO 关键观察

- **accuracy = 100%**，margin = 10.34，比 V2 (8.51) 更高
- **训练速度是 V2 DPO 的 15 倍**（525s vs 8,251s）
- **eval 曲线完美**：从 0.018 → 0.005，持续下降后平稳
- **任务简单导致 DPO 更容易**：3 分类 vs 10+ 工具，短 JSON vs 多轮对话

---

## 四、三模型 SFT 横向对比

| 维度 | V1 | V2 | V3 |
|------|-----|-----|-----|
| **任务** | 单轮结构化生成 | 多轮工具决策 | 三分类路由 |
| **复杂度** | 中 | 高 | 低 |
| **平均序列长度** | ~2,400 tokens | ~7,500 tokens | ~85 tokens |
| **SFT train_loss** | 0.288 | 0.277 | 0.296 |
| **SFT eval_loss** | **0.278** | 0.316 | 0.034 |
| **SFT eval_gap** | **+0.010** ✅ | +0.039 | +0.262 |
| **SFT 训练时长** | 2,828s | 4,692s | **103s** |
| **SFT 健康度** | ⭐⭐⭐ 优秀 | ⭐⭐☆ 良好 | ⭐⭐⭐ 优秀（任务简单） |
| **数据量** | 500 条 | 786 条 | 800 条 |
| **DPO accuracy** | N/A | **100%** | **100%** |
| **DPO margin** | N/A | 8.51 | **10.34** |
| **DPO 训练时长** | N/A | 8,251s | **525s** |

---

## 五、PRO 6000 96GB 的价值

| 改进 | A6000 48GB | PRO 6000 96GB |
|------|-----------|--------------|
| V1 SFT batch | 1 | **2** |
| V1 SFT cutoff | 6144 (妥协) | **8192** (全覆盖) |
| V1 SFT 速度 | 6,334s | **2,828s** (快 2.2x) |
| V1 SFT eval | 0.304 | **0.278** ✅ |
| V2 SFT batch | 1 | **2** |
| V2 SFT eval_gap | +0.048 | **+0.039** ✅ |
| V2 DPO cutoff | 4096 (妥协) | **8192** (和 SFT 一致) |

---

## 六、关键结论

### 6.1 SFT 效果

- **V1 SFT 最健康**：eval_gap 仅 +0.010，batch=2 后梯度极稳，cutoff=8192 覆盖完整
- **V2 SFT 有改善**：batch=2 使 eval_gap 从 +0.048 降到 +0.039，但多轮任务固有复杂度限制进一步改善
- **V3 SFT 配置精简**：任务简单，1024 cutoff 和 rank=8 已足够，结果优秀

### 6.2 DPO 效果

- V2 和 V3 的 DPO 都达到 **100% accuracy**
- V3 margin (10.34) > V2 margin (8.51)，任务越简单 DPO 效果越显著
- DPO 对 V2 的价值更大：SFT eval_gap 大，DPO 进一步优化了决策质量

### 6.3 剩余问题

| 模型 | 问题 | 优先级 |
|-----|------|--------|
| V2 | 数据量 786 条偏少，最长样本截断 | 中 |
| V2 | batch=1 的 DPO 仍有震荡 | 低 |
| V3 | 类别不平衡（83% route vs 17% 其他） | 中 |
| V3 | 配置已优化（rank=8, cutoff=1024） | 低 |

---

## 七、模型文件位置

| 模型 | 路径 |
|-----|------|
| V1 SFT | `./outputs/sft-v1/checkpoint-125` |
| V2 SFT | `./outputs/sft-v2/checkpoint-175` |
| V2 DPO | `./outputs/dpo-v2/checkpoint-243` |
| V3 SFT | `./outputs/sft-v3/checkpoint-200` |
| V3 DPO | `./outputs/dpo-v3/checkpoint-225` |

---

## 八、后续建议

1. **端到端测试**：V3 → V2 → V1 的完整链路验证
2. **V2 数据扩充**：增加多轮对话样本，特别是边界 case
3. **V3 类别平衡**：增加 direct_answer 和 boundary 的 hard negatives
4. **V1 无需 RL**：SFT 已充分，格式化生成任务 SFT + 规则后处理最优
