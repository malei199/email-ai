# 线上监控与自动告警方案

> 针对你的服装行业邮件Agent系统，从"能跑"到"跑得稳"的监控体系建设

---

## 一、为什么需要监控

你的系统现在：
- LoRA 微调完成（198条数据，Loss降到0.02）
- 双轨RAG + 知识图谱已构建
- 可以回答时间线、术语、关系查询

但上线后会出现的问题：
- 模型突然输出乱码/格式错乱
- 某类款号查询特别慢
- 用户问了一个训练时没见过的问题，模型开始编造
- RAG检索不到内容，模型却硬要回答
- GPU显存泄漏，服务越来越慢直到崩溃

**监控的目的：早发现、早定位、早修复**

---

## 二、监控分层体系

```
┌─────────────────────────────────────────┐
│  第一层：业务层监控（用户视角）            │
│  - 回答质量、响应时间、用户满意度          │
└─────────────────────────────────────────┘
    │
┌─────────────────────────────────────────┐
│  第二层：模型层监控（AI视角）              │
│  - 输出格式、幻觉检测、置信度              │
└─────────────────────────────────────────┘
    │
┌─────────────────────────────────────────┐
│  第三层：系统层监控（工程视角）            │
│  - GPU/CPU、内存、请求量、错误率           │
└─────────────────────────────────────────┘
    │
┌─────────────────────────────────────────┐
│  第四层：数据层监控（数据视角）            │
│  - RAG检索质量、知识库覆盖率、数据新鲜度    │
└─────────────────────────────────────────┘
```

---

## 三、逐层详解（结合你的系统）

### 3.1 业务层监控

**核心问题：用户觉得好用吗？**

| 指标 | 怎么采集 | 告警阈值 |
|------|----------|----------|
| **响应时间** | 记录请求→响应的耗时 | P99 > 5秒告警 |
| **用户反馈** | 👍/👎 按钮 | 👎率 > 15%告警 |
| **会话轮数** | 用户问了多少轮才得到答案 | 平均 > 3轮告警 |
| **重复提问率** | 同一用户重复问相似问题 | > 20%告警（可能没听懂）|

**你的场景示例：**
```python
# 每次推理后记录
log_record = {
    "timestamp": "2026-04-22T10:30:00",
    "user_id": "user_123",
    "query": "AW25-KFWTS101 现在什么进度",
    "style_id": "AW25-KFWTS101",
    "response_time_ms": 2300,
    "response_length": 1250,
    "user_feedback": None,  # 用户还没点
    "intent": "timeline_query",
}
```

---

### 3.2 模型层监控

**核心问题：模型输出靠谱吗？**

这是你最需要关注的层，直接用上刚才写的 `validate_output.py`：

| 指标 | 检测方法 | 告警阈值 |
|------|----------|----------|
| **格式错误率** | `validate_output.py` 检查 Markdown 表格 | > 5%告警 |
| **幻觉率** | 输出中出现输入没有的事件/日期 | > 3%告警 |
| **遗漏率** | 输入有但输出没提到的事件 | > 10%告警 |
| **空回答率** | 模型输出为空或"我不知道" | > 5%告警 |
| **超长输出** | 超过 cutoff_len 被截断 | 单条 > 4000字符告警 |

**实时检测代码（推理时嵌入）：**
```python
from validate_output import validate

def inference_with_monitoring(style_id, prompt):
    # 1. 调用模型
    output = model.generate(prompt)
    
    # 2. 实时验证
    result = validate(style_id=style_id, output_text=output)
    
    # 3. 记录指标
    metrics.record("model.format_errors", len(result["errors"]))
    metrics.record("model.warnings", len(result["warnings"]))
    metrics.record("model.valid", 1 if result["valid"] else 0)
    
    # 4. 严重错误立即告警
    if not result["valid"]:
        alert.send(f"模型输出验证失败: style_id={style_id}, errors={result['errors']}")
    
    return output
```

**关键：不要把验证只做在离线，要嵌入到每次推理里**

---

### 3.3 系统层监控

**核心问题：服务会崩吗？**

| 指标 | 采集方式 | 告警阈值 |
|------|----------|----------|
| **GPU显存** | `nvidia-smi` 或 pynvml | 使用率 > 90%告警 |
| **GPU利用率** | `nvidia-smi` | 持续 < 10%（可能卡死）|
| **请求QPS** | 网关/代理统计 | 突增 > 300%（可能是攻击）|
| **错误率** | HTTP 5xx 统计 | > 1%告警 |
| **模型加载时间** | 记录从请求到ready的时间 | > 30秒告警 |

