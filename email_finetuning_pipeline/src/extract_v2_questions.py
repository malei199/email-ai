#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2 问题生成与模拟验证（重构版）

基于 CALL_CHAIN_RULES + 单轮接口配置生成问题，确保与 v2_executor 完全对齐。

流程：
  1. 遍历所有查询链配置（CALL_CHAIN_RULES）和单轮接口
  2. 按 QUESTION_DISTRIBUTION 分配的目标数量采样真实数据
  3. 用 DeepSeek 基于采样数据生成自然语言问题
  4. 自动填充标准格式的 requires_interface（含 result 字段）
  5. 调用 v2_executor 验证问题可执行性
  6. 保存结果

输出：
  - email_finetuning_pipeline/datasets/v2_questions.json

使用：
    python extract_v2_questions.py --target 1000
"""

import os
import sys
import json
import argparse
import random
import time
import re
from datetime import datetime
from collections import defaultdict

# 复用 V1 的 DeepSeek client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_v1_timeline_dataset import (
    get_deepseek_client,
    DEEPSEEK_MODEL,
    MAX_RETRIES,
    RETRY_DELAY,
    REQUEST_TIMEOUT,
)

# 导入 v2_executor
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
from email_agent.services.v2_executor import V2FunctionExecutor, CALL_CHAIN_RULES

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_FILE = os.path.join(_SCRIPT_DIR, "../datasets/v2_questions.json")

# 接口到 name 的映射
INTERFACE_TO_NAME = {
    "my_styles": "kg_query",
    "person_styles": "kg_query",
    "factory_styles": "kg_query",
    "find_styles_with_conditions": "kg_query",
    "style_overview": "kg_query",
    "style_summaries": "kg_query",
    "timeline": "kg_query",
    "collaborators": "kg_query",
    "factory_delays": "kg_query",
    "term_translation": "rag_query",
    "semantic_search": "rag_query",
    "semantic_search_by_date": "rag_query",
    "semantic_search_by_conditions": "rag_query",
}

# result 字段预定义（标准格式）
RESULT_FIELDS = {
    "kg_query.my_styles": [
        "styles", "styles.style_id", "styles.latest_category", "styles.event_count",
        "styles.total_delay_days", "total_styles"
    ],
    "kg_query.person_styles": [
        "styles", "styles.style_id", "styles.latest_category", "styles.event_count",
        "styles.total_delay_days", "total_styles"
    ],
    "kg_query.factory_styles": [
        "styles", "styles.style_id", "styles.total_delay_days", "total_styles"
    ],
    "kg_query.find_styles_with_conditions": [
        "styles", "styles.style_id", "styles.matched_categories", "styles.total_delay_days", "total"
    ],
    "kg_query.style_overview": [
        "style_id", "people", "timeline", "by_category", "by_category.面料", "by_category.封样",
        "total_events", "latest_category", "last_update"
    ],
    "kg_query.style_summaries": [
        "summaries", "summaries.style_id", "summaries.status", "summaries.current_stage",
        "summaries.delay_days", "summaries.last_update", "total"
    ],
    "kg_query.timeline": [
        "events", "events.description", "events.date", "events.delay_days", "events.category"
    ],
    "kg_query.collaborators": [
        "collaborators", "collaborators.name", "collaborators.event_count", "collaborators.style_count", "total_unique"
    ],
    "kg_query.factory_delays": [
        "factories", "factories.name", "factories.total_delay_days", "factories.avg_delay", "total_factories"
    ],
    "rag_query.term_translation": [
        "translations", "translations.chinese", "translations.english", "translations.category", "best_match"
    ],
    "rag_query.semantic_search": [
        "events", "events.style_id", "events.description", "events.category", "events.score", "events.delay_days", "total"
    ],
    "rag_query.semantic_search_by_date": [
        "events", "events.id", "events.description", "events.style_id", "events.category",
        "events.date", "events.delay_days", "total"
    ],
    "rag_query.semantic_search_by_conditions": [
        "events", "events.id", "events.description", "events.style_id", "events.category",
        "events.date", "events.delay_days", "total"
    ],
}

# 接口描述
INTERFACE_DESCRIPTIONS = {
    "my_styles": "获取当前登录用户的款号列表（无需指定人名）",
    "person_styles": "获取指定人员的款号列表",
    "factory_styles": "获取指定工厂的款号列表",
    "find_styles_with_conditions": "按条件（阶段、延期天数等）筛选款号",
    "style_overview": "获取单个款号的完整概览（阶段分布、人员、事件数）",
    "style_summaries": "批量获取多个款号的摘要信息",
    "timeline": "获取单个款号的时间线事件",
    "collaborators": "获取与指定人员协作最多的同事列表",
    "factory_delays": "获取各工厂的延期统计排名",
    "term_translation": "翻译服装行业术语（中英对照）",
    "semantic_search": "基于语义相似度检索邮件事件",
    "semantic_search_by_date": "检索最近N天的邮件事件",
    "semantic_search_by_conditions": "按条件（阶段、延期天数等）检索邮件事件",
}

# 单轮接口类型（不在 CALL_CHAIN_RULES 中或可作为独立调用）
SINGLE_INTERFACE_TYPES = [
    "my_styles", "person_styles", "factory_styles", "find_styles_with_conditions",
    "collaborators", "factory_delays", "term_translation",
    "semantic_search", "semantic_search_by_date", "semantic_search_by_conditions",
    "style_overview", "style_summaries", "timeline",
]

# 问题分布配置（总计 253 条，可按比例扩展到 1000+）
QUESTION_DISTRIBUTION = {
    # === 查询链（33种，按 CALL_CHAIN_RULES）===
    "my_styles -> style_overview": 12,
    "my_styles -> style_summaries": 8,
    "my_styles -> timeline": 8,
    "my_styles -> semantic_search": 12,
    "my_styles -> semantic_search_by_date": 8,
    "my_styles -> semantic_search_by_conditions": 8,
    "person_styles -> style_overview": 6,
    "person_styles -> style_summaries": 4,
    "person_styles -> timeline": 4,
    "person_styles -> semantic_search": 6,
    "person_styles -> semantic_search_by_date": 4,
    "person_styles -> semantic_search_by_conditions": 4,
    "factory_styles -> style_overview": 3,
    "factory_styles -> style_summaries": 3,
    "factory_styles -> timeline": 3,
    "factory_styles -> semantic_search": 3,
    "factory_styles -> semantic_search_by_date": 3,
    "factory_styles -> semantic_search_by_conditions": 3,
    "find_styles_with_conditions -> style_overview": 3,
    "find_styles_with_conditions -> style_summaries": 3,
    "find_styles_with_conditions -> timeline": 3,
    "find_styles_with_conditions -> semantic_search": 3,
    "find_styles_with_conditions -> semantic_search_by_date": 3,
    "find_styles_with_conditions -> semantic_search_by_conditions": 3,
    "semantic_search -> style_overview": 4,
    "semantic_search -> style_summaries": 2,
    "semantic_search -> timeline": 2,
    "semantic_search_by_date -> style_overview": 4,
    "semantic_search_by_date -> style_summaries": 2,
    "semantic_search_by_date -> timeline": 2,
    "semantic_search_by_conditions -> style_overview": 4,
    "semantic_search_by_conditions -> style_summaries": 2,
    "semantic_search_by_conditions -> timeline": 2,

    # === 单轮查询 ===
    "my_styles": 20,
    "person_styles": 5,
    "factory_styles": 5,
    "find_styles_with_conditions": 5,
    "collaborators": 15,
    "factory_delays": 8,
    "term_translation": 12,
    "semantic_search": 8,
    "semantic_search_by_date": 8,
    "semantic_search_by_conditions": 8,
    "style_overview": 5,
    "style_summaries": 5,
    "timeline": 5,
}


# ---------------------------------------------------------------------------
# Prompt 模板
# ---------------------------------------------------------------------------

CHAIN_PROMPT_TEMPLATE = """你是服装行业跟单员。基于以下真实业务数据，生成 {count} 个自然、口语化的用户问题。

