"""
对话Agent主入口（真实模型模式）

流程：
  1. 用户输入 → V3 路由决策
  2. 根据决策分支：
     - direct_answer: 直接回答（V3 生成）
     - route_v1: 查询事件 → V1 生成报告
     - route_v2: V2 多轮查询 → 生成回答
  3. 保存完整 session_flow 到数据库
  4. SSE 流式输出最终回答

Session 流程记录：
  user → v3 → [v2 → tool → v2 → tool → ...] → [v1] → assistant
"""

import json
import os
from typing import AsyncGenerator, Optional, List, Dict, Any

from email_agent.agents.intent_router import route
from email_agent.agents.v1_orchestrator import orchestrate_v1_analysis
from email_agent.agents.v2_orchestrator import orchestrate_v2_query
from email_agent.services.vllm_client import call_v3

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_session_flow(
    user_message: str,
    v3_result: dict,
    model_outputs: List[Dict[str, str]],
    final_answer: str,
) -> List[Dict[str, str]]:
    """
    构建完整的 session_flow 用于保存到数据库
    
    Args:
        user_message: 用户原始输入
        v3_result: V3 路由决策结果
        model_outputs: 中间模型输出 [{"role": "v2", "content": "..."}, ...]
        final_answer: 最终 assistant 回答
    
    Returns:
        [
            {"role": "user", "content": "..."},
            {"role": "v3", "content": "..."},
            {"role": "v2", "content": "..."},
            {"role": "tool", "content": "..."},
            ...,
            {"role": "assistant", "content": "..."}
        ]
    """
    flow = [
        {"role": "user", "content": user_message},
        {"role": "v3", "content": json.dumps(v3_result, ensure_ascii=False)},
    ]
    
    for output in model_outputs:
        flow.append(output)
    
    flow.append({"role": "assistant", "content": final_answer})
    
    return flow


# ---------------------------------------------------------------------------
# 各分支处理函数
# ---------------------------------------------------------------------------

async def _handle_direct_answer(
    user_message: str,
    v3_result: dict,
) -> tuple[str, List[Dict[str, str]]]:
    """
    处理 direct_answer 分支
    
    V3 直接生成回答（如问候、超出范围提示等）
    
    Returns:
        (final_answer, model_outputs)
    """
    # V3 已经给出了 decision，但 direct_answer 时需要 V3 生成回答内容
    # 重新调用 V3，但要求生成回答而非决策
    # 或者使用 V3 的 thought/answer 字段
    
    # 简化：直接返回 V3 的 answer（如果有）或固定提示
    answer = v3_result.get("answer", "您好，我可以帮您查询款号进度、分析延期原因、翻译术语等。请直接输入您的问题。")
    
    model_outputs = []
    
    return answer, model_outputs


async def _handle_route_v1(
    user_message: str,
    v3_result: dict,
    style_id: str,
) -> tuple[str, List[Dict[str, str]]]:
    """
    处理 route_v1 分支
    
    1. 调用 v1_orchestrator 查询事件 + 调用 V1 生成报告
    2. 返回 Markdown 报告
    
    Returns:
        (final_answer, model_outputs)
    """
    model_outputs = []
    
    # 获取用户关注的事件类型（从 V3 输出）
    event_focus = v3_result.get("event_focus")
    
    try:
        # 调用 V1 Orchestrator：查询事件 + 分轮调用 V1 + 合并报告
        report = await orchestrate_v1_analysis(
            style_id=style_id,
            event_focus=event_focus,
        )
        model_outputs.append({"role": "v1", "content": report})  # 保存全量
    except Exception as e:
        report = f"抱歉，生成 {style_id} 的时间线报告时出现错误: {e}"
        model_outputs.append({"role": "v1", "content": f"ERROR: {e}"})
    
    return report, model_outputs


