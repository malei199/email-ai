"""
V2 回答生成器
根据模板和数据生成 Markdown 回答

由外部系统调用，在 V2 输出 generate_answer function_call 后执行

策略：
1. data 中有 "message" 字段 → 直接透传（覆盖约 60% 场景）
2. 无 "message" → 按 template 匹配结构化渲染
3. 都不匹配 → JSON 降级输出
"""
import json
from typing import List, Optional


# ---------------------------------------------------------------------------
# 1. 术语翻译
# ---------------------------------------------------------------------------

def _render_term_translation(data: dict, mode: str = "detailed") -> str:
    """术语翻译"""
    term = data.get("term", "")
    translation = data.get("translation", "")
    category = data.get("category", "")
    note = data.get("note", "")
    user_guess = data.get("user_guess", "")

    if not translation:
        return f"抱歉，未找到 **{term}** 的翻译。"

    lines = [f"**{term}** 译为：**{translation}**"]

    if category:
        lines.append(f"")
        lines.append(f"分类：{category}")

    if note:
        lines.append(f"")
        lines.append(f"*{note}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. 款号列表
# ---------------------------------------------------------------------------

def _render_style_list(data: dict, mode: str = "detailed") -> str:
    """款号列表（支持 styles/style_ids/events/summaries 等多种输入）"""
    # 尝试多种可能的字段名
    items = data.get("styles") or data.get("style_ids") or data.get("events") or data.get("summaries") or data.get("delayed_styles") or data.get("high_event_styles") or []
    count = data.get("count") or data.get("total") or data.get("total_styles") or len(items)

    if not items:
        return "未找到相关款号。"

    # items 可能是字符串列表，也可能是字典列表
    lines = [f"共 **{count}** 个：", ""]

    for i, item in enumerate(items, 1):
        if isinstance(item, str):
            lines.append(f"{i}. {item}")
        elif isinstance(item, dict):
            # 尝试提取款号/描述
            sid = item.get("style_id") or item.get("id") or ""
            desc = item.get("description") or item.get("current_stage") or item.get("latest_category") or ""
            if sid and desc:
                lines.append(f"{i}. **{sid}** - {desc}")
            elif sid:
                lines.append(f"{i}. {sid}")
            else:
                lines.append(f"{i}. {json.dumps(item, ensure_ascii=False)}")
        else:
            lines.append(f"{i}. {str(item)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 我的款号进度汇总
# ---------------------------------------------------------------------------

def _render_my_styles_summary(data: dict, mode: str = "detailed") -> str:
    """我的款号进度汇总"""
    summaries = data.get("summaries") or data.get("styles") or []
    total = data.get("total") or data.get("total_styles") or len(summaries)
    truncated = data.get("truncated", False)
    has_more = data.get("has_more", False)
    zero_styles = data.get("zero_styles", [])

    if not summaries:
        if zero_styles:
            return f"共查询到 **{total}** 个款号，当前均无事件记录。"
        return "未找到您负责的款号记录。"

    risk_styles = [s for s in summaries if s.get("status") == "延期" or s.get("delay_days", 0) > 0]
    normal_styles = [s for s in summaries if s not in risk_styles]

    lines = [f"共查询到 **{total}** 个款号：", ""]

    # 延期款号
    if risk_styles:
        lines.append(f"⚠️ **延期 ({len(risk_styles)}个)**：")
        for s in risk_styles:
            delay_days = s.get("delay_days") or s.get("total_delay_days", 0)
            delay_str = f" - 延期{delay_days}天" if delay_days else ""
            stage = s.get("current_stage") or s.get("latest_category") or "未知"
            lines.append(f"  • **{s['style_id']}** - {stage}{delay_str}")
        lines.append("")

    # 正常款号
    if normal_styles:
        lines.append(f"✅ **正常 ({len(normal_styles)}个)**：")
        for s in normal_styles:
            stage = s.get("current_stage") or s.get("latest_category") or "未知"
            lines.append(f"  • **{s['style_id']}** - {stage}")
        lines.append("")

    # 截断提示
    if truncated or has_more:
        shown = len(summaries)
        lines.append(f"*仅显示前 {shown} 个，共 {total} 个款号。如需查看全部，请说\"剩下的\"*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. 款号数量统计
# ---------------------------------------------------------------------------

def _render_my_styles_count(data: dict, mode: str = "detailed") -> str:
    """我的款号数量"""
    total = data.get("total_styles", 0)
    return f"您目前负责 **{total}** 个款号。"


# ---------------------------------------------------------------------------
# 5. 工厂延期排名
# ---------------------------------------------------------------------------

def _render_factory_delay_ranking(data: dict, mode: str = "detailed") -> str:
    """工厂延期排名"""
    factories = data.get("factories", [])
    note = data.get("note", "")
    top_avg_delay = data.get("top_avg_delay")
    top_factory = data.get("top_factory")
    worst_delay = data.get("worst_delay")
    worst_factory = data.get("worst_factory")

    if not factories:
        return "暂无工厂延期数据。"

    lines = ["**工厂延期排名**：", ""]
    lines.append("| 排名 | 工厂 | 总延期天数 | 平均延期 | 涉及款号 |")
    lines.append("|------|------|-----------|---------|---------|")

    for i, f in enumerate(factories, 1):
        name = f.get("name") or f.get("factory_name") or "未知"
        total = f.get("total_delay_days", 0)
        avg = f.get("avg_delay", 0)
        count = f.get("style_count", 0)
        lines.append(f"| {i} | {name} | {total} | {avg:.1f} | {count} |")

    if worst_factory and worst_delay:
        lines.append("")
        lines.append(f"🔴 延期最严重：**{worst_factory}**（总延期 {worst_delay} 天）")

    if top_factory and top_avg_delay:
        lines.append(f"🟡 平均延期最长：**{top_factory}**（平均 {top_avg_delay:.1f} 天）")

    if note:
        lines.append("")
        lines.append(f"*{note}*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. 工厂延期统计
# ---------------------------------------------------------------------------

def _render_factory_delay_summary(data: dict, mode: str = "detailed") -> str:
    """工厂延期统计摘要"""
    factories = data.get("factories", [])
    worst_factory = data.get("worst_factory", "")
    worst_total_delay = data.get("worst_total_delay", 0)
    worst_avg_delay = data.get("worst_avg_delay", 0)
    longest_avg_factory = data.get("longest_avg_factory", "")
    longest_avg_delay = data.get("longest_avg_delay", 0)

    if not factories:
        return "暂无工厂延期统计数据。"

    lines = ["**工厂延期统计**：", ""]

    # 关键指标
    if worst_factory:
        lines.append(f"🔴 延期最严重工厂：**{worst_factory}**")
        lines.append(f"   - 总延期天数：{worst_total_delay}")
        lines.append(f"   - 平均延期：{worst_avg_delay:.1f} 天")
        lines.append("")

    if longest_avg_factory:
        lines.append(f"🟡 平均延期最长工厂：**{longest_avg_factory}**（{longest_avg_delay:.1f} 天/款）")
        lines.append("")

    # 列表
    lines.append("**工厂列表**：")
    for f in factories:
        name = f.get("name") or f.get("factory_name") or "未知"
        total = f.get("total_delay_days", 0)
        avg = f.get("avg_delay", 0)
        count = f.get("style_count", 0)
        lines.append(f"- **{name}**：总延期 {total} 天，平均 {avg:.1f} 天，{count} 个款号")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 7. 延期款号列表
# ---------------------------------------------------------------------------

def _render_delayed_styles_list(data: dict, mode: str = "detailed") -> str:
    """延期款号列表"""
    delayed = data.get("delayed_styles") or data.get("styles") or []
    total_delayed = data.get("total_delayed") or len(delayed)
    top_delays = data.get("top_delays", [])
    ahead_styles = data.get("ahead_styles", [])

    if not delayed:
        return "暂无延期款号。"

    lines = [f"**延期款号**（共 {total_delayed} 个）：", ""]

    # 先展示 top_delays（如果有）
    if top_delays:
        lines.append("| 款号 | 延期天数 | 当前阶段 |")
        lines.append("|------|---------|---------|")
        for s in top_delays:
            sid = s.get("style_id") or s.get("id", "")
            days = s.get("total_delay_days") or s.get("delay_days", 0)
            stage = s.get("latest_category") or s.get("current_stage") or "未知"
            lines.append(f"| {sid} | {days} | {stage} |")
        lines.append("")
    else:
        # 直接列款式
        for s in delayed[:20]:
            if isinstance(s, str):
                lines.append(f"- {s}")
            elif isinstance(s, dict):
                sid = s.get("style_id") or s.get("id", "")
                days = s.get("total_delay_days") or s.get("delay_days", 0)
                stage = s.get("latest_category") or s.get("current_stage") or ""
                if days and stage:
                    lines.append(f"- **{sid}** - 延期{days}天（{stage}）")
                elif days:
                    lines.append(f"- **{sid}** - 延期{days}天")
                else:
                    lines.append(f"- {sid}")
            else:
                lines.append(f"- {str(s)}")

    if len(delayed) > 20:
        lines.append(f"")
        lines.append(f"*... 等共 {total_delayed} 个款号*")

    if ahead_styles:
        lines.append("")
        lines.append(f"✅ 提前完成：{len(ahead_styles)} 个款号")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. 款号详情/概览/进度
# ---------------------------------------------------------------------------

def _render_style_detail(data: dict, mode: str = "detailed") -> str:
    """款号详情/概览/进度/时间线"""
    style_id = data.get("style_id", "")
    people = data.get("people", [])
    latest_category = data.get("latest_category") or data.get("current_stage", "")
    total_events = data.get("total_events") or data.get("event_count", 0)
    last_update = data.get("last_update", "")
    total_delay_days = data.get("total_delay_days", 0)
    by_category = data.get("by_category", {})
    categories = data.get("categories", [])
    timeline = data.get("timeline", [])
    timeline_summary = data.get("timeline_summary", {})
    delay_events = data.get("delay_events", [])

    if not style_id:
        return "款号信息不完整。"

    lines = [f"## 📋 款号 {style_id}", ""]

    # 基本信息
    info_parts = []
    if latest_category:
        info_parts.append(f"当前阶段：**{latest_category}**")
    if total_events:
        info_parts.append(f"事件数：{total_events}")
    if last_update:
        info_parts.append(f"最后更新：{last_update}")
    if total_delay_days:
        info_parts.append(f"⚠️ 累计延期：{total_delay_days} 天")

    if info_parts:
        lines.append(" | ".join(info_parts))
        lines.append("")

    # 人员
    if people:
        people_names = []
        for p in people:
            if isinstance(p, str):
                people_names.append(p)
            elif isinstance(p, dict):
                name = p.get("name") or p.get("person_name", "")
                role = p.get("role", "")
                if name and role:
                    people_names.append(f"{name}（{role}）")
                elif name:
                    people_names.append(name)
        if people_names:
            lines.append(f"**相关人员**：{', '.join(people_names[:10])}")
            lines.append("")

    # 阶段分布
    if by_category:
        lines.append("**阶段分布**：")
        for cat, count in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {cat}：{count} 个事件")
        lines.append("")
    elif categories:
        lines.append(f"**涉及阶段**：{', '.join(categories)}")
        lines.append("")

    # 时间线
    if timeline:
        lines.append("**最近事件**：")
        for event in timeline[:5]:
            if isinstance(event, dict):
                date = event.get("date", "")
                cat = event.get("category") or event.get("event_type", "")
                desc = event.get("description", "")
                delay = event.get("delay_days", 0)
                delay_str = f" [延期{delay}天]" if delay else ""
                lines.append(f"- {date} {cat}：{desc}{delay_str}")
            else:
                lines.append(f"- {str(event)}")
        lines.append("")

    # 延期事件
    if delay_events:
        lines.append(f"**延期事件**（{len(delay_events)} 个）：")
        for e in delay_events[:5]:
            if isinstance(e, dict):
                desc = e.get("description", "")
                days = e.get("delay_days", 0)
                lines.append(f"- {desc}（延期{days}天）")
            else:
                lines.append(f"- {str(e)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. 协作对象列表
# ---------------------------------------------------------------------------

def _render_collaborators_list(data: dict, mode: str = "detailed") -> str:
    """协作对象列表"""
    person_name = data.get("person_name") or data.get("person", "")
    collaborators = data.get("collaborators", [])
    total_unique = data.get("total_unique", 0)

    if not collaborators:
        if person_name:
            return f"未找到 **{person_name}** 的协作对象。"
        return "未找到协作对象。"

    lines = []
    if person_name:
        lines.append(f"**{person_name}** 的协作对象（共 {total_unique} 人）：")
    else:
        lines.append(f"**协作对象**（共 {total_unique} 人）：")
    lines.append("")

    lines.append("| 排名 | 姓名 | 共同事件 | 共同款号 |")
    lines.append("|------|------|---------|---------|")

    for i, c in enumerate(collaborators, 1):
        name = c.get("name") or c.get("collaborator_name", "未知")
        event_count = c.get("event_count", 0)
        style_count = c.get("style_count", 0)
        lines.append(f"| {i} | {name} | {event_count} | {style_count} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 10. 款号延期分析
# ---------------------------------------------------------------------------

def _render_style_delay_analysis(data: dict, mode: str = "detailed") -> str:
    """款号延期分析"""
    style_id = data.get("style_id", "")
    total_delay_days = data.get("total_delay_days", 0)
    delays_by_category = data.get("delays_by_category", {})
    delayed_stages = data.get("delayed_stages", [])
    current_bottleneck = data.get("current_bottleneck", "")

    if not style_id:
        return "款号信息不完整。"

    lines = [f"## ⚠️ 款号 {style_id} 延期分析", ""]
    lines.append(f"**累计延期：{total_delay_days} 天**")
    lines.append("")

    if current_bottleneck:
        lines.append(f"🔴 **当前瓶颈**：{current_bottleneck}")
        lines.append("")

    if delays_by_category:
        lines.append("**各阶段延期分布**：")
        for cat, days in sorted(delays_by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {cat}：{days} 天")
        lines.append("")

    if delayed_stages:
        lines.append(f"**延期阶段**：{', '.join(delayed_stages)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 11. 工厂款号相关
# ---------------------------------------------------------------------------

def _render_factory_styles(data: dict, mode: str = "detailed") -> str:
    """工厂款号（含延期/时间线/邮件等）"""
    factory_name = data.get("factory_name") or data.get("factory", "")
    total_styles = data.get("total_styles", 0)
    styles = data.get("styles", [])
    delayed_count = data.get("delayed_count", 0)
    delayed_styles = data.get("delayed_styles", [])
    selected_style = data.get("selected_style", "")
    timeline_events = data.get("timeline_events", [])
    zero_delay_styles_count = data.get("zero_delay_styles_count", 0)
    email_events = data.get("email_events", [])
    on_time_styles = data.get("on_time_styles", [])

    if not factory_name:
        return "工厂信息不完整。"

    lines = [f"## 🏭 {factory_name}", ""]

    # 统计
    stats = []
    if total_styles:
        stats.append(f"在制款号：**{total_styles}** 个")
    if delayed_count:
        stats.append(f"⚠️ 延期：**{delayed_count}** 个")
    if zero_delay_styles_count:
        stats.append(f"✅ 无延期：**{zero_delay_styles_count}** 个")
    if stats:
        lines.append(" | ".join(stats))
        lines.append("")

    # 延期款号
    if delayed_styles:
        lines.append("**延期款号**：")
        for s in delayed_styles[:10]:
            if isinstance(s, str):
                lines.append(f"- {s}")
            elif isinstance(s, dict):
                sid = s.get("style_id") or s.get("id", "")
                days = s.get("total_delay_days") or s.get("delay_days", 0)
                lines.append(f"- **{sid}**（延期{days}天）")
            else:
                lines.append(f"- {str(s)}")
        if len(delayed_styles) > 10:
            lines.append(f"- ... 等共 {len(delayed_styles)} 个")
        lines.append("")

    # 时间线
    if timeline_events:
        lines.append(f"**款号 {selected_style} 时间线**：")
        for e in timeline_events[:5]:
            if isinstance(e, dict):
                date = e.get("date", "")
                desc = e.get("description", "")
                lines.append(f"- {date} {desc}")
            else:
                lines.append(f"- {str(e)}")
        lines.append("")

    # 邮件事件
    if email_events:
        lines.append(f"**相关邮件**：")
        for e in email_events[:5]:
            if isinstance(e, dict):
                subject = e.get("subject") or e.get("description", "")
                lines.append(f"- {subject}")
            else:
                lines.append(f"- {str(e)}")
        lines.append("")

    # 准时款号
    if on_time_styles:
        lines.append(f"**准时款号**（{len(on_time_styles)} 个）：{', '.join(on_time_styles[:10])}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 12. 事件列表
# ---------------------------------------------------------------------------

def _render_event_list(data: dict, mode: str = "detailed") -> str:
    """事件列表"""
    events = data.get("events", [])
    summaries = data.get("summaries", [])

    if not events and not summaries:
        return "暂无事件记录。"

    lines = []

    # 如果有 summaries，先展示摘要
    if summaries:
        lines.append("**事件摘要**：")
        for s in summaries:
            if isinstance(s, dict):
                style_id = s.get("style_id", "")
                desc = s.get("description", "")
                count = s.get("event_count", 0)
                if style_id:
                    lines.append(f"- **{style_id}**：{desc}（{count} 个事件）")
                else:
                    lines.append(f"- {desc}")
            else:
                lines.append(f"- {str(s)}")
        lines.append("")

    # 事件详情
    if events:
        lines.append(f"**事件详情**（共 {len(events)} 个）：")
        lines.append("")
        lines.append("| 时间 | 款号 | 阶段 | 描述 | 延期 |")
        lines.append("|------|------|------|------|------|")

        for e in events[:20]:
            if isinstance(e, dict):
                date = e.get("date", "")
                sid = e.get("style_id", "")
                cat = e.get("category") or e.get("event_type", "")
                desc = e.get("description", "")[:30]
                delay = e.get("delay_days", 0)
                delay_str = f"{delay}天" if delay else "-"
                lines.append(f"| {date} | {sid} | {cat} | {desc} | {delay_str} |")
            else:
                lines.append(f"| - | - | - | {str(e)} | - |")

        if len(events) > 20:
            lines.append("")
            lines.append(f"*... 等共 {len(events)} 个事件*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 13. 摘要列表
# ---------------------------------------------------------------------------

def _render_summaries_list(data: dict, mode: str = "detailed") -> str:
    """摘要列表（款号摘要/延期摘要等）"""
    summaries = data.get("summaries", [])

    if not summaries:
        summaries = data.get("events", [])
        
    if not summaries:
        return "暂无摘要数据。"

    lines = [f"**款号摘要**（共 {len(summaries)} 个）：", ""]
    lines.append("| 款号 | 当前阶段 | 状态 | 延期天数 | 最后更新 |")
    lines.append("|------|---------|------|---------|---------|")

    for s in summaries:
        if isinstance(s, dict):
            sid = s.get("style_id", "")
            stage = s.get("current_stage") or s.get("latest_category") or "-"
            status = s.get("status", "-")
            delay = s.get("delay_days") or s.get("total_delay_days", 0)
            delay_str = f"{delay}天" if delay else "-"
            last = s.get("last_update", "")
            lines.append(f"| {sid} | {stage} | {status} | {delay_str} | {last} |")
        else:
            lines.append(f"| {str(s)} | - | - | - | - |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 14. 我的款号概览
# ---------------------------------------------------------------------------

def _render_my_styles_overview(data: dict, mode: str = "detailed") -> str:
    """我的款号概览"""
    style_overviews = data.get("style_overviews") or data.get("styles", [])
    total_styles = data.get("total_styles", 0)
    truncated = data.get("truncated", False)
    top_styles = data.get("top_styles", [])

    if not style_overviews and not top_styles:
        return "暂无款号概览数据。"

    items = style_overviews or top_styles
    lines = [f"**款号概览**（共 {total_styles} 个）：", ""]

    for item in items[:10]:
        if isinstance(item, dict):
            sid = item.get("style_id", "")
            stage = item.get("latest_category") or item.get("current_stage", "")
            events = item.get("total_events") or item.get("event_count", 0)
            people_count = len(item.get("people", []))
            lines.append(f"- **{sid}**：{stage}，{events} 个事件，{people_count} 人参与")
        else:
            lines.append(f"- {str(item)}")

    if len(items) > 10:
        lines.append(f"- ... 等共 {len(items)} 个")

    if truncated:
        lines.append("")
        lines.append(f"*仅显示前 10 个，共 {total_styles} 个款号*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

TEMPLATE_MAP = {
    # 结构化渲染模板
    "term_translation": _render_term_translation,
    "style_list": _render_style_list,
    "my_styles_summary": _render_my_styles_summary,
    "my_styles_count": _render_my_styles_count,
    "my_styles_total": _render_my_styles_count,
    "factory_delay_ranking": _render_factory_delay_ranking,
    "factory_delays_ranking": _render_factory_delay_ranking,
    "factory_delays_summary": _render_factory_delay_ranking,
    "factory_delay_summary": _render_factory_delay_summary,
    "delayed_styles_list": _render_delayed_styles_list,
    "my_styles_delays": _render_delayed_styles_list,
    "delayed_styles": _render_delayed_styles_list,
    "delay_list": _render_delayed_styles_list,
    "delayed_styles_detail": _render_delayed_styles_list,
    "my_styles_delayed": _render_delayed_styles_list,
    "my_styles_delayed_summary": _render_delayed_styles_list,
    "style_detail": _render_style_detail,
    "style_overview": _render_style_detail,
    "style_progress": _render_style_detail,
    "style_timeline": _render_style_detail,
    "style_people": _render_style_detail,
    "collaborators_list": _render_collaborators_list,
    "collaborator_list": _render_collaborators_list,
    "style_delay_analysis": _render_style_delay_analysis,
    "factory_styles_with_delays": _render_factory_styles,
    "factory_styles_timeline": _render_factory_styles,
    "factory_delayed_styles_summary": _render_factory_styles,
    "factory_delay_issues": _render_factory_styles,
    "factory_styles_with_emails": _render_factory_styles,
    "factory_no_delay_styles": _render_factory_styles,
    "factory_style_count": _render_factory_styles,
    "event_list": _render_event_list,
    "fabric_progress_abnormal": _render_event_list,
    "delayed_stages_email": _render_event_list,
    "my_styles_recent_emails": _render_event_list,
    "delay_reasons": _render_event_list,
    "transport_delay_summary": _render_event_list,
    "delayed_styles_summary": _render_summaries_list,
    "style_summaries": _render_summaries_list,
    "my_styles_update": _render_summaries_list,
    "my_styles_recent_updates": _render_summaries_list,
    "my_styles_overview": _render_my_styles_overview,
    "my_styles_event_count_analysis": _render_my_styles_overview,
    "my_styles_and_events": _render_my_styles_overview,
}


def generate_answer(template: str, data: dict, mode: str = "detailed") -> str:
    """
    根据模板和数据生成 Markdown 回答

    策略：
    1. data 中有 "message" 字段 → 直接透传（覆盖约 60% 场景）
    2. 无 "message" → 按 template 匹配结构化渲染
    3. 都不匹配 → JSON 降级输出
    """
    # 80%+ 场景：V2 已经写好了回答，直接透传
    if "message" in data:
        return data["message"]

    # 结构化场景：按模板渲染
    renderer = TEMPLATE_MAP.get(template)
    if renderer:
        return renderer(data, mode)

    # 兜底：未知模板，返回 JSON 降级输出
    return f"【查询结果】\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def generate_from_v2_call(template: str, context: dict, mode: str = "detailed") -> str:
    """
    从 V2 编排器的累积 context 中提取数据，生成回答

    由 V2Orchestrator 调用，自动从 context 中提取所需数据
    """
    data = _extract_data_for_template(template, context)
    return generate_answer(template, data, mode)


def _extract_data_for_template(template: str, context: dict) -> dict:
    """从累积 context 中提取模板所需数据"""

    # 如果 context 已经有 message，直接透传
    if "message" in context:
        return {"message": context["message"]}

    # 术语翻译
    if template == "term_translation":
        return {
            "term": context.get("term", ""),
            "translation": context.get("translation", ""),
            "category": context.get("category", ""),
            "note": context.get("note", ""),
            "user_guess": context.get("user_guess", ""),
        }

    # 款号列表
    if template in ("style_list", "delay_list"):
        return {
            "styles": context.get("styles") or context.get("style_ids") or context.get("events") or context.get("summaries") or context.get("delayed_styles") or context.get("high_event_styles") or [],
            "count": context.get("count") or context.get("total") or context.get("total_styles") or 0,
        }

    # 我的款号汇总
    if template == "my_styles_summary":
        return {
            "summaries": context.get("summaries") or context.get("styles", []),
            "total": context.get("total") or context.get("total_styles", 0),
            "truncated": context.get("truncated", False),
            "has_more": context.get("has_more", False),
            "zero_styles": context.get("zero_styles", []),
        }

    # 款号数量
    if template in ("my_styles_count", "my_styles_total"):
        return {
            "total_styles": context.get("total_styles", 0),
        }

    # 工厂延期排名
    if template in ("factory_delay_ranking", "factory_delays_ranking", "factory_delays_summary"):
        return {
            "factories": context.get("factories", []),
            "note": context.get("note", ""),
            "top_avg_delay": context.get("top_avg_delay"),
            "top_factory": context.get("top_factory"),
            "worst_delay": context.get("worst_delay"),
            "worst_factory": context.get("worst_factory"),
        }

    # 工厂延期统计
    if template == "factory_delay_summary":
        return {
            "factories": context.get("factories", []),
            "worst_factory": context.get("worst_factory", ""),
            "worst_total_delay": context.get("worst_total_delay", 0),
            "worst_avg_delay": context.get("worst_avg_delay", 0),
            "longest_avg_factory": context.get("longest_avg_factory", ""),
            "longest_avg_delay": context.get("longest_avg_delay", 0),
        }

    # 延期款号列表
    if template in ("delayed_styles_list", "my_styles_delays", "delayed_styles",
                     "delayed_styles_detail", "my_styles_delayed", "my_styles_delayed_summary"):
        return {
            "delayed_styles": context.get("delayed_styles") or context.get("styles", []),
            "total_delayed": context.get("total_delayed", 0),
            "top_delays": context.get("top_delays", []),
            "ahead_styles": context.get("ahead_styles", []),
        }

    # 款号详情/概览/进度
    if template in ("style_detail", "style_overview", "style_progress", "style_timeline", "style_people"):
        return {
            "style_id": context.get("style_id", ""),
            "people": context.get("people", []),
            "latest_category": context.get("latest_category") or context.get("current_stage", ""),
            "total_events": context.get("total_events") or context.get("event_count", 0),
            "last_update": context.get("last_update", ""),
            "total_delay_days": context.get("total_delay_days", 0),
            "by_category": context.get("by_category", {}),
            "categories": context.get("categories", []),
            "timeline": context.get("timeline", []),
            "timeline_summary": context.get("timeline_summary", {}),
            "delay_events": context.get("delay_events", []),
        }

    # 协作对象
    if template in ("collaborators_list", "collaborator_list"):
        return {
            "person_name": context.get("person_name") or context.get("person", ""),
            "collaborators": context.get("collaborators", []),
            "total_unique": context.get("total_unique", 0),
        }

    # 款号延期分析
    if template == "style_delay_analysis":
        return {
            "style_id": context.get("style_id", ""),
            "total_delay_days": context.get("total_delay_days", 0),
            "delays_by_category": context.get("delays_by_category", {}),
            "delayed_stages": context.get("delayed_stages", []),
            "current_bottleneck": context.get("current_bottleneck", ""),
        }

    # 工厂款号
    if template in ("factory_styles_with_delays", "factory_styles_timeline",
                    "factory_delayed_styles_summary", "factory_delay_issues",
                    "factory_styles_with_emails", "factory_no_delay_styles", "factory_style_count"):
        return {
            "factory_name": context.get("factory_name") or context.get("factory", ""),
            "total_styles": context.get("total_styles", 0),
            "styles": context.get("styles", []),
            "delayed_count": context.get("delayed_count", 0),
            "delayed_styles": context.get("delayed_styles", []),
            "selected_style": context.get("selected_style", ""),
            "timeline_events": context.get("timeline_events", []),
            "zero_delay_styles_count": context.get("zero_delay_styles_count", 0),
            "email_events": context.get("email_events", []),
            "on_time_styles": context.get("on_time_styles", []),
        }

    # 事件列表
    if template in ("event_list", "fabric_progress_abnormal", "delayed_stages_email",
                    "my_styles_recent_emails", "delay_reasons", "transport_delay_summary"):
        return {
            "events": context.get("events", []),
            "summaries": context.get("summaries", []),
        }

    # 摘要列表
    if template in ("delayed_styles_summary", "style_summaries", "my_styles_update", "my_styles_recent_updates"):
        return {
            "summaries": context.get("summaries", []),
        }

    # 我的款号概览
    if template in ("my_styles_overview", "my_styles_event_count_analysis", "my_styles_and_events"):
        return {
            "style_overviews": context.get("style_overviews") or context.get("styles", []),
            "total_styles": context.get("total_styles", 0),
            "truncated": context.get("truncated", False),
            "top_styles": context.get("top_styles", []),
            "events": context.get("events", []),
        }

    # 兜底：返回完整 context
    return context