**你的A6000 48GB需要关注的：**
```bash
# 显存监控脚本（放到服务器定时跑）
nvidia-smi --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu \
  --format=csv -l 10 > gpu_metrics.log

# 关键：如果显存持续增长不释放 = 内存泄漏
```

---

### 3.4 数据层监控

**核心问题：RAG和知识图谱还新鲜吗？**

| 指标 | 检测方法 | 告警阈值 |
|------|----------|----------|
| **RAG检索命中率** | 查询有返回结果的比例 | < 80%告警 |
| **知识库年龄** | 最新事件日期 vs 当前日期 | 超过 30 天无更新告警 |
| **款号覆盖率** | 用户问的款号在知识库中的比例 | < 70%告警 |
| **事件提取失败率** | 新邮件提取事件为空的概率 | > 10%告警 |

**你的场景示例：**
```python
# 每天检查一次
def daily_data_check():
    # 1. 最新事件日期
    latest_event = get_latest_event_date()  # 如 2025-12-15
    days_since_update = (today - latest_event).days
    
    if days_since_update > 30:
        alert.send(f"知识库已 {days_since_update} 天未更新，最新事件: {latest_event}")
    
    # 2. 款号覆盖
    recent_queries = get_recent_queries(days=7)
    uncovered = [q for q in recent_queries if q.style_id not in knowledge_base]
    if len(uncovered) / len(recent_queries) > 0.3:
        alert.send(f"近7天 {len(uncovered)} 个款号未覆盖，需补充数据")
```

---

## 四、告警分级与响应

### 4.1 三级告警

| 级别 | 场景 | 响应方式 | 响应人 |
|------|------|----------|--------|
| **P0-紧急** | 服务完全不可用、大量幻觉输出 | 电话/短信/企微 | 技术负责人 |
| **P1-重要** | 响应时间>10s、格式错误率>10% | 企微/邮件 | 开发人员 |
| **P2-一般** | 知识库7天未更新、单条badcase | 邮件/日报 | 运维/产品 |

### 4.2 告警收敛（避免轰炸）

```python
# 同一问题5分钟内只告警一次
@throttle(seconds=300)
def alert_format_error(style_id, errors):
    send_alert(f"格式错误: {style_id}")

# 只有错误率超过阈值才告警，不是单条就报
if format_error_rate_5min > 0.05:  # 5分钟内 > 5%
    alert.send("格式错误率超标")
```

---

## 五、最小可行监控（MVP）

你不需要一开始就搞完整的监控体系，按优先级来：

### 第一阶段（本周就能做）

1. **推理时嵌入 validate_output.py**
   - 每次输出自动检查格式、幻觉、遗漏
   - 错误写入日志文件

2. **记录每次请求的元信息**
   - 时间、款号、响应时间、用户反馈
   - 存到文件或简单数据库

3. **显存监控脚本**
   - `nvidia-smi` 定时记录
   - 超过阈值打印告警

### 第二阶段（1-2周后）

4. **简单的告警通知**
   - 企微机器人/邮件
   - 每天汇总报告：请求量、错误率、平均响应时间

5. **知识库新鲜度检查**
   - 每天检查最新事件日期
   - 超过30天告警

### 第三阶段（1个月后）

6. **可视化仪表盘**
   - Grafana + Prometheus（如果熟悉）
   - 或简单的 Web 页面展示关键指标

7. **自动降级**
   - 模型输出验证失败时，自动 fallback 到 RAG 直接返回
   - 服务过载时，拒绝非关键请求

---

## 六、具体代码示例

### 6.1 推理服务嵌入监控