【查询能力】
系统支持查询链：先执行一级查询获取范围，再自动执行二级查询获取详情。
当前查询链：{primary_type} -> {secondary_type}

一级查询（{primary_type}）：{primary_desc}
二级查询（{secondary_type}）：{secondary_desc}

【真实数据片段】
一级查询结果（示例）：
{primary_data}

二级查询结果（示例，基于一级第一个结果）：
{secondary_example}

【任务】
生成 {count} 个用户问题，要求：
1. 自然、口语化，像真实跟单员提问
2. 必须能用当前查询链回答
3. 不出现具体款号或订单号
4. 问题中不要提到人名（如Paula Cheng），用"我"代替
5. 如果一级是my_styles，问题要说"我的款号""我跟的款号"等
6. 如果一级是person_styles，问题可以说"Paula Cheng的款号"或"我跟的款号"

输出格式（JSON）：
{{"questions": [
  {{
    "question": "...",
    "reasoning": "为什么这个查询链能回答"
  }}
]}}
"""

SINGLE_PROMPT_TEMPLATE = """你是服装行业跟单员。基于以下真实业务数据，生成 {count} 个自然、口语化的用户问题。

【查询能力】
单轮查询：{interface_type}
描述：{interface_desc}

【真实数据片段】
{data}

【任务】
生成 {count} 个用户问题，要求：
1. 自然、口语化，像真实跟单员提问
2. 必须能用当前接口回答
3. 不出现具体款号或订单号
4. 问题中不要提到人名（如Paula Cheng），用"我"代替
5. 如果查询的是当前用户，问题要说"我的款号""我跟的款号"等

