"""
V1 外部编排框架 (Orchestrator)

职责：
1. 接收 V3 的 route_v1 输出（style_id + 可选 event_focus）
2. 查 ChromaDB 获取该款式所有事件
3. 按 date 排序
4. 计算 token，决定分几轮
5. 串行调 V1（每轮独立）
6. 合并多轮 Markdown
7. 返回合并后的完整报告

设计原则：
- 纯代码逻辑，不依赖 LLM
- 确定性行为（相同的输入始终产生相同的输出）
- 与 V1 模型解耦，未来可替换为真实 V1
"""

import json
from typing import Optional

from email_agent.services.rag_adapter import query_email_events
from email_agent.services.v1_model_adapter import call_v1_model


# Qwen2.5-7B-Instruct context window: 32K
# 预留空间：system prompt (~500) + user prompt (~500) + output (~4000)
# 每轮事件可用 token ≈ 27K
# 每个事件 JSON 平均约 200-300 token（含字段名和值）
# 保守设置：每轮最多 60 个事件
MAX_EVENTS_PER_ROUND = 60


async def orchestrate_v1_analysis(
    style_id: str,
    event_focus: Optional[str] = None,
) -> str:
    """
    编排 V1 分析全流程
    
    Args:
        style_id: 款号
        event_focus: 可选，用户关注的事件类型（如"样衣"、"延期"）
                     从 V3 的 event 字段传入
    
    Returns:
        合并后的 V1 Markdown 报告
        如果无事件记录，返回提示信息
    """
    # Step 1: 查 ChromaDB（优先向量库）
    events = query_email_events(style_id=style_id, top_k=1000)
    
    if not events:
        return _build_no_events_report(style_id)
    
    # Step 2: 按日期排序（从早到晚）
    events = sorted(events, key=lambda e: e.get("date", ""))
    
    # Step 3: 分轮
    rounds = _split_into_rounds(events, MAX_EVENTS_PER_ROUND)
    total_rounds = len(rounds)
    
    # Step 4: 串行调 V1（每轮独立）
    reports = []
    for round_num, round_events in enumerate(rounds, 1):
        report = await call_v1_model(
            style_id=style_id,
            round_num=round_num,
            total_rounds=total_rounds,
            events=round_events,
            event_focus=event_focus,
        )
        reports.append(report)
    
    # Step 5: 合并多轮报告
    return _merge_reports(reports, style_id)


def _split_into_rounds(events: list[dict], max_per_round: int) -> list[list[dict]]:
    """
    按事件数量切分为多轮
    
    当前策略：简单按数量切分
    未来优化：基于真实 token 数切分（需要 tokenizer）
    
    Args:
        events: 全部事件列表（已排序）
        max_per_round: 每轮最大事件数
    
    Returns:
        list[round_events]
    """
    if len(events) <= max_per_round:
        return [events]
    
    rounds = []
    for i in range(0, len(events), max_per_round):
        rounds.append(events[i:i + max_per_round])
    
    return rounds


def _merge_reports(reports: list[str], style_id: str) -> str:
    """
    合并多轮 V1 报告
    
    策略：
    - 单轮：直接返回
    - 多轮：用分隔线拼接
    
    Args:
        reports: 每轮的 Markdown 报告
        style_id: 款号（用于日志）
    
    Returns:
        合并后的完整报告
    """
    if len(reports) == 1:
        return reports[0]
    
    # 多轮合并：用分隔线 + 轮次说明
    merged_parts = []
    for i, report in enumerate(reports):
        merged_parts.append(report)
        if i < len(reports) - 1:
            merged_parts.append("")
            merged_parts.append("---")
            merged_parts.append("")
    
    return "\n".join(merged_parts)


def _build_no_events_report(style_id: str) -> str:
    """
    当查不到事件时的降级报告
    
    返回格式与 V1 输出一致，便于 V3 统一处理
    """
    return f"""## 📋 款号 {style_id} 时间线分析

### 一、📅 时间线梳理

未找到款号 **{style_id}** 的相关事件记录。

可能原因：
- 该款式尚未录入系统
- 款号拼写有误（请确认格式，如 CCSS230021、INDOT27551、AW25-KFWTS101）

建议：如需进一步查询，请联系业务人员核实。

### 二、⚠️ 风险点

- 🟡 **无记录**：未找到该款式的事件数据

### 三、🛤️ 关键路径

（无数据，无法生成关键路径）
"""
