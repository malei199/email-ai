"""
V1 模型调用适配器 (Phase 2: 本地 vLLM 模型)

替换 DeepSeek API，使用本地微调的 V1 时间线生成模型
"""

import json
from typing import Optional

from email_agent.services.vllm_client import call_v1


def build_v1_input_json(
    style_id: str,
    round_num: int,
    total_rounds: int,
    events: list[dict],
    event_focus: Optional[str] = None,
) -> dict:
    """
    构造 V1 输入 JSON（与 V1_DATA_SPEC.md 一致）
    
    Args:
        style_id: 款号
        round_num: 当前轮次
        total_rounds: 总轮次
        events: 该轮的事件列表
        event_focus: 用户关注的事件类型（如"样衣"），可选
    """
    event_list = []
    for e in events:
        event_list.append({
            "category": e.get("category", ""),
            "event_type": e.get("event_type", ""),
            "date": e.get("date", ""),
            "related_date": e.get("related_date", ""),
            "delay_days": e.get("delay_days") if e.get("delay_days") is not None else 0,
            "party_from": e.get("party_from", ""),
            "party_to": e.get("party_to", ""),
            "description": e.get("description", ""),
            "source_filename": e.get("source_filename", ""),
            "source_subject": e.get("source_subject", ""),
        })
    
    input_json = {
        "style_id": style_id,
        "round": round_num,
        "total_rounds": total_rounds,
        "events": event_list,
    }
    
    if event_focus:
        input_json["_user_focus"] = event_focus
    
    return input_json


def build_v1_prompt(input_json: dict) -> str:
    """
    构造 V1 模型的输入 prompt
    
    格式与训练数据中的 user message 一致
    """
    return json.dumps(input_json, ensure_ascii=False, indent=2)


async def call_v1_model(
    style_id: str,
    round_num: int,
    total_rounds: int,
    events: list[dict],
    event_focus: Optional[str] = None,
) -> str:
    """
    调用 V1 模型生成单轮分析报告
    
    Phase 2: 使用本地微调的 V1 模型（vLLM 服务）
    
    Args:
        style_id: 款号
        round_num: 当前轮次（从1开始）
        total_rounds: 总轮次
        events: 该轮的事件列表
        event_focus: 用户关注的事件类型，可选
    
    Returns:
        Markdown 格式的分析报告
    """
    # 构造输入
    input_json = build_v1_input_json(
        style_id, round_num, total_rounds, events, event_focus
    )
    
    # 构建 prompt
    prompt = build_v1_prompt(input_json)
    
    # 调用本地 V1 模型
    try:
        report = call_v1(prompt)
        return report
    except Exception as e:
        print(f"[ERROR] V1 模型调用失败 (style_id={style_id}, round={round_num}/{total_rounds}): {e}")
        # 返回降级输出
        return _build_fallback_report(style_id, round_num, total_rounds, events)


def _build_fallback_report(
    style_id: str,
    round_num: int,
    total_rounds: int,
    events: list[dict],
) -> str:
    """
    当 V1 模型调用失败时的降级输出
    """
    lines = [
        f"## 📋 款号 {style_id} 时间线分析（第 {round_num}/{total_rounds} 部分）",
        "",
        "### 一、📅 时间线梳理",
        "",
        "| 阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件 |",
        "|------|------|------|------|------|----------|",
    ]
    
    for e in events:
        category = e.get("category", "")
        event_type = e.get("event_type", "")
        date = e.get("date", "")
        delay = e.get("delay_days", 0)
        delay_str = f"{delay}天" if delay > 0 else "-"
        desc = e.get("description", "")[:30] + "..." if len(e.get("description", "")) > 30 else e.get("description", "")
        filename = e.get("source_filename", "")
        
        lines.append(f"| {category} | {event_type} | {date} | {delay_str} | {desc} | 📧 {filename} |")
    
    lines.extend([
        "",
        "### 二、⚠️ 风险点",
        "- 🟡 **模型调用失败**：当前为降级输出，请检查 vLLM 服务",
        "",
        "### 三、🛤️ 关键路径",
        "（模型调用失败，无法生成关键路径分析）",
    ])
    
    return "\n".join(lines)


# 兼容性别名（保持旧接口可用）
async def call_v1_legacy(
    style_id: str,
    round_num: int,
    total_rounds: int,
    events: list[dict],
    event_focus: Optional[str] = None,
) -> str:
    """旧接口兼容"""
    return await call_v1_model(style_id, round_num, total_rounds, events, event_focus)
