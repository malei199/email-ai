"""
联合查询编排器
处理 V2 五类问题的查询路由、款号歧义消解、KG→RAG→LLM 编排
"""
import sys
import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from email_agent.services import kg_adapter, rag_adapter


# ============ 款号歧义处理 ============

def resolve_style_ambiguity(
    person_name: Optional[str] = None,
    customer_email: Optional[str] = None,
    factory_name: Optional[str] = None,
    context_style_ids: Optional[List[str]] = None,
    max_suggestions: int = 5
) -> Dict[str, Any]:
    """
    当用户说"我这款号"但没有指定具体款号时，推断可能的款号范围
    
    策略优先级：
    1. 继承上下文（如果对话中已确认款号）
    2. 按人员查最近活跃的款号
    3. 按客户查款号
    4. 按工厂查款号
    
    Args:
        person_name: 当前用户姓名
        customer_email: 关联客户邮箱
        factory_name: 关联工厂名称
        context_style_ids: 对话上下文中已确认的款号
        max_suggestions: 最多返回几个候选款号
        
    Returns:
        {
            "resolved": True/False,
            "style_ids": ["CCAW240015", "CCAW240016"],
            "style_count": 2,
            "reason": "基于用户Paula Cheng最近活跃的2款款号",
            "needs_clarification": False,  # 是否需要用户确认
            "suggestions": [
                {"style_id": "CCAW240015", "latest_category": "调纸样", "last_update": "2024-03-15", "reason": "最近更新"}
            ]
        }
    """
    # 1. 继承上下文
    if context_style_ids:
        return {
            "resolved": True,
            "style_ids": context_style_ids,
            "style_count": len(context_style_ids),
            "reason": "继承对话上下文",
            "needs_clarification": False,
            "suggestions": []
        }
    
    candidates = []
    reason_parts = []
    
    # 2. 按人员查
    if person_name:
        result = kg_adapter.query_styles_by_person(person_name)
        styles = result.get("styles", [])
        if styles:
            # 取最近活跃的款号
            for s in styles[:max_suggestions]:
                candidates.append({
                    "style_id": s["style_id"],
                    "latest_category": s.get("latest_category", ""),
                    "last_update": s.get("last_update", ""),
                    "role": s.get("role", ""),
                    "reason": f"{person_name}的{s.get('role', '参与')}款号"
                })
            reason_parts.append(f"用户{person_name}的款号")
    
    # 3. 按客户查
    if customer_email and len(candidates) < max_suggestions:
        # 这里需要KG支持客户查款号
        # 暂时跳过，因为需要 get_styles_by_customer
        pass
    
    # 4. 按工厂查
    if factory_name and len(candidates) < max_suggestions:
        result = kg_adapter.query_styles_by_factory(factory_name)
        styles = result.get("styles", [])
        for s in styles[:max_suggestions - len(candidates)]:
            candidates.append({
                "style_id": s["style_id"],
                "last_update": s.get("last_update", ""),
                "reason": f"工厂{factory_name}的款号"
            })
        reason_parts.append(f"工厂{factory_name}的款号")
    
    if not candidates:
        return {
            "resolved": False,
            "style_ids": [],
            "style_count": 0,
            "reason": "无法推断款号范围，请提供人员姓名或具体款号",
            "needs_clarification": True,
            "suggestions": []
        }
    
    # 判断是否需要澄清
    needs_clarification = len(candidates) > 1
    
    return {
        "resolved": True,
        "style_ids": [c["style_id"] for c in candidates],
        "style_count": len(candidates),
        "reason": "; ".join(reason_parts) if reason_parts else "基于图谱查询",
        "needs_clarification": needs_clarification,
        "suggestions": candidates
    }


