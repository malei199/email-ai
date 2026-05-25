"""
回答组装器
根据查询结果和用户选择的模式（简洁/详细）组装最终回答
"""
from typing import List, Optional


def build_term_answer(results: List[dict], mode: str = "detailed") -> tuple[str, List[dict]]:
    """组装术语查询回答"""
    if not results:
        return "抱歉，在知识库中没有找到相关术语。", []
    
    top = results[0]
    sources = [{"type": "term", "collection": "clothing_terms", "count": len(results)}]
    
    if mode == "concise":
        answer = f"{top['chinese']} → {top['english']}"
        return answer, sources
    
    # detailed mode
    lines = [
        f"**{top['chinese']}**",
        f"",
        f"英文：{top['english']}",
        f"分类：{top['category']}",
    ]
    
    if len(results) > 1:
        lines.append("")
        lines.append("相关术语：")
        for r in results[1:4]:
            lines.append(f"- {r['chinese']} → {r['english']}")
    
    return "\n".join(lines), sources


def build_timeline_answer(style_id: str, events: List[dict], mode: str = "detailed") -> tuple[str, List[dict]]:
    """组装时间线查询回答"""
    if not events:
        return f"款号 **{style_id}** 暂无事件记录。", [{"type": "kg", "query": "timeline", "style_id": style_id}]
    
    sources = [{"type": "kg", "query": "timeline", "style_id": style_id, "count": len(events)}]
    
    if mode == "concise":
        latest = max(events, key=lambda x: x.get("date", ""))
        return f"{style_id} 最新：{latest.get('category', '')} - {latest.get('event_type', '')}（{latest.get('date', '')}）", sources
    
    # detailed mode
    lines = [f"### 款号 {style_id} 时间线", ""]
    
    # 按日期倒序
    sorted_events = sorted(events, key=lambda x: x.get("date", ""), reverse=True)
    
    for e in sorted_events[:10]:  # 最多显示10条
        date_str = e.get("date", "")
        category = e.get("category", "")
        event_type = e.get("event_type", "")
        desc = e.get("description", "")
        delay = e.get("delay_days", 0)
        
        delay_str = ""
        if delay > 0:
            delay_str = f" ⚠️延期{delay}天"
        elif delay < 0:
            delay_str = f" ✅提前{abs(delay)}天"
        
        lines.append(f"- **{date_str}** | {category} · {event_type}{delay_str}")
        if desc:
            lines.append(f"  > {desc}")
    
    if len(sorted_events) > 10:
        lines.append("")
        lines.append(f"*共 {len(sorted_events)} 条事件，以上为最近10条*")
    
    return "\n".join(lines), sources


def build_delay_answer(style_id: str, events: List[dict], mode: str = "detailed") -> tuple[str, List[dict]]:
    """组装延期分析回答"""
    delay_events = [e for e in events if e.get("delay_days", 0) > 0]
    
    if not delay_events:
        return f"款号 **{style_id}** 当前无延期记录。", [{"type": "kg", "query": "timeline", "style_id": style_id}]
    
    sources = [{"type": "kg", "query": "timeline", "style_id": style_id, "count": len(delay_events)}]
    
    if mode == "concise":
        total_delay = sum(e.get("delay_days", 0) for e in delay_events)
        return f"{style_id} 累计延期 {total_delay} 天，涉及 {len(delay_events)} 个阶段。", sources
    
    # detailed mode
    lines = [f"### 款号 {style_id} 延期分析", ""]
    lines.append(f"共发现 **{len(delay_events)}** 个延期事件：")
    lines.append("")
    
    for e in sorted(delay_events, key=lambda x: x.get("date", "")):
        lines.append(f"- **{e.get('date', '')}** | {e.get('category', '')}")
        lines.append(f"  - 延期天数：**{e.get('delay_days', 0)} 天**")
        lines.append(f"  - 事件类型：{e.get('event_type', '')}")
        if e.get("description"):
            lines.append(f"  - 详情：{e['description']}")
        lines.append("")
    
    total = sum(e.get("delay_days", 0) for e in delay_events)
    lines.append(f"**累计延期：{total} 天**")
    
    return "\n".join(lines), sources


def build_person_answer(style_id: str, people_data: dict, mode: str = "detailed") -> tuple[str, List[dict]]:
    """组装人员查询回答"""
    people = people_data.get("people", [])
    primary = people_data.get("primary_owner", "")
    
    if not people:
        return f"款号 **{style_id}** 暂无人员记录。", [{"type": "kg", "query": "people_by_style", "style_id": style_id}]
    
    sources = [{"type": "kg", "query": "people_by_style", "style_id": style_id, "count": len(people)}]
    
    if mode == "concise":
        return f"{style_id} 负责人：{primary or people[0]}", sources
    
    lines = [f"### 款号 {style_id} 涉及人员", ""]
    if primary:
        lines.append(f"**主要负责人：{primary}**")
        lines.append("")
    
    lines.append("参与人员：")
    for p in people:
        lines.append(f"- {p}")
    
    return "\n".join(lines), sources


def build_unknown_answer(text: str) -> tuple[str, List[dict]]:
    """未知意图的兜底回答"""
    return (
        "抱歉，我不太理解您的问题。您可以尝试：\n"
        "- 查询款号进度：`CCSS230021 进度`\n"
        "- 术语翻译：`拉链的英文`\n"
        "- 延期分析：`INDOT27551 为什么延期`",
        []
    )
