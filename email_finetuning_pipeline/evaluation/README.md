# 端到端测试脚本

## 目录结构

```
evaluation/
├── README.md                 # 本说明文件
├── test_end_to_end.py        # 端到端测试主脚本
├── test_cases.json           # 测试用例配置
└── requirements.txt          # 依赖
```

## 测试范围

覆盖 V3 调度器的 4 种场景路由，以及 V2 的 11 种意图查询执行能力。

### V3 场景类型 (v2.0)

V3 在 v2.0 已简化为**纯单轮路由决策器**，只输出 `decision`，不参与后续流程。

| 场景 | 用户输入示例 | 期望路由 | 说明 |
|-----|------------|---------|------|
| `direct_answer` | "你好" / "谢谢" | `direct_answer` | 问候、感谢、模糊输入、越界 |
| `route_v2` | "Iris Jiang 的款号进度" | `route_v2` | 无款号查询，V2 引擎自治 |
| `route_v1` | "CCSS230021 的时间线" | `route_v1` | 有款号查询，V1 分析 |
| `boundary` | "讲个笑话" / "9999999 的信息" | `direct_answer` | 越界问题、无效款号 |

> **v2.0 变更**：删除 `v2_then_v1` 和 `v2_single_round`/`v2_multi_round` 的 V3 侧区分。V3 只判断 `route_v1` / `route_v2` / `direct_answer`。

### V2 意图覆盖（11 种）

| 意图 | 类型 | 示例 | 轮数 |
|-----|------|------|------|
| `term_translation` | 单轮 | "oxford 怎么翻译" | 1 |
| `order_query` | 单轮 | "订单 2538808 有哪些款" | 1 |
| `delay_analysis` | 单轮 | "CCSS230026 进度怎么样？" | 1 |
| `person_query` | 多轮 | "CCSS230041 是谁在负责" | ≥2 |
| `factory_query` | 多轮 | "CCSS230011 是哪个工厂的？" | ≥2 |
| `technical_param` | 多轮 | "AW25-KFWTT133 面料成分" | ≥2 |
| `general_timeline` | 多轮 | "CCSS230011 现在到哪了" | ≥2 |
| `multi_aspect` | 多轮 | "8971427 完整情况" | ≥2 |
| `stage_check` | 多轮 | "2538808 封样了没有" | ≥2 |
| `client_feedback` | 多轮 | "CCSS230021 客户意见给了吗" | ≥2 |
| `factory_issue` | 多轮 | "AW25-KFWTT166 工厂能按时做完吗" | ≥2 |
| `my_styles_status` | 多轮 | "我手上有哪些款号要出货了" | ≥2 |

> **单轮 vs 多轮判断**：`term_translation`、`order_query`、`delay_analysis` 为单轮；其余均为多轮。

## 模型路径

测试脚本会自动加载以下模型（相对 `email_finetuning_pipeline/`）：

| 模型 | 路径 | 作用 |
|-----|------|------|
| V3 Scheduler | `outputs/dpo-v3/checkpoint-225` | 入口调度，决定路由 |
| V2 Query Engine | `outputs/dpo-v2/checkpoint-243` | 多轮查询策略 + 工具调用 |
| V1 Timeline | `outputs/sft-v1/checkpoint-189` | 时间线推理分析 |

## 使用方法

### 1. 安装依赖

```bash
cd email_finetuning_pipeline/evaluation
pip install -r requirements.txt
```

### 2. 运行全部测试

```bash
python test_end_to_end.py --all
```

### 3. 运行指定场景测试

```bash
# 只测 V3 调度决策
python test_end_to_end.py --scene route_v2

# 测多个场景
python test_end_to_end.py --scene direct_answer,route_v2,boundary

# 测有款号场景
python test_end_to_end.py --scene route_v1
```

### 4. 运行指定意图测试

```bash
# 测新增意图
python test_end_to_end.py --custom v2_multi_stage_check
python test_end_to_end.py --custom v2_multi_client_feedback
python test_end_to_end.py --custom v2_multi_factory_issue
```

### 5. 自定义测试用例