```python
# inference_service.py
import time
import json
from datetime import datetime
from validate_output import validate

class MonitoredInference:
    def __init__(self, model, adapter_path):
        self.model = load_model(model, adapter_path)
        self.log_file = open("inference_log.jsonl", "a")
    
    def query(self, style_id: str, user_question: str) -> dict:
        start_time = time.time()
        
        # 1. 构造 prompt
        events = get_events(style_id)
        prompt = build_prompt(style_id, events)
        
        # 2. 推理
        output = self.model.generate(prompt)
        
        # 3. 验证
        validation = validate(
            style_id=style_id,
            input_events=events,
            output_text=output
        )
        
        # 4. 记录
        record = {
            "timestamp": datetime.now().isoformat(),
            "style_id": style_id,
            "query": user_question,
            "response_time": round(time.time() - start_time, 3),
            "output_length": len(output),
            "validation_valid": validation["valid"],
            "validation_errors": validation["errors"],
            "validation_warnings": validation["warnings"],
        }
        self.log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.log_file.flush()
        
        # 5. 实时告警
        if not validation["valid"]:
            alert.send(f"[P1] 输出验证失败: {style_id}, errors={validation['errors']}")
        
        if record["response_time"] > 10:
            alert.send(f"[P1] 响应过慢: {style_id}, time={record['response_time']}s")
        
        return {
            "output": output,
            "validation": validation,
            "metrics": record,
        }
```

### 6.2 每日汇总报告

```python
# daily_report.py
import json
from collections import Counter
from datetime import datetime, timedelta

def generate_daily_report(log_file: str):
    records = []
    with open(log_file) as f:
        for line in f:
            records.append(json.loads(line))
    
    # 只取今天
    today = datetime.now().date()
    today_records = [r for r in records 
                     if datetime.fromisoformat(r["timestamp"]).date() == today]
    
    total = len(today_records)
    valid_count = sum(1 for r in today_records if r["validation_valid"])
    error_count = total - valid_count
    avg_time = sum(r["response_time"] for r in today_records) / total if total else 0
    
    # 统计常见错误
    all_errors = []
    for r in today_records:
        all_errors.extend(r.get("validation_errors", []))
    top_errors = Counter(all_errors).most_common(5)
    
    report = f"""
=== 每日监控报告 ({today}) ===
总请求数: {total}
验证通过: {valid_count} ({valid_count/total*100:.1f}%)
验证失败: {error_count} ({error_count/total*100:.1f}%)
平均响应: {avg_time:.2f}s

Top 5 错误:
"""
    for error, count in top_errors:
        report += f"  - {error}: {count}次\n"
    
    return report

# 定时发送（如每天早8点）
report = generate_daily_report("inference_log.jsonl")
send_email(report)
```

### 6.3 显存监控脚本

```bash
#!/bin/bash
# gpu_monitor.sh

THRESHOLD=90  # 显存使用率告警阈值
LOG_FILE="gpu_monitor.log"

while true; do
    # 获取显存使用率（百分比）
    MEMORY_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    MEMORY_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
    USAGE=$((MEMORY_USED * 100 / MEMORY_TOTAL))
    
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    echo "$TIMESTAMP GPU Memory: ${USAGE}% (${MEMORY_USED}MB / ${MEMORY_TOTAL}MB)" >> $LOG_FILE
    
    if [ "$USAGE" -gt "$THRESHOLD" ]; then
        echo "$TIMESTAMP [ALERT] GPU Memory usage ${USAGE}% exceeds threshold ${THRESHOLD}%" >> $LOG_FILE
        # 发送告警（企微/邮件）
        curl -X POST "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\": \"text\", \"text\": {\"content\": \"[P0] GPU显存告警: ${USAGE}%\"}}"
    fi
    
    sleep 60
done
```

---

## 七、你的下一步行动

| 优先级 | 行动 | 预计时间 |
|--------|------|----------|
| **P0** | 把 `validate_output.py` 嵌入推理服务 | 2小时 |
| **P0** | 记录每次请求的日志（jsonl格式） | 1小时 |
| **P1** | 写 `daily_report.py` 生成日报 | 2小时 |
| **P1** | 部署 `gpu_monitor.sh` 显存监控 | 30分钟 |
| **P2** | 接入企微/邮件告警 | 2小时 |
| **P2** | 知识库新鲜度检查脚本 | 1小时 |

---

## 八、核心原则

1. **监控不是为了好看，是为了快速定位问题**
   - 用户投诉时，5分钟内能找到是哪个环节出错

2. **告警不是越多越好，要有分级和收敛**
   - 避免"狼来了"，真正紧急时才打扰人

3. **从简单开始，逐步完善**
   - 先能记录和查看，再谈可视化仪表盘

4. **监控本身也要监控**
   - 如果日志文件不写了、监控脚本挂了，要知道

---

还有什么想细化的？比如：
- 具体用什么工具（Prometheus/Grafana vs 简单脚本）
- 告警通知接入企微/钉钉的具体代码
- 自动降级和熔断策略
