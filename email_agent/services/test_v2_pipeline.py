#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端 V2 管道测试

从 test_record2.json 提取 DeepSeek 模拟的 function_calls，
忽略 top_k 等参数，真实调用 KG/RAG，进行上下文检测和截取。

使用:
    cd /Users/potato/Documents/indochine/emlData/source/messages_package
    python email_agent/services/test_v2_pipeline.py
"""

import json
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from email_agent.services.result_truncator import ResultTruncator
from email_agent.services.context_manager import ContextManager
from email_agent.services import kg_adapter


# 从 test_record2.json 提取的 function_calls（去重，忽略 top_k）
EXTRACTED_CALLS = [
    {"name": "kg_query", "params": {"type": "my_styles"}},
    {"name": "kg_query", "params": {"type": "style_summaries", "style_ids": ["AW25-KFWTS101", "AW25-KFWTT156", "INDOT23404", "SS25IACB201", "INDOB28113", "INDOT28119", "INDOT26215", "INDOT26908", "INDOB27696", "INDOT25139", "INDOT22861", "9046143", "9024097", "9037551", "8826445", "9113832", "9113726", "9170269", "9163621", "9061160"]}},
    {"name": "kg_query", "params": {"type": "style_summaries", "style_ids": ["9061160", "8826445", "9113832", "9113726", "9170269", "9163621", "9024097", "9037551", "9046143", "INDOT22861", "INDOT25139", "INDOB27696", "INDOT26908", "INDOT26215", "INDOT28119", "INDOB28113", "SS25IACB201", "INDOT23404", "AW25-KFWTT156", "AW25-KFWTS101"]}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "8826445"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9061160"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9113832"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9113726"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9170269"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9163621"}},
    {"name": "kg_query", "params": {"type": "style_overview", "style_id": "9024097"}},
]


def execute_function_call(fc: dict) -> dict:
    """执行单个 function_call，返回真实查询结果"""
    name = fc.get("name", "")
    params = fc.get("params", {})
    
    if name == "kg_query":
        return _execute_kg(params)
    elif name == "rag_query":
        return _execute_rag(params)
    else:
        return {"error": f"Unknown function: {name}"}


def _execute_kg(params: dict) -> dict:
    """执行 KG 查询"""
    qtype = params.get("type", "")
    
    if qtype == "my_styles":
        result = kg_adapter.query_person_styles_with_stats("Paula Cheng")
        styles = result.get("styles", [])
        EXTRACTED_CALLS[1]['params']['style_ids'] = styles
        return {
            "type": "my_styles",
            "styles": [{"style_id": s["style_id"], "latest_category": s.get("latest_category", ""), "event_count": s.get("event_count", 0)} for s in styles],
            "total": result.get("total_styles", 0),
        }
    
    elif qtype == "style_summaries":
        style_ids = params.get("style_ids", [])
        summaries = []
        for sid in style_ids:
            overview = kg_adapter.get_style_overview(sid)
            summaries.append({
                "style_id": sid,
                "latest_category": overview.get("latest_category", ""),
                "total_events": overview.get("total_events", 0),
                "total_delay_days": overview.get("total_delay_days", 0),
                "last_update": overview.get("last_update", ""),
            })
        return {"type": "style_summaries", "summaries": summaries, "total": len(style_ids)}
    
    elif qtype == "style_overview":
        sid = params.get("style_id", "")
        overview = kg_adapter.get_style_overview(sid)
        # 简化：只保留关键字段
        return {
            "type": "style_overview",
            "overview": {
                "style_id": overview.get("style_id", ""),
                "latest_category": overview.get("latest_category", ""),
                "total_events": overview.get("total_events", 0),
                "people_count": len(overview.get("people", [])),
                "timeline_count": len(overview.get("timeline", [])),
            }
        }
    
    else:
        return {"error": f"Unknown kg_query type: {qtype}"}


def _execute_rag(params: dict) -> dict:
    """执行 RAG 查询（当前测试数据中没有 RAG 调用）"""
    return {"error": "RAG not used in this test record"}


def run_pipeline(max_tokens: int = 10000, reserve_tokens: int = 1000):
    """
    运行端到端 V2 管道测试
    
    Args:
        max_tokens: 上下文总token上限（默认10000）
        reserve_tokens: 给 V2 输出预留的token数
    """
    print("=" * 70)
    print(f"V2 端到端管道测试 (max_tokens={max_tokens}, reserve={reserve_tokens})")
    print("=" * 70)
    
    cm = ContextManager(max_tokens=max_tokens, reserve_tokens=reserve_tokens)
    truncator = ResultTruncator()
    
    # 初始化消息
    messages = [
        {"role": "system", "content": "你是 V2 查询策略模型。根据用户问题和历史查询结果，判断信息是否满足用户需求。"},
        {"role": "user", "content": "[用户提问] 我这边面料阶段事件数在30个以上的款号有几个？"},
    ]
    
    total_original_items = 0
    total_truncated_items = 0
    truncation_count = 0
    
    for round_idx, fc in enumerate(EXTRACTED_CALLS):
        print(f"\n{'─' * 70}")
        print(f"Round {round_idx + 1}: {fc['name']} / {fc['params'].get('type', '')}")
        print(f"{'─' * 70}")
        
        # 1. 执行真实查询
        print(f"  [1] 执行查询...")
        raw_result = execute_function_call(fc)
        
        # 统计原始item数量
        original_count = 0
        if "styles" in raw_result:
            original_count = len(raw_result["styles"])
        elif "summaries" in raw_result:
            original_count = len(raw_result["summaries"])
        elif "overview" in raw_result:
            original_count = 1  # style_overview 返回单个对象
        
        total_original_items += original_count
        print(f"      原始结果: {original_count} items")
        
        # 2. 检查上下文
        print(f"  [2] 上下文检测...")
        content_str = json.dumps(raw_result, ensure_ascii=False)
        check = cm.check_content_overflow(messages, content_str)
        print(f"      {cm.get_status_summary(check)}")
        
        # 3. 判断是否需要截取
        if check.status in ("warning", "overflow"):
            print(f"  [3] 需要截取！")
            
            # 确定查询类型
            query_type = f"kg_query.{fc['params'].get('type', '')}"
            rule = truncator.RULES.get(query_type)
            item_estimate = rule.item_token_estimate if rule else 50
            
            # 计算允许的最大item数
            max_items = cm.calculate_max_items(item_estimate, check.remaining_tokens)
            print(f"      剩余空间允许: {max_items} items")
            
            # 执行截取
            result = truncator.truncate(raw_result, query_type, max_items=max(max_items, 1))
            feedback = cm.build_truncation_feedback(result)
            
            total_truncated_items += result.returned_count
            truncation_count += 1
            
            print(f"      截取: {result.returned_count}/{result.original_count} ({result.strategy})")
            print(f"      说明: {result.truncation_note}")
        else:
            print(f"  [3] 无需截取")
            feedback = "[工具返回] " + content_str
            total_truncated_items += original_count
        
        # 4. 添加到消息列表
        messages.append({"role": "user", "content": feedback})
        print(f"  [4] 反馈长度: {len(feedback)} 字符")
        print(f"      当前总消息数: {len(messages)}")
    
    # 最终统计
    print(f"\n{'=' * 70}")
    print("测试完成")
    print(f"{'=' * 70}")
    print(f"总轮次: {len(EXTRACTED_CALLS)}")
    print(f"原始总items: {total_original_items}")
    print(f"截断后总items: {total_truncated_items}")
    print(f"截断次数: {truncation_count}")
    print(f"截断率: {(1 - total_truncated_items / total_original_items) * 100:.1f}%" if total_original_items > 0 else "N/A")
    print(f"最终上下文: {cm.get_status_summary(cm.check_overflow(messages))}")


if __name__ == "__main__":
    run_pipeline(max_tokens=5000, reserve_tokens=500)