async def _handle_route_v2(
    user_message: str,
    v3_result: dict,
) -> tuple[str, List[Dict[str, str]], Optional[dict]]:
    """
    处理 route_v2 分支
    
    V2 多轮查询：调用 v2_orchestrator 执行多轮工具调用
    
    Returns:
        (final_answer, model_outputs, truncation_info)
        truncation_info: 截断信息（用于续查），无截断时为 None
    """
    try:
        answer, model_outputs, truncation_result = await orchestrate_v2_query(
            user_message=user_message,
        )
        
        # 如果有截断，构造 truncation_info 供上层保存
        truncation_info = None
        if truncation_result and truncation_result.remaining_data:
            truncation_info = {
                "query_type": truncation_result.query_type or truncation_result.strategy,
                "original_count": truncation_result.original_count,
                "returned_count": truncation_result.returned_count,
                "omitted_count": len(truncation_result.omitted_data) if truncation_result.omitted_data else 0,
                "remaining_data": truncation_result.remaining_data,
                "conversation": truncation_result.conversation,
            }
        
        return answer, model_outputs, truncation_info
        
    except Exception as e:
        answer = f"【V2 查询引擎】查询过程中出现错误: {e}"
        model_outputs = [
            {"role": "v2", "content": f"{{\"thought\": \"查询失败: {e}\", \"satisfied\": false, \"function_calls\": []}}"},
        ]
        return answer, model_outputs, None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def _handle_continuation(
    user_message: str,
    session_id: Optional[str] = None,
) -> tuple[str, List[Dict[str, str]], Optional[dict]]:
    """
    处理续查请求
    
    续查不调用模型，直接从 OmittedData 中读取剩余数据并截取
    
    Returns:
        (final_answer, model_outputs, truncation_info)
    """
    # 续查逻辑由 chat.py 的 continue_chat 端点处理
    # 这里返回一个标记，让 chat.py 知道这是续查请求
    return (
        "__CONTINUATION__",  # 特殊标记
        [{"role": "system", "content": "continuation_request"}],
        None,
    )


async def process_message(
    text: str,
    session_style_id: Optional[str] = None,
    mode: str = "detailed"
) -> AsyncGenerator[dict, None]:
    """
    处理用户消息，返回 SSE 流式事件
    
    流程：
      1. V3 路由决策
      2. 根据决策调用 V1/V2/续查/直接回答
      3. 保存 session_flow
      4. SSE 输出最终回答
    
    Yields:
        {"event": "delta", "data": {"content": "..."}}
        {"event": "done", "data": {"content": "...", "sources": [], "mode": "..."}}
    """
    assistant_content = ""
    session_flow = []
    
    try:
        # Step 1: V3 路由决策
        yield {"event": "thought", "data": {"thought": "正在分析查询意图..."}}
        v3_result = route(text)
        decision = v3_result["decision"]
        style_id = v3_result.get("style_id") or session_style_id
        
        # Step 2: 根据决策分支处理
        truncation_info = None
        model_outputs = []
        
        if decision == "direct_answer":
            yield {"event": "thought", "data": {"thought": "直接生成回答..."}}
            assistant_content, model_outputs = await _handle_direct_answer(text, v3_result)
            
        elif decision == "route_v1":
            if not style_id:
                assistant_content = "抱歉，未检测到款号，请提供具体款号。"
            else:
                yield {"event": "thought", "data": {"thought": "正在生成时间线报告..."}}
                assistant_content, model_outputs = await _handle_route_v1(text, v3_result, style_id)
                
        elif decision == "route_v2":
            yield {"event": "thought", "data": {"thought": "正在查询数据..."}}
            assistant_content, model_outputs, truncation_info = await _handle_route_v2(text, v3_result)
            if truncation_info:
                yield {"event": "thought", "data": {"thought": f"数据量较大，已截取 {truncation_info['returned_count']}/{truncation_info['original_count']} 条，生成回答中..."}}
            else:
                yield {"event": "thought", "data": {"thought": "生成回答中..."}}
        
        elif decision == "continuation":
            yield {"event": "thought", "data": {"thought": "正在获取剩余数据..."}}
            # 续查请求 - 返回特殊标记，由 chat.py 处理
            assistant_content, model_outputs, _ = await _handle_continuation(text)
            
        else:
            assistant_content = f"未知决策: {decision}"
        
        # 构建 session_flow
        session_flow = _build_session_flow(text, v3_result, model_outputs, assistant_content)
        print(session_flow)
        
    except Exception as e:
        assistant_content = f"系统错误: {e}"
        session_flow = [
            {"role": "user", "content": text},
            {"role": "assistant", "content": assistant_content},
        ]
    
    # Step 3: SSE 流式输出
    yield {"event": "delta", "data": {"content": assistant_content}}
    
    # 完成事件
    done_data = {
        "content": assistant_content,
        "sources": [],
        "mode": mode,
        "session_flow": session_flow,  # 供外部保存到数据库
    }
    
    # 如果有截断信息，包含在 done 事件中供 chat.py 保存到 OmittedData
    if truncation_info:
        done_data["truncation_info"] = truncation_info
    
    yield {
        "event": "done",
        "data": done_data,
    }


# ---------------------------------------------------------------------------
# 兼容接口
# ---------------------------------------------------------------------------

def get_mock_session_flow(text: str) -> List[Dict[str, str]]:
    """
    兼容旧接口，返回空列表（真实模式下不再使用 mock 数据）
    """
    return []
