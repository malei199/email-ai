"""
vLLM 本地模型服务客户端
封装 OpenAI 兼容 API 调用，统一处理 system prompt 和模型参数
"""

import json
from typing import Optional, List
import openai

from email_agent.config import (
    VLLM_BASE_URL,
    VLLM_API_KEY,
    VLLM_MODELS,
    SYSTEM_PROMPTS,
    MODEL_DEFAULTS,
)

# ---------------------------------------------------------------------------
# 全局客户端（复用连接）
# ---------------------------------------------------------------------------

_client: Optional[openai.OpenAI] = None


def get_client() -> openai.OpenAI:
    """获取或创建 OpenAI 客户端"""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            base_url=VLLM_BASE_URL,
            api_key=VLLM_API_KEY,
        )
    return _client


# ---------------------------------------------------------------------------
# 核心调用函数
# ---------------------------------------------------------------------------

def call_model(
    model: str,
    user_message: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
) -> str:
    """
    调用 vLLM 本地模型服务（单条 user message 模式）

    Args:
        model: 模型标识 (v3/v2/v1)
        user_message: 用户输入文本
        temperature: 采样温度，默认从 MODEL_DEFAULTS 读取
        max_tokens: 最大生成 token 数，默认从 MODEL_DEFAULTS 读取
        response_format: 强制输出格式，如 {"type": "json_object"}

    Returns:
        模型生成的文本内容

    Raises:
        ValueError: 模型标识无效
        openai.APIError: API 调用失败
    """
    if model not in VLLM_MODELS:
        raise ValueError(f"未知模型: {model}，可用: {list(VLLM_MODELS.keys())}")

    # 获取 system prompt
    system_prompt = SYSTEM_PROMPTS.get(model, "")

    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    return _call_model_with_messages(model, messages, temperature, max_tokens, response_format)


def _call_model_with_messages(
    model: str,
    messages: List[dict],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[dict] = None,
) -> str:
    """
    调用 vLLM 本地模型服务（传入完整 messages 列表）

    Args:
        model: 模型标识 (v3/v2/v1)
        messages: 完整消息列表（已包含 system prompt）
        temperature: 采样温度
        max_tokens: 最大生成 token 数
        response_format: 强制输出格式

    Returns:
        模型生成的文本内容
    """
    if model not in VLLM_MODELS:
        raise ValueError(f"未知模型: {model}，可用: {list(VLLM_MODELS.keys())}")

    # 获取默认参数
    defaults = MODEL_DEFAULTS.get(model, {})
    temp = temperature if temperature is not None else defaults.get("temperature", 0.3)
    max_tok = max_tokens if max_tokens is not None else defaults.get("max_tokens", 500)

    # 调用 vLLM
    client = get_client()
    kwargs = {
        "model": VLLM_MODELS[model],
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tok,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = client.chat.completions.create(**kwargs)

    return response.choices[0].message.content


def call_model_json(
    model: str,
    user_message: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    """
    调用模型并解析 JSON 输出

    Args:
        model: 模型标识 (v3/v2/v1)
        user_message: 用户输入文本
        temperature: 采样温度
        max_tokens: 最大生成 token 数

    Returns:
        解析后的 JSON 字典

    Raises:
        json.JSONDecodeError: 输出不是有效 JSON
    """
    content = call_model(
        model=model,
        user_message=user_message,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return json.loads(content)


# ---------------------------------------------------------------------------
# 便捷函数（按模型）
# ---------------------------------------------------------------------------

def call_v3(user_message: str) -> dict:
    """调用 V3 调度器，返回 JSON 决策"""
    # max_tokens 从 MODEL_DEFAULTS 读取（v3: 300）
    return call_model_json(
        model="v3",
        user_message=user_message,
        temperature=0.1,
    )



def call_v2_messages(messages: List[dict]) -> dict:
    """
    调用 V2 查询引擎，传入完整 messages 列表（与训练数据格式一致）

    Args:
        messages: 完整消息列表，格式与训练数据一致：
            [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "[用户提问] ..."},
                {"role": "assistant", "content": '{"thought": ..., "satisfied": ...}'},
                {"role": "user", "content": "[工具返回] ..."},
                ...
            ]

    Returns:
        解析后的 JSON 字典

    Raises:
        json.JSONDecodeError: 输出不是有效 JSON（通常是被 max_tokens 截断）
                              异常对象的 .doc 属性包含原始截断字符串
    """
    content = _call_model_with_messages(
        model="v2",
        messages=messages,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # 将原始内容附加到异常，供上层恢复
        e.doc = content  # type: ignore
        raise


def call_v1(user_message: str) -> str:
    """调用 V1 时间线生成，返回 Markdown 报告"""
    # max_tokens 从 MODEL_DEFAULTS 读取（v1: 3000）
    return call_model(
        model="v1",
        user_message=user_message,
        temperature=0.3,
    )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

def health_check() -> dict:
    """检查 vLLM 服务状态，返回已加载模型列表"""
    try:
        client = get_client()
        models = client.models.list()
        return {
            "status": "ok",
            "models": [m.id for m in models.data],
            "base_url": VLLM_BASE_URL,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "base_url": VLLM_BASE_URL,
        }