输出格式（JSON）：
{{"questions": [
  {{
    "question": "...",
    "reasoning": "为什么这个接口能回答"
  }}
]}}
"""


# ---------------------------------------------------------------------------
# 进度条
# ---------------------------------------------------------------------------

def _print_progress_bar(current: int, total: int, prefix: str = "", suffix: str = "", bar_length: int = 40):
    if total == 0:
        return
    filled = int(bar_length * current / total)
    bar = "█" * filled + "░" * (bar_length - filled)
    percent = current / total * 100
    sys.stdout.write(f"\r  {prefix} |{bar}| {current}/{total} ({percent:.1f}%) {suffix}")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# 辅助函数：采样
# ---------------------------------------------------------------------------

def _get_default_person() -> str:
    """返回默认高频人员"""
    import email_agent.services.kg_adapter as kg_adapter
    candidates = ["Paula Cheng", "Iris Jiang", "Lisa Sun", "Sunny Padda"]
    best = None
    best_count = 0
    for p in candidates:
        try:
            r = kg_adapter.query_person_styles_with_stats(p)
            cnt = r.get("total_styles", 0)
            if cnt > best_count:
                best_count = cnt
                best = p
        except:
            pass
    return best or "Paula Cheng"


def _sample_factory_name() -> str:
    """采样一个真实工厂名"""
    import email_agent.services.kg_adapter as kg_adapter
    try:
        result = kg_adapter.query_factory_delays(top_k=20)
        factories = result.get("factories", [])
        if factories:
            return random.choice(factories)["name"]
    except:
        pass
    return "南通利丰"


def _sample_conditions() -> dict:
    """采样 find_styles_with_conditions 的条件"""
    conditions = {}
    if random.random() > 0.5:
        categories = random.sample(["面料", "封样", "船样", "出货", "修改样", "定辅料"], k=random.randint(1, 3))
        conditions["categories"] = categories
    if random.random() > 0.5:
        conditions["min_delay_days"] = random.choice([1, 3, 5, 7])
    return conditions


def _sample_search_conditions() -> dict:
    """采样 semantic_search_by_conditions 的条件"""
    conditions = {}
    # 总是包含 categories，避免空条件返回太多数据
    categories = random.sample(["面料", "封样", "船样", "出货", "修改样", "定辅料"], k=random.randint(1, 3))
    conditions["categories"] = categories
    # 50% 概率加 min_delay_days
    if random.random() > 0.5:
        conditions["min_delay_days"] = random.choice([1, 3, 5, 7])
    return conditions


def _sample_search_query() -> str:
    """采样语义检索查询词"""
    queries = [
        "拉链", "面料", "延期", "问题", "确认", "修改", "出货",
        "封样", "船样", "颜色", "尺寸", "logo", "辅料",
        "客人意见", "工厂回复", "不同意", "重新做", "急",
    ]
    return random.choice(queries)


def _sample_term() -> str:
    """采样术语"""
    terms = [
        "taffeta", "enzyme wash", "invisible zipper", "rib knit",
        "pilling", "色牢度", "克重", "门幅", "缩水率",
        "塔夫绸", "牛仔布", "摇粒绒", "莫代尔",
    ]
    return random.choice(terms)


def _sample_style_id() -> str:
    """采样一个真实款号"""
    import email_agent.services.kg_adapter as kg_adapter
    try:
        result = kg_adapter.query_person_styles_with_stats("Paula Cheng")
        styles = result.get("styles", [])
        if styles:
            return random.choice(styles)["style_id"]
    except:
        pass
    return "AW25-KFWTS101"


def _sample_style_ids() -> list:
    """采样多个真实款号"""
    import email_agent.services.kg_adapter as kg_adapter
    try:
        result = kg_adapter.query_person_styles_with_stats("Paula Cheng")
        styles = result.get("styles", [])
        if styles:
            return [s["style_id"] for s in random.sample(styles, min(3, len(styles)))]
    except:
        pass
    return ["AW25-KFWTS101", "AW25-KFWTT156"]


def _extract_dependency_values(result: dict, primary_type: str) -> list:
    """从一级结果中提取依赖值（款号列表或事件列表）"""
    if primary_type in ("my_styles", "person_styles", "factory_styles", "find_styles_with_conditions"):
        key = primary_type
        styles = result.get(key, {}).get("styles", [])
        return [s["style_id"] for s in styles if s.get("style_id")]
    elif primary_type in ("semantic_search", "semantic_search_by_date", "semantic_search_by_conditions"):
        key = primary_type
        events = result.get(key, {}).get("events", [])
        style_ids = []
        seen = set()
        for e in events:
            sid = e.get("style_id")
            if sid and sid not in seen:
                style_ids.append(sid)
                seen.add(sid)
        return style_ids
    return []


def _truncate_for_prompt(data: dict, max_items: int = 3) -> dict:
    """截断数据用于 Prompt（避免过长）"""
    if not isinstance(data, dict):
        return data
    truncated = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list) and len(value) > max_items:
            truncated[key] = value[:max_items]
            truncated[key + "_count"] = len(value)
        else:
            truncated[key] = value
    return truncated


# ---------------------------------------------------------------------------
# 构建查询调用
# ---------------------------------------------------------------------------

def _build_primary_call(interface_type: str, default_person: str) -> dict:
    """构建一级查询调用"""
    name = INTERFACE_TO_NAME[interface_type]
    result = RESULT_FIELDS[f"{name}.{interface_type}"]

    if interface_type == "my_styles":
        return {"name": name, "params": {"type": "my_styles"}, "result": result}
    elif interface_type == "person_styles":
        return {"name": name, "params": {"type": "person_styles", "person_name": default_person}, "result": result}
    elif interface_type == "factory_styles":
        factory_name = _sample_factory_name()
        return {"name": name, "params": {"type": "factory_styles", "factory_name": factory_name}, "result": result}
    elif interface_type == "find_styles_with_conditions":
        conditions = _sample_conditions()
        return {"name": name, "params": {"type": "find_styles_with_conditions", **conditions}, "result": result}
    elif interface_type == "semantic_search":
        query = _sample_search_query()
        return {"name": name, "params": {"type": "semantic_search", "query": query}, "result": result}
    elif interface_type == "semantic_search_by_date":
        return {"name": name, "params": {"type": "semantic_search_by_date", "days": 365}, "result": result}
    elif interface_type == "semantic_search_by_conditions":
        conditions = _sample_search_conditions()
        return {"name": name, "params": {"type": "semantic_search_by_conditions", **conditions}, "result": result}
    else:
        raise ValueError(f"未知一级接口: {interface_type}")


def _build_secondary_call(interface_type: str, dependency_value) -> dict:
    """构建二级查询调用（依赖值已提取）"""
    name = INTERFACE_TO_NAME[interface_type]
    result = RESULT_FIELDS[f"{name}.{interface_type}"]

    if interface_type == "style_overview":
        return {"name": name, "params": {"type": "style_overview", "style_id": dependency_value}, "result": result}
    elif interface_type == "style_summaries":
        style_ids = dependency_value if isinstance(dependency_value, list) else [dependency_value]
        return {"name": name, "params": {"type": "style_summaries", "style_ids": style_ids[:5]}, "result": result}
    elif interface_type == "timeline":
        return {"name": name, "params": {"type": "timeline", "style_id": dependency_value}, "result": result}
    elif interface_type in ("semantic_search", "semantic_search_by_date", "semantic_search_by_conditions"):
        style_ids = dependency_value if isinstance(dependency_value, list) else [dependency_value]
        params = {"type": interface_type, "style_ids": style_ids[:10]}
        if interface_type == "semantic_search":
            params["query"] = _sample_search_query()
        elif interface_type == "semantic_search_by_date":
            params["days"] = 365
        return {"name": name, "params": params, "result": result}
    else:
        raise ValueError(f"未知二级接口: {interface_type}")


def _build_single_call(interface_type: str, default_person: str) -> dict:
    """构建单轮查询调用"""
    name = INTERFACE_TO_NAME[interface_type]
    result = RESULT_FIELDS[f"{name}.{interface_type}"]

    if interface_type == "my_styles":
        return {"name": name, "params": {"type": "my_styles"}, "result": result}
    elif interface_type == "person_styles":
        return {"name": name, "params": {"type": "person_styles", "person_name": default_person}, "result": result}
    elif interface_type == "factory_styles":
        factory_name = _sample_factory_name()
        return {"name": name, "params": {"type": "factory_styles", "factory_name": factory_name}, "result": result}
    elif interface_type == "find_styles_with_conditions":
        conditions = _sample_conditions()
        return {"name": name, "params": {"type": "find_styles_with_conditions", **conditions}, "result": result}
    elif interface_type == "collaborators":
        return {"name": name, "params": {"type": "collaborators", "person_name": default_person, "top_k": 10}, "result": result}
    elif interface_type == "factory_delays":
        return {"name": name, "params": {"type": "factory_delays", "top_k": 10}, "result": result}
    elif interface_type == "term_translation":
        query = _sample_term()
        return {"name": name, "params": {"type": "term_translation", "query": query}, "result": result}
    elif interface_type == "semantic_search":
        query = _sample_search_query()
        return {"name": name, "params": {"type": "semantic_search", "query": query}, "result": result}
    elif interface_type == "semantic_search_by_date":
        return {"name": name, "params": {"type": "semantic_search_by_date", "days": 365}, "result": result}
    elif interface_type == "semantic_search_by_conditions":
        conditions = _sample_search_conditions()
        return {"name": name, "params": {"type": "semantic_search_by_conditions", **conditions}, "result": result}
    elif interface_type == "style_overview":
        style_id = _sample_style_id()
        return {"name": name, "params": {"type": "style_overview", "style_id": style_id}, "result": result}
    elif interface_type == "style_summaries":
        style_ids = _sample_style_ids()
        return {"name": name, "params": {"type": "style_summaries", "style_ids": style_ids}, "result": result}
    elif interface_type == "timeline":
        style_id = _sample_style_id()
        return {"name": name, "params": {"type": "timeline", "style_id": style_id}, "result": result}
    else:
        raise ValueError(f"未知单轮接口: {interface_type}")


def _build_chain_interfaces(primary_type: str, secondary_type: str, default_person: str) -> list:
    """构建查询链的 requires_interface（标准格式，用于训练数据）"""
    # 一级调用（params 中保留必要的入参）
    primary_call = _build_primary_call(primary_type, default_person)
    # 二级调用（params 中不包含 style_id/style_ids，由查询链自动展开）
    secondary_call = {"name": INTERFACE_TO_NAME[secondary_type], "params": {"type": secondary_type}, "result": RESULT_FIELDS[f"{INTERFACE_TO_NAME[secondary_type]}.{secondary_type}"]}
    return [primary_call, secondary_call]


# ---------------------------------------------------------------------------
# 数据采样（按接口组合）
# ---------------------------------------------------------------------------

def sample_chain_data(primary_type: str, secondary_type: str, executor: V2FunctionExecutor, default_person: str = "Paula Cheng") -> dict:
    """采样查询链的真实数据"""
    # 1. 执行一级查询
    primary_call = _build_primary_call(primary_type, default_person)
    primary_result = executor.execute([primary_call])

    if primary_result.get("status") != "success":
        return None

    # 2. 提取依赖值
    dependency_values = _extract_dependency_values(primary_result, primary_type)
    if not dependency_values:
        return None

    # 3. 执行二级查询（用第一个依赖值作为示例）
    secondary_call = _build_secondary_call(secondary_type, dependency_values[0])
    secondary_result = executor.execute([secondary_call])

    return {
        "chain_type": f"{primary_type} -> {secondary_type}",
        "primary_type": primary_type,
        "secondary_type": secondary_type,
        "primary_data": _truncate_for_prompt(primary_result),
        "secondary_example": _truncate_for_prompt(secondary_result),
        "dependency_count": len(dependency_values),
    }


def sample_single_data(interface_type: str, executor: V2FunctionExecutor, default_person: str = "Paula Cheng") -> dict:
    """采样单轮接口的真实数据"""
    call = _build_single_call(interface_type, default_person)
    result = executor.execute([call])

    if result.get("status") != "success":
        return None

    return {
        "interface_type": interface_type,
        "data": _truncate_for_prompt(result),
    }


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------

def _call_deepseek_for_questions(client, prompt: str, max_retries: int = MAX_RETRIES) -> str:
    """调用 DeepSeek API 生成问题"""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个专业的服装行业跟单助手，擅长生成自然的业务提问。只输出 JSON 格式。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=2048,
                timeout=REQUEST_TIMEOUT,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"      DeepSeek 调用失败: {e}")
                return ""
    return ""


def _call_deepseek_and_parse(deepseek_client, prompt: str) -> list:
    """调用 DeepSeek 并解析返回的 JSON"""
    for attempt in range(3):
        try:
            response = _call_deepseek_for_questions(deepseek_client, prompt, max_retries=1)
            if not response:
                continue

            # 提取 JSON
            try:
                result = json.loads(response)
                return result.get("questions", [])
            except json.JSONDecodeError:
                # 尝试从 Markdown 代码块提取
                json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(1))
                    return result.get("questions", [])

                # 尝试直接找 JSON 对象
                obj_match = re.search(r'\{.*"questions".*\}', response, re.DOTALL)
                if obj_match:
                    result = json.loads(obj_match.group(0))
                    return result.get("questions", [])
        except Exception as e:
            continue

    return []


def generate_questions_for_chain(
    primary_type: str,
    secondary_type: str,
    sample: dict,
    deepseek_client,
    count: int = 3,
) -> list:
    """用 DeepSeek 基于查询链采样数据生成问题"""
    prompt = CHAIN_PROMPT_TEMPLATE.format(
        count=count,
        primary_type=primary_type,
        secondary_type=secondary_type,
        primary_desc=INTERFACE_DESCRIPTIONS.get(primary_type, ""),
        secondary_desc=INTERFACE_DESCRIPTIONS.get(secondary_type, ""),
        primary_data=json.dumps(sample.get("primary_data", {}), ensure_ascii=False, indent=2),
        secondary_example=json.dumps(sample.get("secondary_example", {}), ensure_ascii=False, indent=2),
    )
    return _call_deepseek_and_parse(deepseek_client, prompt)


def generate_questions_for_single(
    interface_type: str,
    sample: dict,
    deepseek_client,
    count: int = 3,
) -> list:
    """用 DeepSeek 基于单轮接口采样数据生成问题"""
    prompt = SINGLE_PROMPT_TEMPLATE.format(
        count=count,
        interface_type=interface_type,
        interface_desc=INTERFACE_DESCRIPTIONS.get(interface_type, ""),
        data=json.dumps(sample.get("data", {}), ensure_ascii=False, indent=2),
    )
    return _call_deepseek_and_parse(deepseek_client, prompt)


# ---------------------------------------------------------------------------
# 质量筛选
# ---------------------------------------------------------------------------

def filter_questions(questions: list) -> list:
    """筛选高质量问题"""
    filtered = []
    seen = set()

    for q in questions:
        if isinstance(q, str):
            q_text = q
            q_data = {"question": q}
        elif isinstance(q, dict):
            q_text = q.get("question", "")
            q_data = q
        else:
            continue

        q_text = q_text.strip()
        if not q_text:
            continue

        # 去重
        if q_text in seen:
            continue
        seen.add(q_text)

        # 长度检查
        if len(q_text) < 5 or len(q_text) > 100:
            continue

        # 必须包含"我"（用户视角）
        if "我" not in q_text:
            continue

        # 不能出现具体款号格式
        if re.search(r'\bCCSS\d+\b|\bINDO[A-Z]\d+\b|\bAW\d+-[A-Z]+\d+\b', q_text, re.IGNORECASE):
            continue

        # 不能出现订单号
        if "订单号" in q_text or "order" in q_text.lower():
            continue

        filtered.append(q_data)

    return filtered


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def _compute_interface_distribution(questions: list) -> dict:
    """计算接口分布统计"""
    dist = {}
    for q in questions:
        interfaces = q.get("requires_interface", [])
        if len(interfaces) >= 2:
            key = f"{interfaces[0]['params']['type']} -> {interfaces[1]['params']['type']}"
        elif len(interfaces) == 1:
            key = interfaces[0]['params']['type']
        else:
            key = "unknown"
        dist[key] = dist.get(key, 0) + 1
    return dist


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def extract_all_questions(
    output_path: str,
    target_total: int = 1000,
    questions_per_batch: int = 3,
):
    """
    基于 CALL_CHAIN_RULES + 单轮接口配置生成问题

    Args:
        output_path: 输出文件路径
        target_total: 目标总问题数（按比例缩放 QUESTION_DISTRIBUTION）
        questions_per_batch: 每次 DeepSeek 调用生成的问题数
    """
    print("[1/5] 初始化 V2 执行器...")
    executor = V2FunctionExecutor()
    print("      V2 执行器已加载")

    print("\n[2/5] 初始化 DeepSeek...")
    deepseek_client = None
    try:
        deepseek_client = get_deepseek_client()
        print("      DeepSeek API 已启用")
    except Exception as e:
        print(f"      DeepSeek API 初始化失败: {e}")
        return

    # 计算默认用户
    default_person = _get_default_person()
    print(f"      默认用户: {default_person}")

    # 按比例缩放分布
    base_total = sum(QUESTION_DISTRIBUTION.values())
    scale_factor = target_total / base_total
    scaled_distribution = {
        k: max(1, int(v * scale_factor))
        for k, v in QUESTION_DISTRIBUTION.items()
    }
    # 调整差额到 my_styles -> style_overview
    diff = target_total - sum(scaled_distribution.values())
    if diff > 0:
        scaled_distribution["my_styles -> style_overview"] += diff

    print(f"\n[3/5] 生成问题（目标 {target_total} 条，基数 {base_total}，缩放因子 {scale_factor:.2f}）...")
    all_questions = []

    # 收集查询链配置
    chain_configs = []
    for primary_type, secondary_rules in CALL_CHAIN_RULES.items():
        for secondary_type in secondary_rules.keys():
            chain_key = f"{primary_type} -> {secondary_type}"
            target = scaled_distribution.get(chain_key, 0)
            if target > 0:
                chain_configs.append((primary_type, secondary_type, target))

    # 收集单轮接口配置
    single_configs = []
    for interface_type in SINGLE_INTERFACE_TYPES:
        target = scaled_distribution.get(interface_type, 0)
        if target > 0:
            single_configs.append((interface_type, target))

    total_target = sum(t for _, _, t in chain_configs) + sum(t for _, t in single_configs)
    print(f"      查询链配置: {len(chain_configs)} 种")
    print(f"      单轮接口: {len(single_configs)} 种")
    print(f"      缩放后目标: {total_target} 条")

    # 生成查询链问题
    for primary_type, secondary_type, target in chain_configs:
        print(f"\n  查询链: {primary_type} -> {secondary_type} (目标 {target} 条)")
        generated = 0
        attempts = 0
        max_attempts = target * 3

        while generated < target and attempts < max_attempts:
            attempts += 1

            # 采样真实数据
            sample = sample_chain_data(primary_type, secondary_type, executor, default_person)
            if not sample:
                continue

            # 生成问题
            count = min(questions_per_batch, target - generated)
            questions = generate_questions_for_chain(
                primary_type, secondary_type, sample, deepseek_client, count
            )

            # 后处理：自动填充标准格式的 requires_interface
            for q in questions:
                q["requires_interface"] = _build_chain_interfaces(primary_type, secondary_type, default_person)
                q["chain_type"] = f"{primary_type} -> {secondary_type}"

            # 筛选
            filtered = filter_questions(questions)
            all_questions.extend(filtered)
            generated += len(filtered)

            _print_progress_bar(generated, target, prefix=f"  {primary_type}->{secondary_type}")

        _print_progress_bar(target, target, prefix=f"  {primary_type}->{secondary_type}", suffix="完成")

    # 生成单轮问题
    for interface_type, target in single_configs:
        print(f"\n  单轮: {interface_type} (目标 {target} 条)")
        generated = 0
        attempts = 0
        max_attempts = target * 3

        while generated < target and attempts < max_attempts:
            attempts += 1

            # 采样真实数据
            sample = sample_single_data(interface_type, executor, default_person)
            if not sample:
                continue

            # 生成问题
            count = min(questions_per_batch, target - generated)
            questions = generate_questions_for_single(
                interface_type, sample, deepseek_client, count
            )

            # 后处理：自动填充标准格式的 requires_interface
            for q in questions:
                q["requires_interface"] = [_build_single_call(interface_type, default_person)]
                q["interface_type"] = interface_type

            # 筛选
            filtered = filter_questions(questions)
            all_questions.extend(filtered)
            generated += len(filtered)

            _print_progress_bar(generated, target, prefix=f"  {interface_type}")

        _print_progress_bar(target, target, prefix=f"  {interface_type}", suffix="完成")

    print(f"\n[4/5] 验证问题可执行性 ({len(all_questions)} 条)...")
    validated_count = 0
    failed_count = 0

    for i, q in enumerate(all_questions):
        interfaces = q.get("requires_interface", [])
        if not interfaces:
            q["validation"] = {
                "status": "failed",
                "executed_at": datetime.now().isoformat(),
                "result": "requires_interface 为空",
            }
            failed_count += 1
            continue

        try:
            result = executor.execute(interfaces)

            if result.get("status") == "success":
                has_data = False
                for key, value in result.items():
                    if key.startswith("_"):
                        continue
                    if value and (not isinstance(value, list) or len(value) > 0):
                        has_data = True
                        break

                if has_data:
                    q["validation"] = {
                        "status": "success",
                        "executed_at": datetime.now().isoformat(),
                        "result": "执行成功返回有数据",
                    }
                    validated_count += 1
                else:
                    q["validation"] = {
                        "status": "failed",
                        "executed_at": datetime.now().isoformat(),
                        "result": "执行成功但返回为空",
                    }
                    failed_count += 1
            else:
                q["validation"] = {
                    "status": "failed",
                    "executed_at": datetime.now().isoformat(),
                    "result": result.get("error", "未知错误"),
                }
                failed_count += 1
        except Exception as e:
            q["validation"] = {
                "status": "failed",
                "executed_at": datetime.now().isoformat(),
                "result": f"执行异常: {str(e)}",
            }
            failed_count += 1

        _print_progress_bar(i + 1, len(all_questions), prefix="  验证", suffix=f"成功:{validated_count} 失败:{failed_count}")

    _print_progress_bar(len(all_questions), len(all_questions), prefix="  验证", suffix="完成")

    print(f"\n[5/5] 保存结果...")
    print(f"      总生成: {len(all_questions)} 条")
    print(f"      验证成功: {validated_count} 条")
    print(f"      验证失败: {failed_count} 条")

    # 统计
    chain_count = sum(1 for q in all_questions if len(q.get("requires_interface", [])) >= 2)
    single_count = len(all_questions) - chain_count

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total": len(all_questions),
            "validated_success": validated_count,
            "validated_failed": failed_count,
            "chain_count": chain_count,
            "single_count": single_count,
            "interface_distribution": _compute_interface_distribution(all_questions),
            "questions": all_questions,
        }, f, ensure_ascii=False, indent=2)

    print(f"      已保存到: {output_path}")
    return all_questions


def main():
    parser = argparse.ArgumentParser(description="Extract V2 training questions based on CALL_CHAIN_RULES")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Output JSON path")
    parser.add_argument("--target", type=int, default=253, help="Target number of questions (default 253, scale up as needed)")
    parser.add_argument("--per-batch", type=int, default=3, help="Questions per DeepSeek call")
    args = parser.parse_args()

    extract_all_questions(
        output_path=args.output,
        target_total=args.target,
        questions_per_batch=args.per_batch,
    )


if __name__ == "__main__":
    main()