def narrow_style_scope(
    style_ids: List[str],
    query_text: Optional[str] = None,
    category_hint: Optional[str] = None,
    date_hint: Optional[str] = None
) -> List[str]:
    """
    根据查询语义进一步缩小款号范围
    
    例：用户问"我这款号的面料进展"
    → 过滤掉没有"面料"相关事件的款号
    
    Args:
        style_ids: 候选款号列表
        query_text: 用户查询文本
        category_hint: 阶段提示（如"面料"、"样衣"）
        date_hint: 日期提示（如"最近"、"上周"）
        
    Returns:
        缩小后的款号列表
    """
    if len(style_ids) <= 1:
        return style_ids
    
    # 从查询文本中提取阶段关键词
    category_keywords = {
        "面料": ["面料", "布料", "lab dip", "色卡", "色样"],
        "样衣": ["样衣", "船样", "产前样", "pp sample", "top", "fitting"],
        "调纸样": ["纸样", "打版", "pattern", "版型"],
        "大货": ["大货", "生产", "出货", "delivery", "bulk"],
        "拉链": ["拉链", "zipper", "拉头"],
        "纽扣": ["纽扣", "扣子", "button"],
    }
    
    # 检测查询中的阶段关键词
    detected_categories = []
    if query_text:
        query_lower = query_text.lower()
        for cat, keywords in category_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_categories.append(cat)
    
    if category_hint:
        detected_categories.append(category_hint)
    
    if not detected_categories:
        # 无法缩小范围，返回全部
        return style_ids
    
    # 过滤：只保留在 detected_categories 中有事件的款号
    filtered = []
    for style_id in style_ids:
        timeline = kg_adapter.query_timeline(style_id)
        # timeline 是事件列表
        if not timeline:
            continue
        
        # 检查是否有匹配阶段的事件
        has_match = False
        for event in timeline:
            event_cat = event.get("category", "")
            for dc in detected_categories:
                if dc in event_cat:
                    has_match = True
                    break
            if has_match:
                break
        
        if has_match:
            filtered.append(style_id)
    
    return filtered if filtered else style_ids


# ============ 查询路由 ============

