# V3 调度器数据集

## 文件结构

```
datasets/
├── sft_scheduler_v3.jsonl          # 训练集 SFT (800条)
├── dpo_scheduler_v3.jsonl          # 训练集 DPO (600条)
├── scheduler_v3_stats.json         # 训练集统计
├── order_mapping.json              # 订单-款号映射（从真实数据提取）
├── val/
│   ├── sft_scheduler_v3.jsonl      # 独立验证集 (100条)
│   └── scheduler_v3_stats.json     # 验证集统计
└── README.md                       # 本文件
```

## 训练集 (datasets/sft_scheduler_v3.jsonl + dpo_scheduler_v3.jsonl)

- **数量**: 800条 SFT + 600条 DPO
- **款号来源**: 事件丰富的款号 (>=5事件)，共280个唯一款号
- **场景分布**:
  - route_v1: 280 (35%) — 有款号 → V1分析
  - route_v2: 240 (30%) — 无款号+无分析关键字 → V2查询
  - route_v2_then_v1: 144 (18%) — 无款号+有分析关键字 → V2查+V1分析
  - direct_answer: 96 (12%) — 问候/能力说明/模糊
  - boundary: 40 (5%) — 越界/无效款号

## 独立验证集 (datasets/val/sft_scheduler_v3.jsonl)

- **数量**: 100条 SFT（无DPO）
- **款号来源**: 事件少的边缘款号 (2-4事件)，共35个唯一款号
- **与训练集关系**: 款号完全不重叠
- **用途**: 训练后独立评估，检测模型对边缘款号的泛化能力
- **生成命令**:
  ```bash
  python src/build_v3_scheduler_dataset.py \
      --output-dir datasets/val \
      --sft-target 100 \
      --dpo-target 0 \
      --seed 999 \
      --use-poor-styles
  ```

## 测试集 (evaluation/test_cases.json)

- **数量**: 112条手工构造用例
- **与训练集关系**: 非direct_answer场景的问题无重叠
- **用途**: 端到端测试，最终报告

## 数据隔离性

| 数据集对 | 款号重叠 | 问题重叠 | 状态 |
|---------|---------|---------|------|
| 训练/验证 | 0 | N/A | ✅ 完全隔离 |
| 训练/测试 | 24个款号 | 11个（仅direct_answer） | ✅ 可接受 |
| 验证/测试 | 0 | N/A | ✅ 完全隔离 |

## 使用方式

### 1. LLaMA-Factory 训练（内部验证集）

```yaml
# configs/sft_scheduler_v3_config.yaml
dataset: sft_scheduler_v3
val_size: 0.1  # LLaMA-Factory自动划分10%内部验证集
```

### 2. 独立验证集评估

训练完成后，在独立验证集上评估：

```python
# 加载验证集
with open("datasets/val/sft_scheduler_v3.jsonl") as f:
    val_data = [json.loads(l) for l in f]

# 评估各场景准确率
for scene in ["route_v1", "route_v2", "route_v2_then_v1", "direct_answer", "boundary"]:
    scene_data = [d for d in val_data if d["scene"] == scene]
    # ... 模型推理 + 准确率计算
```

### 3. 测试集端到端测试

```bash
python evaluation/test_end_to_end.py
```

## 重新生成数据

```bash
# 训练集
python src/build_v3_scheduler_dataset.py \
    --output-dir datasets \
    --sft-target 800 \
    --dpo-target 600 \
    --seed 42

# 独立验证集
python src/build_v3_scheduler_dataset.py \
    --output-dir datasets/val \
    --sft-target 100 \
    --dpo-target 0 \
    --seed 999 \
    --use-poor-styles
```