编辑 `test_cases.json` 添加自己的测试用例：

```json
{
  "my_test": {
    "scene": "route_v1",
    "user_input": "CCSS230021 面料确认了吗",
    "expected_route": "route_v1",
    "expected_style_id": "CCSS230021",
    "expected_event": "面料确认"
  }
}
```

然后运行：
```bash
python test_end_to_end.py --custom my_test
```

## 输出说明

测试结果会输出到控制台，并保存到 `results/` 目录：

```
results/
├── 20250426_150102/           # 时间戳目录
│   ├── summary.json           # 汇总结果
│   ├── v3_routing.json        # V3 路由决策详情
│   ├── v2_execution.json      # V2 查询执行详情
│   └── v1_timeline.json       # V1 时间线推理详情
```

### 评估指标

| 指标 | 说明 |
|-----|------|
| `routing_accuracy` | V3 路由到正确模块的比例 |
| `decision_accuracy` | V2 决策正确率（satisfied/function_calls） |
| `format_compliance` | 输出 JSON 格式合规率 |
| `end_to_end_success` | 端到端完整执行成功率 |

## 测试用例分布（V2 更新后）

当前 `test_cases.json` 共 **80 条**测试用例（v2.0 已移除 `route_v2_then_v1`）：

| 场景 | 数量 | 覆盖意图/类型 |
|-----|------|-------------|
| `direct_answer` | 16 | greeting, thanks, vague, out_of_scope |
| `boundary` | 8 | invalid_style, joke, weather, off_topic, missing_info, vague |
| `route_v2` | 20 | person_query, factory_query, term_translation, my_styles_status, order_query |
| `route_v1` | 36 | timeline_analysis, stage_check, technical_param, delay_analysis, person_query, factory_query, client_feedback |

> 注：`test_cases.json` 中仍保留部分历史 `route_v2_then_v1` 用例，但 v2.0 V3 不再支持该路由，测试脚本需相应更新。

## 训练数据参考分布

### V3 Scheduler (SFT)

| 场景 | 数量 |
|-----|------|
| `direct_answer` | ~96 |
| `boundary` | ~40 |
| `route_v2` | ~344 |
| `route_v1` | ~320 |
| **总计** | **800** |

### V2 Query Engine (SFT)

| 数据 | 数量 | 说明 |
|-----|------|------|
| SFT 训练样本 | 786 | 多轮查询策略 |
| DPO 偏好对 | 776 | chosen/rejected 对比 |
| 轮数分布 | 2轮 44%, 3轮 26%, 4轮 14%, 5+轮 16% | |
| 平均长度 | ~7,500 tokens | 最大 88K（8192 cutoff） |

## 注意事项

1. **显存要求**：同时加载 4 个 LoRA 需要约 20-24GB 显存
   - 如果显存不足，可以分批测试（`--scene` 参数）
   
2. **模型基座**：所有 LoRA 基于 `Qwen/Qwen2.5-7B-Instruct`
   - 脚本会自动下载基座模型（首次需要联网）
   
3. **工具模拟**：测试脚本会模拟工具执行（kg_query/rag_query/email_extract）
   - 返回预定义的模拟数据，不连接真实数据库
   
4. **V1 时间线**：V1 模型需要 `events_passed.json` 数据
   - 脚本会从 `email_rag_pipeline/output/` 自动加载

5. **V3 v2.0 简化**：V3 已退化为纯单轮路由器，测试脚本需适配新输出格式
   - 不再测试 `route_v2_then_v1` 场景

## 故障排查

| 问题 | 解决 |
|-----|------|
| `CUDA out of memory` | 减少 `--batch_size` 或只测单一场景 |
| `Model not found` | 检查 `rlhf/outputs/` 下模型目录是否存在 |
| `JSON decode error` | 模型输出格式不对，检查 SFT/DPO 训练是否完整 |
| `Routing always wrong` | V3 DPO 可能过拟合，检查 `test_cases.json` 分布 |
| `Multi-round not triggered` | V2 multi-round 模型未正确判断缺失，检查训练数据中的 missing 逻辑 |