def route_query(
    query_text: str,
    person_name: Optional[str] = None,
    style_id: Optional[str] = None,
    style_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    根据查询内容路由到合适的查询策略
    
    V2 五类问题分布：
    1. KG-款号总览 (25%): "我的款号进展如何"
    2. RAG-语义检索 (25%): "拉链问题怎么处理"
    3. RAG+KG-联合 (25%): "我这款号的船样进展"
    4. KG-时序/延期 (15%): "哪些款号延期了"
    5. KG-关系查询 (10%): "我和谁合作最多"
    
    Args:
        query_text: 用户查询文本
        person_name: 当前用户姓名
        style_id: 单款号（如果已确定）
        style_ids: 多款号范围
        
    Returns:
        {
            "strategy": "kg_overview" | "rag_semantic" | "hybrid" | "kg_temporal" | "kg_relational",
            "confidence": 0.85,
            "reason": "查询包含'进展'和'我的'，判断为款号总览类",
            "params": {...}
        }
    """
    query_lower = query_text.lower()
    
    # 关键词模式
    overview_keywords = ["进展", "情况", "怎么样", "状态", "概览", "总览", "summary", "overview", "status"]
    temporal_keywords = ["延期", "delay", "推迟", "late", "逾期", "deadline", "交期", "时间线", "timeline"]
    relational_keywords = ["合作", "协作", "和谁", "同事", "下属", "汇报", "collaborat", "team", "partner"]
    semantic_keywords = ["怎么", "如何", "what is", "什么是", "问题", "issue", "problem", "处理", "解决"]
    
    # 检测各类关键词
    has_overview = any(kw in query_lower for kw in overview_keywords)
    has_temporal = any(kw in query_lower for kw in temporal_keywords)
    has_relational = any(kw in query_lower for kw in relational_keywords)
    has_semantic = any(kw in query_lower for kw in semantic_keywords)
    
    # 有具体款号 → 可能是总览或联合查询
    has_style = style_id is not None or (style_ids is not None and len(style_ids) > 0)
    
    # 路由决策（按优先级排序）
    
    # 1. 关系查询（不依赖款号，优先级最高）
    if has_relational and not has_style:
        return {
            "strategy": "kg_relational",
            "confidence": 0.9,
            "reason": "查询涉及人员关系，无需款号",
            "params": {"person_name": person_name, "query_type": "collaborators"}
        }
    
    # 2. 时序/延期查询
    if has_temporal and not has_overview:
        if "工厂" in query_text or "factory" in query_lower:
            return {
                "strategy": "kg_temporal",
                "confidence": 0.85,
                "reason": "查询工厂延期情况",
                "params": {"query_type": "factory_delays"}
            }
        return {
            "strategy": "kg_temporal",
            "confidence": 0.8,
            "reason": "查询涉及延期/时间线",
            "params": {"person_name": person_name, "style_ids": style_ids}
        }
    
    # 3. 联合查询（有款号 + 有具体业务实体关键词）
    # 例如"船样进展"、"面料问题"、"拉链怎么"等
    specific_entity_keywords = ["船样", "样衣", "面料", "拉链", "纽扣", "生产", "大货", "辅料", "色卡", "色样"]
    if has_style and any(kw in query_lower for kw in specific_entity_keywords):
        return {
            "strategy": "hybrid",
            "confidence": 0.85,
            "reason": "查询包含具体业务实体且有款号，走联合查询",
            "params": {
                "style_ids": style_ids or ([style_id] if style_id else []),
                "query_text": query_text,
                "person_name": person_name
            }
        }
    
    # 4. 款号总览（明确的进展/状态/概览查询 + 有款号）
    if has_overview and has_style:
        return {
            "strategy": "kg_overview",
            "confidence": 0.85,
            "reason": "查询款号进展，有确定款号",
            "params": {"style_id": style_id, "style_ids": style_ids}
        }
    
    # 5. 其他有款号+语义的情况走联合
    if has_semantic and has_style:
        return {
            "strategy": "hybrid",
            "confidence": 0.75,
            "reason": "查询具体问题且有款号范围，需要语义+结构化联合",
            "params": {
                "style_ids": style_ids or ([style_id] if style_id else []),
                "query_text": query_text,
                "person_name": person_name
            }
        }
    
    # 5. 纯语义检索（无款号）
    if has_semantic and not has_style:
        return {
            "strategy": "rag_semantic",
            "confidence": 0.75,
            "reason": "查询具体问题但无确定款号，走语义检索",
            "params": {"query_text": query_text, "person_name": person_name}
        }
    
    # 默认：如果有款号就走总览，否则走语义
    if has_style:
        return {
            "strategy": "kg_overview",
            "confidence": 0.7,
            "reason": "默认路由：有款号走总览",
            "params": {"style_id": style_id, "style_ids": style_ids}
        }
    
    return {
        "strategy": "rag_semantic",
        "confidence": 0.6,
        "reason": "默认路由：无款号走语义检索",
        "params": {"query_text": query_text, "person_name": person_name}
    }


# ============ 联合查询执行 ============

def execute_kg_overview(style_id: str) -> Dict[str, Any]:
    """
    执行 KG 款号总览查询
    
    Returns:
        {
            "type": "kg_overview",
            "style_id": "CCSS230021",
            "data": {
                "people": [...],
                "customers": [...],
                "timeline_summary": {...},
                "last_update": {...},
                "stats": {...}
            }
        }
    """
    overview = kg_adapter.get_style_overview(style_id)
    
    # 生成统计摘要
    timeline = overview.get("timeline", [])
    categories = {}
    total_delay = 0
    delay_events = 0
    
    for event in timeline:
        cat = event.get("category", "其他")
        categories[cat] = categories.get(cat, 0) + 1
        delay = event.get("delay_days") or 0
        if delay > 0:
            total_delay += delay
            delay_events += 1
    
    return {
        "type": "kg_overview",
        "style_id": style_id,
        "data": {
            "style_id": style_id,
            "people": overview.get("people", []),
            "primary_owner": overview.get("primary_owner"),
            "customers": overview.get("customers", []),
            "timeline_summary": {
                "total_events": len(timeline),
                "categories": categories,
                "date_range": {
                    "first": timeline[0].get("date") if timeline else None,
                    "last": timeline[-1].get("date") if timeline else None,
                }
            },
            "last_update": {
                "date": overview.get("last_update"),
                "category": overview.get("latest_category"),
                "days_since": overview.get("days_since_update"),
            },
            "stats": {
                "total_delay_days": total_delay,
                "delay_event_count": delay_events,
            }
        }
    }


def execute_rag_semantic(
    query_text: str,
    style_ids: Optional[List[str]] = None,
    person_name: Optional[str] = None,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    执行 RAG 语义检索
    
    如果提供了 person_name 但没有 style_ids，先查KG获取用户的款号范围
    """
    # 如果只有人员没有款号范围，先查KG
    if person_name and not style_ids:
        kg_result = kg_adapter.query_styles_by_person(person_name)
        style_ids = [s["style_id"] for s in kg_result.get("styles", [])]
    
    # 执行语义检索
    if style_ids:
        events = rag_adapter.query_email_events(
            style_ids=style_ids,
            query_text=query_text,
            top_k=top_k
        )
    else:
        events = rag_adapter.query_email_events(
            query_text=query_text,
            top_k=top_k
        )
    
    return {
        "type": "rag_semantic",
        "query": query_text,
        "style_ids": style_ids,
        "event_count": len(events),
        "events": events
    }


def execute_hybrid(
    query_text: str,
    style_ids: List[str],
    person_name: Optional[str] = None,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    执行 KG + RAG 联合查询
    
    策略：
    1. KG 提供款号结构化信息（人员、客户、时间线摘要）
    2. RAG 提供语义匹配的具体事件
    3. 合并去重，按相关性排序
    """
    # 1. KG 结构化信息
    kg_results = []
    for style_id in style_ids[:5]:  # 限制款号数量
        overview = kg_adapter.get_style_overview(style_id)
        kg_results.append({
            "style_id": style_id,
            "people": overview.get("people", []),
            "customers": overview.get("customers", []),
            "last_update": overview.get("last_update"),
            "latest_category": overview.get("latest_category"),
            "total_events": overview.get("total_events", 0),
        })
    
    # 2. RAG 语义检索
    rag_events = rag_adapter.query_email_events(
        style_ids=style_ids,
        query_text=query_text,
        top_k=top_k
    )
    
    # 3. 按款号分组 RAG 结果
    events_by_style = {}
    for event in rag_events:
        sid = event.get("style_id", "")
        if sid not in events_by_style:
            events_by_style[sid] = []
        events_by_style[sid].append(event)
    
    return {
        "type": "hybrid",
        "query": query_text,
        "style_ids": style_ids,
        "kg_summary": kg_results,
        "rag_events": rag_events,
        "events_by_style": events_by_style,
        "total_events": len(rag_events)
    }


def execute_kg_temporal(
    query_type: str,
    person_name: Optional[str] = None,
    style_ids: Optional[List[str]] = None,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    执行 KG 时序/延期查询
    
    Args:
        query_type: "factory_delays" | "person_delays" | "style_timeline"
    """
    if query_type == "factory_delays":
        result = kg_adapter.query_factory_delays(top_k=top_k)
        return {
            "type": "kg_temporal",
            "subtype": "factory_delays",
            "factories": result.get("factories", []),
            "total_factories": result.get("total_factories", 0)
        }
    
    if query_type == "person_delays" and person_name:
        # 查该人员的所有款号，筛选有延期的
        result = kg_adapter.query_styles_by_person(person_name)
        styles = result.get("styles", [])
        delayed_styles = [
            s for s in styles
            if (s.get("total_delay_days") or 0) > 0
        ]
        delayed_styles.sort(key=lambda x: x.get("total_delay_days", 0), reverse=True)
        
        return {
            "type": "kg_temporal",
            "subtype": "person_delays",
            "person": person_name,
            "delayed_styles": delayed_styles[:top_k],
            "total_delayed": len(delayed_styles),
            "total_styles": len(styles)
        }
    
    if query_type == "style_timeline" and style_ids:
        timelines = []
        for sid in style_ids[:5]:
            timeline = kg_adapter.query_timeline(sid)
            timelines.append({
                "style_id": sid,
                "events": timeline,
                "event_count": len(timeline)
            })
        return {
            "type": "kg_temporal",
            "subtype": "style_timeline",
            "timelines": timelines
        }
    
    return {"type": "kg_temporal", "error": "参数不足"}


def execute_kg_relational(
    query_type: str,
    person_name: str,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    执行 KG 关系查询
    
    Args:
        query_type: "collaborators" | "subordinates" | "department"
    """
    if query_type == "collaborators":
        result = kg_adapter.query_collaborators(person_name, top_k=top_k)
        return {
            "type": "kg_relational",
            "subtype": "collaborators",
            "person": person_name,
            "collaborators": result.get("collaborators", []),
            "total_unique": result.get("total_unique", 0)
        }
    
    # 其他关系查询可扩展...
    return {"type": "kg_relational", "error": "未支持的查询类型"}


# ============ 主入口 ============

def execute_query(
    query_text: str,
    person_name: Optional[str] = None,
    customer_email: Optional[str] = None,
    style_id: Optional[str] = None,
    style_ids: Optional[List[str]] = None,
    context_style_ids: Optional[List[str]] = None,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    主查询入口：自动路由并执行查询
    
    完整流程：
    1. 款号歧义消解（如果没有明确款号）
    2. 查询路由（判断五类问题类型）
    3. 执行对应查询策略
    4. 返回结构化结果
    
    Args:
        query_text: 用户查询文本
        person_name: 当前用户姓名（用于推断"我"的款号）
        customer_email: 客户邮箱
        style_id: 明确的单款号
        style_ids: 明确的多款号
        context_style_ids: 对话上下文中已确认的款号
        top_k: 返回数量限制
        
    Returns:
        {
            "query": "我这款号进展如何",
            "routing": {...},
            "ambiguity": {...},
            "result": {...},
            "metadata": {
                "execution_time_ms": 150,
                "data_sources": ["kg", "rag"]
            }
        }
    """
    import time
    start_time = time.time()
    
    # 1. 查询路由（先路由，再决定是否需要歧义消解）
    routing = route_query(query_text, person_name, style_id, style_ids)
    strategy = routing["strategy"]
    params = routing["params"]
    
    # 2. 款号歧义消解（当路由需要款号或查询包含"我这款号"但没有提供时）
    ambiguity = None
    # 扩展需要款号的策略，也包括 rag_semantic 中用户说"我这款号"的情况
    has_style_reference = "款号" in query_text or "style" in query_text.lower()
    needs_style = strategy in ("kg_overview", "hybrid") or (strategy == "rag_semantic" and has_style_reference)
    if needs_style and not style_id and not style_ids:
        ambiguity = resolve_style_ambiguity(
            person_name=person_name,
            customer_email=customer_email,
            context_style_ids=context_style_ids
        )
        if ambiguity["resolved"]:
            style_ids = ambiguity["style_ids"]
            # 重新路由，现在有style_ids了
            routing = route_query(query_text, person_name, style_id, style_ids)
            strategy = routing["strategy"]
            params = routing["params"]
    
    # 3. 执行查询
    result = None
    if strategy == "kg_overview":
        target_id = style_id or (style_ids[0] if style_ids else None)
        if target_id:
            result = execute_kg_overview(target_id)
        else:
            result = {"error": "kg_overview需要款号"}
    
    elif strategy == "rag_semantic":
        result = execute_rag_semantic(
            query_text=params.get("query_text", query_text),
            style_ids=style_ids,
            person_name=person_name,
            top_k=top_k
        )
    
    elif strategy == "hybrid":
        result = execute_hybrid(
            query_text=params.get("query_text", query_text),
            style_ids=params.get("style_ids", style_ids or []),
            person_name=person_name,
            top_k=top_k
        )
    
    elif strategy == "kg_temporal":
        result = execute_kg_temporal(
            query_type=params.get("query_type", "person_delays"),
            person_name=person_name,
            style_ids=style_ids,
            top_k=top_k
        )
    
    elif strategy == "kg_relational":
        result = execute_kg_relational(
            query_type=params.get("query_type", "collaborators"),
            person_name=person_name or "",
            top_k=top_k
        )
    
    execution_time = int((time.time() - start_time) * 1000)
    
    return {
        "query": query_text,
        "routing": routing,
        "ambiguity": ambiguity,
        "result": result,
        "metadata": {
            "execution_time_ms": execution_time,
            "data_sources": ["kg"] if strategy.startswith("kg_") else (
                ["rag"] if strategy == "rag_semantic" else ["kg", "rag"]
            )
        }
    }
