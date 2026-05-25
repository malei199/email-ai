"""
V2 多轮查询编排器

职责：
1. 接收用户问题，调用 V2 模型生成 function_calls
2. 使用 V2FunctionExecutor 执行查询
3. 使用 ContextManager 检测上下文长度
4. 使用 ResultTruncator 截取过长结果
5. 循环直到 satisfied=true 或达到最大轮次
6. 生成最终回答

流程：
  user → V2 → function_calls → Executor → Result → [truncate] → V2 → ... → generate_answer

对话格式（与训练数据 sft_v2_multiround.jsonl 一致）：
  [
    {"role": "system", "content": "你是 V2 查询策略模型..."},
    {"role": "user", "content": "[用户提问] 我的款号有哪些"},
    {"role": "assistant", "content": '{"thought": "...", "satisfied": false, "function_calls": [...]}'},
    {"role": "user", "content": "[工具返回] {status: success, ...}"},
    {"role": "assistant", "content": '{"thought": "...", "satisfied": true, "function_calls": [{"name": "generate_answer", ...}]}'},
  ]
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple

from email_agent.services.vllm_client import call_v2_messages
from email_agent.services.v2_executor import V2FunctionExecutor
from email_agent.services.context_manager import ContextManager
from email_agent.services.result_truncator import ResultTruncator, TruncationResult
from email_agent.services.answer_generator import generate_answer
from email_agent.config import V2_SYSTEM_PROMPT


MAX_V2_ROUNDS = 10

# 非法控制字符（JSON 标准不允许，vLLM 解析器会报错）
# 保留 \n (0x0a), \r (0x0d), \t (0x09)，清理其他所有控制字符 + 扩展 ASCII 控制字符
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def _clean_content(text: str) -> str:
    """清理 content 中的非法控制字符"""
    return _CONTROL_CHARS.sub("", text)


def _clean_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """清理 messages 列表中所有 content 的非法控制字符"""
    cleaned = []
    for m in messages:
        content = m.get("content", "")
        cleaned.append({**m, "content": _clean_content(content)})
    return cleaned


def _recover_truncated_json(truncated_str: str) -> Optional[dict]:
    """
    尝试从被 vLLM max_tokens 截断的 JSON 字符串中恢复有效数据
    
    策略：
      1. 尝试补全截断的字符串（加引号）
      2. 尝试提取已完整的字段
      3. 如果 thought 已完整但 function_calls 截断，构造 generate_answer 兜底
    """
    if not truncated_str or not truncated_str.strip():
        return None
    
    s = truncated_str.strip()
    
    # 策略1: 尝试补全截断的字符串（最常见：字符串未闭合）
    # 找到最后一个未闭合的引号，补全它并关闭 JSON
    # 简单方法：逐层尝试关闭 JSON
    closers = ["", "\"", "\"}", "\"}]", "\"}]}", "\"}}"]
    for closer in closers:
        try:
            fixed = s + closer
            # 如果最后一个字符是反斜杠，需要额外处理
            if fixed.endswith("\\"):
                fixed = fixed[:-1] + "\\\\" + closer
            return json.loads(fixed)
        except json.JSONDecodeError:
            continue
    
    # 策略2: 尝试提取已完整的字段（用正则）
    try:
        thought_match = re.search(r'"thought"\s*:\s*"([^"]*)"', s)
        thought = thought_match.group(1) if thought_match else "输出被截断"
        
        satisfied_match = re.search(r'"satisfied"\s*:\s*(true|false)', s)
        satisfied = satisfied_match.group(1) == "true" if satisfied_match else True
        
        # 如果 satisfied=true，尝试提取 generate_answer
        if satisfied:
            gen_match = re.search(r'"name"\s*:\s*"generate_answer"', s)
            if gen_match:
                # 尝试提取 template 和 data
                template_match = re.search(r'"template"\s*:\s*"([^"]*)"', s)
                template = template_match.group(1) if template_match else "not_found"
                
                # data 可能截断，尝试提取 message 字段
                # 注意：截断时字符串可能未闭合，用非贪婪匹配到字符串末尾或引号
                msg_match = re.search(r'"message"\s*:\s*"([^"]*)', s)
                msg = msg_match.group(1) if msg_match else ""
                # 如果 message 值未闭合（后面没有引号），去掉末尾可能截断的部分
                if msg and not s[s.find(msg) + len(msg):].startswith('"'):
                    # 字符串被截断，简单处理：保留已有内容
                    pass
                data = {"message": msg} if msg else {}
                
                return {
                    "thought": thought,
                    "satisfied": True,
                    "function_calls": [{
                        "name": "generate_answer",
                        "params": {"template": template, "data": data}
                    }]
                }
        
        # 兜底：返回截断的 thought，satisfied=false，无 function_calls
        return {
            "thought": thought + "（输出被截断，请重试）",
            "satisfied": False,
            "function_calls": []
        }
    except Exception:
        pass
    
    return None


async def orchestrate_v2_query(
    user_message: str,
    session_context: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, List[Dict[str, str]], Optional[TruncationResult]]:
    """
    编排 V2 多轮查询

    Args:
        user_message: 用户原始问题
        session_context: 当前会话历史消息（用于上下文管理）

    Returns:
        (final_answer, model_outputs, last_truncation_result)
        - final_answer: Markdown 格式最终回答
        - model_outputs: 中间模型输出列表
        - last_truncation_result: 最后一次截断结果（如有，用于续查）
    """
    executor = V2FunctionExecutor()
    cm = ContextManager(max_tokens=14000, reserve_tokens=1000)
    truncator = ResultTruncator()


    # 初始化消息列表（与训练数据格式一致）
    # system prompt + 历史消息 + 当前用户问题
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": V2_SYSTEM_PROMPT},
    ]
    
    if session_context:
        messages.extend(session_context)
    
    # 添加当前用户问题
    messages.append({"role": "user", "content": f"[用户提问] {user_message}"})

    model_outputs = []
    last_truncation_result: Optional[TruncationResult] = None

    for round_num in range(MAX_V2_ROUNDS):
        # 1. 调用 V2 模型（传入完整 messages 列表，与训练数据格式一致）
        # 先清理非法控制字符，防止 vLLM 解析报错
        clean_messages = _clean_messages(messages)
        try:
            v2_output = call_v2_messages(clean_messages)
        except json.JSONDecodeError as e:
            # JSON 解析失败（通常是 vLLM max_tokens 截断导致）
            print(f"[V2 JSON ERROR] {e}")
            # 尝试从截断的响应中恢复
            v2_output = _recover_truncated_json(e.doc if hasattr(e, 'doc') else "")
            if not v2_output:
                # 无法恢复，强制生成回答
                answer = _build_answer_from_context(messages, {"thought": "V2 输出截断，强制生成回答"})
                return answer, model_outputs, last_truncation_result
        # 截断过长的 thought，防止 JSON 序列化后超限
        thought = v2_output.get("thought", "")
        if len(thought) > 3000:
            v2_output["thought"] = thought[:3000] + "..."
        
        v2_content = json.dumps(v2_output, ensure_ascii=False)
        model_outputs.append({"role": "v2", "content": v2_content})

        # 2. 检查是否满足
        if v2_output.get("satisfied", False):
            # 生成最终回答
            function_calls = v2_output.get("function_calls", [])
            if function_calls and function_calls[0].get("name") == "generate_answer":
                answer = _handle_generate_answer(function_calls[0])
                print(f"[GENERATE_ANSWER] call: {json.dumps(function_calls[0], ensure_ascii=False)[:500]}")
            else:
                answer = _build_answer_from_context(messages, v2_output)
            return answer, model_outputs, last_truncation_result

        # 3. 执行 function_calls
        function_calls = v2_output.get("function_calls", [])
        if not function_calls:
            # V2 没有输出 function_calls，降级处理
            answer = "抱歉，无法理解您的查询意图，请尝试提供更具体的信息（如款号、人员姓名等）。"
            return answer, model_outputs, last_truncation_result

        try:
            raw_result = executor.execute(function_calls)
        except Exception as e:
            model_outputs.append({"role": "tool", "content": f"ERROR: {e}"})
            answer = f"查询执行出错: {e}"
            return answer, model_outputs, last_truncation_result

        # 4. 上下文检测 + 截取
        result_json = json.dumps(raw_result, ensure_ascii=False)
        check = cm.check_content_overflow(messages, result_json)

        if check.status in ("warning", "overflow"):
            print("overflow -- " * 20)
            # 需要截取
            query_type = _infer_query_type_from_result(raw_result)
            rule = truncator.RULES.get(query_type)
            item_estimate = rule.item_token_estimate if rule else 50
            max_items = cm.calculate_max_items(item_estimate, check.remaining_tokens)

            conversation = {
                "user_query": user_message,
                "v2_thought": v2_output.get("thought", ""),
                "function_calls": function_calls,
                "round": round_num + 1,
            }

            # 解包嵌套结构：raw_result = {'status': 'success', 'call_type': {'events': [...]}, '_errors': None}
            # 提取内层数据用于截取
            data_keys = [k for k in raw_result.keys() if not k.startswith("_") and k != "status"]
            if data_keys and isinstance(raw_result[data_keys[0]], dict):
                call_type_key = data_keys[0]
                inner_data = raw_result[call_type_key]  # {'events': [...]}
                is_nested = True
            else:
                inner_data = raw_result
                call_type_key = None
                is_nested = False
            
            truncation_result = truncator.truncate(
                raw_result=inner_data,
                query_type=query_type,
                max_items=max(max_items, 1),
                conversation=conversation,
            )
            
            # 保存 query_type 到 truncation_result，供续查使用
            from dataclasses import replace
            truncation_result = replace(truncation_result, query_type=query_type)
            
            # 如果原始数据是嵌套结构，把截取后的数据包回去
            if is_nested:
                wrapped_data = {
                    k: v for k, v in raw_result.items()
                }
                wrapped_data[call_type_key] = truncation_result.truncated_data
                # 更新 truncation_result 的 truncated_data 为包回后的结构
                truncation_result = replace(truncation_result, truncated_data=wrapped_data)
                # 构造 remaining_data：把 truncated_data 中的列表替换成 omitted_data
                remaining_data = dict(raw_result)
                remaining_inner = dict(remaining_data[call_type_key])
                # 找到列表字段并替换
                for key, value in remaining_inner.items():
                    if isinstance(value, list):
                        remaining_inner[key] = truncation_result.omitted_data
                        break
                remaining_data[call_type_key] = remaining_inner
            else:
                # 扁平结构
                remaining_data = dict(raw_result)
                for key, value in remaining_data.items():
                    if isinstance(value, list):
                        remaining_data[key] = truncation_result.omitted_data
                        break
            
            # 保存 remaining_data 到 truncation_result，供续查使用
            truncation_result = replace(truncation_result, remaining_data=remaining_data)
            
            feedback = cm.build_truncation_feedback(truncation_result)
            last_truncation_result = truncation_result

            model_outputs.append({"role": "tool", "content": feedback})
            # 将 assistant 决策和工具返回加入 messages（与训练数据格式一致）
            messages.append({"role": "assistant", "content": v2_content})
            messages.append({"role": "user", "content": feedback})
        else:
            # 无需截取
            feedback = f"[工具返回] {result_json}"
            model_outputs.append({"role": "tool", "content": feedback})
            # 将 assistant 决策和工具返回加入 messages
            messages.append({"role": "assistant", "content": v2_content})
            messages.append({"role": "user", "content": feedback})

    # 达到最大轮次，强制生成回答
    answer = _build_answer_from_context(messages, {"thought": "达到最大轮次，强制生成回答"})
    return answer, model_outputs, last_truncation_result


async def continue_v2_query(
    remaining_data: dict,
    query_type: str,
) -> str:
    """
    续查：直接返回剩余的所有数据，不过模型，不截取
    
    Args:
        remaining_data: 从 OmittedData 读取的剩余数据（完整的 raw_result 结构）
        query_type: 查询类型，如 "rag_query.semantic_search"
    
    Returns:
        生成的回答字符串
    """
    # 解包嵌套结构，提取内层数据
    data_keys = [k for k in remaining_data.keys() if not k.startswith("_") and k != "status"]
    if data_keys and isinstance(remaining_data[data_keys[0]], dict):
        inner_data = remaining_data[data_keys[0]]
    else:
        inner_data = remaining_data
    
    # 直接生成回答
    template = _infer_template_from_data(inner_data, query_type)
    return generate_answer(template, inner_data)


def _infer_query_type(function_calls: List[dict]) -> str:
    """从 function_calls 推断查询类型（已废弃，请使用 _infer_query_type_from_result）"""
    if not function_calls:
        return "unknown"

    first_call = function_calls[0]
    name = first_call.get("name", "")
    params = first_call.get("params", {})
    qtype = params.get("type", "")

    if name == "kg_query":
        return f"kg_query.{qtype}"
    elif name == "rag_query":
        return f"rag_query.{qtype}"
    return "unknown"


def _infer_query_type_from_result(raw_result: dict) -> str:
    """
    从工具返回结果推断 query_type，与 build_v2_dataset.py 的截取逻辑保持一致。
    
    处理两种结构：
      1. 单轮结果: {"status": "success", "call_type": {"main_key": [...]}}
      2. 查询链结果: {"status": "success", "call_types": [...], "_meta": {...}}
    """
    if not raw_result or not isinstance(raw_result, dict):
        return "unknown"
    
    # 跳过元信息字段
    data_keys = [k for k in raw_result.keys() if not k.startswith("_") and k != "status"]
    if not data_keys:
        return "unknown"
    
    # 判断是否为查询链结果（有 _meta 且只有一个数据 key）
    has_meta = "_meta" in raw_result
    is_chain = has_meta and len(data_keys) == 1
    
    if is_chain:
        # 查询链结果：固定使用 style_summaries 规则处理二级列表
        return "kg_query.style_summaries"
    
    # 单轮结果：取 call_type_key，再解包取内层 main_key
    call_type_key = data_keys[0]
    inner_data = raw_result.get(call_type_key)
    
    # 如果内层是 dict，取内层的第一个数据 key 作为 main_key
    if isinstance(inner_data, dict):
        inner_keys = [k for k in inner_data.keys() if not k.startswith("_")]
        main_key = inner_keys[0] if inner_keys else call_type_key
    # 如果内层是 list，直接用 call_type_key（如查询链的复数形式）
    elif isinstance(inner_data, list):
        main_key = call_type_key
    else:
        main_key = call_type_key
    
    # 按 main_key 映射到 RULES 中的 query_type
    if main_key == "events":
        return "rag_query.semantic_search"
    elif main_key == "styles":
        return "kg_query.my_styles"
    elif main_key == "summaries":
        return "kg_query.style_summaries"
    elif main_key == "collaborators":
        return "kg_query.collaborators"
    elif main_key == "factories":
        return "kg_query.factory_delays"
    elif main_key == "translations":
        return "rag_query.term_translation"
    else:
        return "unknown"


def _handle_generate_answer(call: dict) -> str:
    """处理 generate_answer function_call"""
    params = call.get("params", {})
    template = params.get("template", "not_found")
    data = params.get("data", {})

    # 使用 answer_generator 生成回答
    return generate_answer(template, data)


def _build_answer_from_context(messages: List[Dict[str, str]], v2_output: dict) -> str:
    """
    从上下文构建降级回答
    
    场景：
      1. V2 输出 satisfied=true 但没有 generate_answer → 从最后工具返回提取数据
      2. 达到最大轮次强制兜底 → 同上
      3. V2 JSON 截断恢复失败 → 提取已有数据生成简化回答
    
    策略：
      - 从 messages 中找到最后一条 [工具返回] 内容
      - 解析其中的 JSON 数据
      - 根据数据内容推断 template，调用 generate_answer 渲染
      - 如果无法解析，返回通用降级回答
    """
    # 1. 从 messages 中提取最后一次工具返回的数据
    last_tool_data = None
    last_query_type = "unknown"
    
    for msg in reversed(messages):
        content = msg.get("content", "")
        if content.startswith("[工具返回]"):
            # 提取 JSON 部分（[工具返回] 后面可能是 JSON 或带警告文本）
            json_str = content.replace("[工具返回]", "").strip()
            # 去掉可能的 [上下文警告] 后缀
            if "\n[上下文警告]" in json_str:
                json_str = json_str.split("\n[上下文警告]")[0]
            try:
                last_tool_data = json.loads(json_str)
            except json.JSONDecodeError:
                continue
            
            # 尝试推断查询类型（从前面最近的 assistant 消息）
            last_query_type = _infer_query_type_from_messages(messages, msg)
            break
    
    # 2. 如果有数据，推断 template 并渲染
    if last_tool_data:
        template = _infer_template_from_data(last_tool_data, last_query_type)
        try:
            return generate_answer(template, last_tool_data)
        except Exception as e:
            print(f"[BUILD_ANSWER_ERROR] generate_answer failed: {e}")
            # 降级：直接 JSON 输出
            return f"【查询结果】\n\n```json\n{json.dumps(last_tool_data, ensure_ascii=False, indent=2)}\n```"
    
    # 3. 没有任何工具数据 → 从 v2_output 的 thought 生成通用回答
    thought = v2_output.get("thought", "")
    if thought and thought != "达到最大轮次，强制生成回答":
        return f"{thought}\n\n（查询结果较长，如需详细数据请提供更具体的查询条件）"
    
    # 4. 完全兜底
    return "根据查询结果，已为您整理相关信息。如需更详细的分析，请提供具体款号。"


def _infer_query_type_from_messages(
    messages: List[Dict[str, str]], 
    tool_msg: Dict[str, str]
) -> str:
    """从工具消息前面的 assistant 消息推断查询类型"""
    # 找到 tool_msg 在 messages 中的位置
    try:
        idx = messages.index(tool_msg)
    except ValueError:
        return "unknown"
    
    # 向前查找最近的 assistant 消息（V2 输出）
    for i in range(idx - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            try:
                v2_out = json.loads(messages[i].get("content", ""))
                fcs = v2_out.get("function_calls", [])
                return _infer_query_type(fcs)
            except (json.JSONDecodeError, Exception):
                continue
    
    return "unknown"


def _infer_template_from_data(data: dict, query_type: str) -> str:
    """从数据结构推断最合适的模板（映射到 answer_generator.TEMPLATE_MAP 中存在的模板）"""
    # 有 message 字段 → 透传型
    if "message" in data:
        return "message"
    
    # 根据 query_type 推断（映射到 TEMPLATE_MAP 中实际存在的模板名）
    if query_type == "kg_query.my_styles":
        return "style_list"
    elif query_type == "kg_query.person_styles":
        return "style_list"
    elif query_type == "kg_query.factory_styles":
        return "factory_styles_timeline"
    elif query_type == "kg_query.style_summaries":
        return "style_list"  # summaries 数据结构类似 styles
    elif query_type == "kg_query.timeline":
        return "style_timeline"
    elif query_type == "kg_query.collaborators":
        return "collaborators_list"
    elif query_type == "kg_query.factory_delays":
        return "factory_delay_ranking"
    elif query_type == "rag_query.semantic_search":
        return "style_list"  # semantic_search 返回 events，用 style_list 兜底
    elif query_type == "rag_query.term_translation":
        return "term_translation"
    
    # 根据数据结构推断
    if "styles" in data or "style_ids" in data:
        return "style_list"
    elif "events" in data:
        return "style_timeline"
    elif "summaries" in data:
        return "style_list"
    elif "collaborators" in data:
        return "collaborators_list"
    elif "factories" in data:
        return "factory_delay_ranking"
    elif "translations" in data:
        return "term_translation"
    elif "term" in data:
        return "term_translation"
    
    return "not_found"
