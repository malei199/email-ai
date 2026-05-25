"""
意图路由器 (V3调度器)
基于训练好的 V3 模型进行意图识别和路由决策
"""
import json
import re
from typing import Literal, Optional

from email_agent.services.vllm_client import call_v3

IntentType = Literal[
    "term_translation",   # 术语翻译
    "term_explanation",   # 术语解释
    "style_timeline",     # 款号时间线
    "style_delay",        # 延期分析
    "person_query",       # 人员查询
    "factory_query",      # 工厂查询
    "general_chat",       # 闲聊/问候
    "unknown",            # 未知意图
]

# 款号正则（复用email_rag_pipeline的规则）
STYLE_ID_PATTERNS = [
    r"\bCCSS\d{5,6}[A-Z]?\b",
    r"\bINDO[A-Z]\d{3,6}\b",
    r"\bAW\d{2}-[A-Z]+\d+\b",
    r"\bSS\d{2}[A-Z]+\d+\b",
    r"\bCCAW\d{5,6}\b",
    r"\bCDIB\d+\b",
    r"\bP\d{3}-[A-Z0-9]+-\d+\b",
    r"\b\d{7}\b",  # New Look 7位数字
]

# V3 决策到意图的映射
DECISION_TO_INTENT = {
    "direct_answer": "general_chat",
    "route_v2": "style_timeline",  # V2 处理无款号查询，后续由 V2 自行判断
    "route_v1": "style_timeline",  # V1 处理有款号的时间线/延期分析
}

# 续查关键词
CONTINUATION_KEYWORDS = [
    "剩下的", "还有吗", "继续", "然后呢", "接着",
    "下一页", "更多", "其余的", "未完", "看看剩下的",
    "还有呢", "接着看", "后面", "剩余",
]


def is_continuation(text: str) -> bool:
    """检测用户输入是否为续查意图"""
    text_lower = text.lower().strip()
    # 精确匹配续查关键词
    for kw in CONTINUATION_KEYWORDS:
        if kw in text_lower:
            return True
    # 单字"续"或"继"也可能表示续查
    if text_lower in ("续", "继", "查", "看"):
        return True
    return False


def extract_style_id(text: str) -> Optional[str]:
    """从文本中提取款号"""
    for pattern in STYLE_ID_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return None


def classify_intent(text: str, session_style_id: Optional[str] = None) -> tuple[IntentType, Optional[str], Optional[str]]:
    """
    调用 V3 模型进行意图识别和路由决策
    
    Args:
        text: 用户输入文本
        session_style_id: 当前会话已绑定的款号（用于指代消解）
    
    Returns:
        (intent_type, style_id, event_focus)
        - intent_type: 意图类型
        - style_id: 提取或继承的款号
        - event_focus: 用户关注的事件类型
    """
    # 提取款号（用于指代消解和后续处理）
    style_id = extract_style_id(text)
    if not style_id and session_style_id:
        # 检查是否有指代词
        pronouns = ["那款", "这个", "它", "这款", "该款", "此款"]
        if any(p in text for p in pronouns):
            style_id = session_style_id
    
    # 提取事件关注点
    event_focus = _extract_event_focus(text)
    
    # 调用 V3 模型进行路由决策
    try:
        v3_result = call_v3(text)
        
        # 解析 V3 输出
        decision = v3_result.get("decision", "direct_answer")
        
        # 如果 V3 提取了款号，优先使用
        if not style_id and "style_id" in v3_result:
            style_id = v3_result["style_id"]
        
        # 映射决策到意图类型
        intent_type = DECISION_TO_INTENT.get(decision, "unknown")
        
        # 如果是 route_v1 且有延期相关关键词，标记为延期分析
        if decision == "route_v1" and event_focus == "延期":
            intent_type = "style_delay"
        
        return intent_type, style_id, event_focus
        
    except Exception as e:
        # V3 调用失败，fallback 到规则提取
        print(f"[V3 调用失败] {e}, fallback 到规则匹配")
        return _fallback_classify(text, style_id, event_focus)


def _fallback_classify(text: str, style_id: Optional[str], event_focus: Optional[str]) -> tuple[IntentType, Optional[str], Optional[str]]:
    """V3 失败时的 fallback 规则匹配"""
    # 简单规则：有款号 → 时间线，无款号 → 未知
    if style_id:
        if event_focus == "延期":
            return "style_delay", style_id, event_focus
        return "style_timeline", style_id, event_focus
    
    # 检查是否是问候
    greetings = ["你好", "您好", "嗨", "hello", "hi"]
    if any(g in text.lower() for g in greetings):
        return "general_chat", style_id, event_focus
    
    return "unknown", style_id, event_focus


# 事件关注点关键词映射（与 V3 训练数据中的 event 字段对齐）
EVENT_FOCUS_PATTERNS = {
    "延期": ["延期", "延迟", "晚", "赶不及", "还能.*出货", "为什么.*延期", "根因", "原因"],
    "样衣": ["样衣", "sample", "打样", "试穿"],
    "封样": ["封样", "签字样", "sealed", "approval sample"],
    "面料": ["面料", "布料", "fabric", "lab dip", "色卡"],
    "出货": ["出货", "发货", "shipment", "ship", "delivery"],
    "拉链": ["拉链", "zipper", "拉锁"],
    "尺寸": ["尺寸", "尺码", "规格", "size", "measurement"],
    "客户回复": ["客户回复", "客人回复", "客户意见", "客人确认", "feedback"],
    "工厂问题": ["工厂问题", "工厂反映", "工厂困难", "factory issue"],
    "Lab Dip": ["lab dip", "色卡", "染色小样"],
    "面料确认": ["面料确认", "布料确认"],
}


def _extract_event_focus(text: str) -> Optional[str]:
    """从用户文本中提取关注的事件类型"""
    for focus, patterns in EVENT_FOCUS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return focus
    return None


def should_use_v1_model(intent: IntentType, text: str) -> bool:
    """
    判断是否需要调用 V1 时间线推理模型
    基于 V3 的决策，但保留辅助判断
    """
    # V3 已经做了路由决策，这里保留作为兼容性接口
    # 实际路由由 classify_intent 中的 V3 调用决定
    return intent in ["style_timeline", "style_delay"]


def should_use_v2_model(intent: IntentType) -> bool:
    """
    判断是否需要调用 V2 多轮工具调用模型
    基于 V3 的决策
    """
    return intent in ["style_timeline", "style_delay", "person_query", "factory_query"]


def route(text: str, session_style_id: Optional[str] = None) -> dict:
    """
    完整的路由函数，返回结构化决策结果
    
    Returns:
        {
            "decision": "direct_answer|route_v2|route_v1|continuation",
            "intent": "意图类型",
            "style_id": "款号或None",
            "event_focus": "事件关注点或None",
            "v3_raw": {}  # V3 原始输出
        }
    """
    # 先检测续查意图
    if is_continuation(text):
        return {
            "decision": "continuation",
            "intent": "continuation",
            "style_id": session_style_id,
            "event_focus": None,
        }
    
    intent, style_id, event_focus = classify_intent(text, session_style_id)
    
    # 确定路由决策
    if intent == "general_chat":
        decision = "direct_answer"
    elif intent in ["style_timeline", "style_delay"] and style_id:
        decision = "route_v1"
    else:
        decision = "route_v2"
    
    return {
        "decision": decision,
        "intent": intent,
        "style_id": style_id,
        "event_focus": event_focus,
    }
