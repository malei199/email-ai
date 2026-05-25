"""
早推送服务
"""
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from email_agent.database import MorningPush, StyleNote, User
from email_agent.services.kg_adapter import query_styles_by_person, query_timeline, query_last_update
from email_agent.services.rag_adapter import query_email_events_by_date
from email_agent.config import STALE_DAYS


def generate_morning_push(db: Session, user: User, push_date: date = None) -> dict:
    """
    生成早推送内容
    
    风险判定（V1）：
    1. 已延期：存在 delay_days > 0 的事件
    2. 长时间无更新：last_update > STALE_DAYS（默认7天）
    """
    if push_date is None:
        push_date = date.today()
    
    # 检查是否已生成过
    existing = db.query(MorningPush).filter(
        MorningPush.user_id == user.id,
        MorningPush.push_date == push_date
    ).first()
    
    if existing:
        return _format_push(existing)
    
    # 查用户负责的款号
    styles = []
    if user.name:
        kg_result = query_styles_by_person(user.name)
        styles = kg_result.get("styles", [])
    
    # 获取用户备注（用于显示别名）
    style_notes = {
        note.style_id: note
        for note in db.query(StyleNote).filter(StyleNote.user_id == user.id).all()
    }
    
    risks = []
    events = []
    
    for style in styles:
        style_id = style["style_id"] if isinstance(style, dict) else style
        alias = style_notes.get(style_id, {}).alias if style_id in style_notes else None
        
        # 风险1: 已延期
        timeline = query_timeline(style_id)
        delay_events = [e for e in timeline if e.get("delay_days", 0) > 0]
        if delay_events:
            latest = max(delay_events, key=lambda x: x.get("date", ""))
            risks.append({
                "style_id": style_id,
                "alias": alias,
                "reason": f"已延期{latest['delay_days']}天（{latest.get('category', '')}）"
            })
        
        # 风险2: 长时间无更新
        last_update = query_last_update(style_id)
        days_since = last_update.get("days_since_update", 0)
        if days_since > STALE_DAYS:
            risks.append({
                "style_id": style_id,
                "alias": alias,
                "reason": f"{days_since}天无更新"
            })
        
        # 收集昨日新增事件（从events_passed.json过滤）
        recent_events = query_email_events_by_date(style_id, days=1)
        for e in recent_events:
            events.append({
                "style_id": style_id,
                "alias": alias,
                "event": f"{e.get('category', '')} - {e.get('event_type', '')}"
            })
    
    # 截断：只保留最近/最严重的5条
    risks = _sort_and_limit(risks, 5)
    events = _sort_and_limit(events, 5)
    
    # 组装Markdown内容
    content = _build_push_markdown(user.name or user.email, len(styles), risks, events)
    
    # 保存到数据库
    push = MorningPush(
        user_id=user.id,
        push_date=push_date,
        content=content,
        risk_count=len(risks),
        event_count=len(events)
    )
    db.add(push)
    db.commit()
    db.refresh(push)
    
    return _format_push(push, risks, events, len(styles))


def _build_push_markdown(name: str, total: int, risks: list, events: list) -> str:
    """构建早推送Markdown内容"""
    lines = [f"# 早安，{name}", ""]
    lines.append(f"您负责 **{total}** 个款号，今日概览如下：")
    lines.append("")
    if risks:
        lines.append(f"## ⚠️ 风险提醒（{len(risks)}个）")
        for r in risks:
            display = f"{r['style_id']}（{r['alias']}）" if r['alias'] else r['style_id']
            lines.append(f"- **{display}**：{r['reason']}")
        lines.append("")
    
    if events:
        lines.append(f"## 📋 昨日动态（{len(events)}条）")
        for e in events:
            display = f"{e['style_id']}（{e['alias']}）" if e['alias'] else e['style_id']
            lines.append(f"- **{display}**：{e['event']}")
        lines.append("")
    
    if not risks and not events:
        lines.append("✅ 今日暂无风险提醒和新增动态。")
    
    lines.append("")
    lines.append("---")
    lines.append("*数据基于昨晚23点更新的数据库*")
    
    return "\n".join(lines)


def _sort_and_limit(items: list, limit: int) -> list:
    """
    按最近更新时间排序，只保留前 limit 条。
    
    排序规则：
      - 有 delay_days 的（已延期）优先
      - 其次按 days_since_update 降序（越久无更新越靠前）
      - 最后按 reason 文本中的数字降序
    """
    def _priority_key(item):
        reason = item.get("reason", "")
        # 提取数字（延期天数或无更新天数）
        import re
        nums = re.findall(r'(\d+)', reason)
        days = int(nums[0]) if nums else 0
        return days
    
    # 复制列表避免修改原列表
    items_copy = items.copy()
    items_copy.sort(key=_priority_key, reverse=False)
    return items_copy[:limit]


def _format_push(push: MorningPush, risks=None, events=None, total_styles=0) -> dict:
    """格式化推送数据为API响应"""
    # 统一截断：只保留最近/最严重的5条
    risks = _sort_and_limit(risks or [], 5)
    events = _sort_and_limit(events or [], 5)
    
    return {
        "date": push.push_date.isoformat(),
        "greeting": f"早安，{push.user.name or push.user.email}",
        "summary": {
            "total_styles": total_styles,
            "risk_count": len(risks),
            "event_count": len(events)
        },
        "risks": risks,
        "events": events,
        "content": push.content
    }
