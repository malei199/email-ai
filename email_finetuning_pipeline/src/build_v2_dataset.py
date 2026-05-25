#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build V2 multi-round query strategy fine-tuning dataset (v2 format).

V2 训练数据生成脚本（新版）

流程：
  1. 加载 v2_questions.json（已验证通过的问题）
  2. 过滤掉 validation.status != "success" 的问题
  3. 对每个问题，用 DeepSeek 模拟 V2 多轮判断（参考 requires_interface + reasoning）
  4. 用 V2FunctionExecutor 执行查询（支持查询链 + result 字段过滤）
  5. 组装成 ShareGPT 格式（SFT）和 DPO 格式

输出：
  - email_finetuning_pipeline/datasets/{train,val,test}/sft_v2_multiround.jsonl
  - email_finetuning_pipeline/datasets/{train,val,test}/dpo_v2_multiround.jsonl
  - email_finetuning_pipeline/datasets/v2_stats.json

使用：
    python build_v2_dataset.py
    python build_v2_dataset.py --questions datasets/v2_questions.json --target 500
"""

import os
import sys
import json
import argparse
import random
import time
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 复用 V1 的 DeepSeek client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_v1_timeline_dataset import (
    get_deepseek_client,
    DEEPSEEK_MODEL,
    MAX_RETRIES,
    RETRY_DELAY,
    REQUEST_TIMEOUT,
)

# 导入 V2FunctionExecutor
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
from email_agent.services.v2_executor import V2FunctionExecutor
from email_agent.services.result_truncator import ResultTruncator
from email_agent.services.context_manager import ContextManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_QUESTIONS_FILE = os.path.join(_SCRIPT_DIR, "../datasets/v2_questions.json")
DEFAULT_OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "../datasets")

MAX_WORKERS = 10          # 不同问题间并发
MAX_ROUNDS = 10           # 单问题多轮上限
MAX_TOKENS = 34000        # 上下文 token 上限（34K）
RESERVE_TOKENS = 2000     # 给 V2 输出预留的 token 数

# System prompt for V2（含 result 字段 + 查询链说明）
V2_SYSTEM_PROMPT = """你是 V2 查询策略模型。根据用户问题和历史查询结果，判断信息是否满足用户需求。

可用工具（含可返回字段）：
- kg_query.my_styles: 获取"我"的款号列表
  - 入参: 无
  - 可返回: ["styles", "styles.style_id", "styles.latest_category", "styles.event_count", "styles.total_delay_days", "total_styles"]
- kg_query.person_styles: 获取某人员的款号列表
  - 入参: {"person_name": "..."}
  - 可返回: ["styles", "styles.style_id", "styles.latest_category", "styles.event_count", "styles.total_delay_days", "total_styles"]
- kg_query.factory_styles: 获取某工厂的款号列表
  - 入参: {"factory_name": "..."}
  - 可返回: ["styles", "styles.style_id", "styles.total_delay_days", "total_styles"]
- kg_query.find_styles_with_conditions: 按条件筛选款号
  - 入参: {"categories": [...], "min_delay_days": N, "factory_name": "...", "person_name": "..."}
  - 可返回: ["styles", "styles.style_id", "total_styles"]
- kg_query.style_summaries: 批量获取款号摘要
  - 入参: {"style_ids": [...]}
  - 可返回: ["summaries", "summaries.style_id", "summaries.status", "summaries.current_stage", "summaries.delay_days", "summaries.last_update", "total"]
- kg_query.style_overview: 获取单个款号详情
  - 入参: {"style_id": "..."}
  - 可返回: ["style_id", "people", "timeline", "by_category", "by_category.面料", "by_category.封样", "total_events", "latest_category", "last_update"]
- kg_query.timeline: 获取单个款号时间线
  - 入参: {"style_id": "..."}
  - 可返回: ["style_id", "events", "events.date", "events.category", "events.delay_days", "events.description", "total"]
- kg_query.collaborators: 获取某人员的合作者
  - 入参: {"person_name": "...", "top_k": N}
  - 可返回: ["collaborators", "collaborators.name", "collaborators.event_count", "collaborators.style_count", "total_unique"]
- kg_query.factory_delays: 获取工厂延期排行
  - 入参: {"top_k": N}
  - 可返回: ["factories", "factories.name", "factories.total_delay_days", "factories.style_count"]
- rag_query.term_translation: 术语翻译
  - 入参: {"query": "...", "top_k": N}
  - 可返回: ["translations", "translations.chinese", "translations.english", "translations.category", "best_match"]
- rag_query.semantic_search: 语义检索
  - 入参: {"query": "...", "style_ids": [...], "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.score", "total"]
- rag_query.semantic_search_by_date: 按日期语义检索
  - 入参: {"query": "...", "style_ids": [...], "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.date", "total"]
- rag_query.semantic_search_by_conditions: 按条件语义检索
  - 入参: {"query": "...", "style_ids": [...], "categories": [...], "min_delay_days": N, "person_name": "...", "factory_name": "...", "top_k": N}
  - 可返回: ["events", "events.style_id", "events.description", "events.category", "events.delay_days", "total"]
- generate_answer: 生成回答（由外部系统执行）
  - 入参: {"template": "...", "data": {...}}
  - 可返回: []

输出格式（严格 JSON）：
{"thought": "判断过程...", "satisfied": true/false, "function_calls": [{"name": "...", "params": {...}, "result": [...]}]}

规则：
1. satisfied=false 时，function_calls 必须是查询工具（kg_query 或 rag_query）
2. satisfied=true 时，function_calls 必须是 generate_answer
3. 看到 [上下文警告] 时，基于现有信息判断 satisfied=true（部分满足）
4. 不要分页，不要截断，外部系统会处理
5. 不要编造不存在的数据，只基于已返回的结果判断
6. **使用 result 字段**：只请求需要的字段，减少数据量。如只查款号列表时 result=["styles.style_id", "total_styles"]
7. **查询链**：可在一个 function_calls 中同时输出一级查询（无款号范围）+ 二级查询（需款号），外部系统自动处理依赖和批量展开。一级查询返回款号列表，二级查询自动填入款号参数。
"""

# Few-shot 示例（含 result 字段 + 查询链）
FEW_SHOT_EXAMPLES = """
【示例1：我的款号进度（多轮 + result 精简）】
用户问题：我跟的款号进度怎么样

Round 1:
输入：用户问题
输出：{"thought": "用户查询我的款号进度，需要先获取款号列表，只取必要字段减少数据量", "satisfied": false, "function_calls": [{"name": "kg_query", "params": {"type": "my_styles"}, "result": ["styles.style_id", "styles.latest_category", "total_styles"]}]}

[工具返回] {"my_styles": {"styles": [{"style_id": "AW25-KFWTS101", "latest_category": "出货"}, {"style_id": "AW25-KFWTT156", "latest_category": "面料"}], "total_styles": 2}}

Round 2:
输入：用户问题 + 工具返回
输出：{"thought": "已获取2个款号，需要查更详细的摘要才能回答进度，只取关键字段", "satisfied": false, "function_calls": [{"name": "kg_query", "params": {"type": "style_summaries", "style_ids": ["AW25-KFWTS101", "AW25-KFWTT156"]}, "result": ["summaries.style_id", "summaries.status", "summaries.current_stage", "summaries.delay_days"]}]}

[工具返回] {"style_summaries": {"summaries": [{"style_id": "AW25-KFWTS101", "status": "正常", "current_stage": "出货"}, {"style_id": "AW25-KFWTT156", "status": "延期", "current_stage": "面料", "delay_days": 5}], "total": 2}}

Round 3:
输入：用户问题 + 所有历史结果
输出：{"thought": "已获取所有款号的进度摘要，信息满足用户提问", "satisfied": true, "function_calls": [{"name": "generate_answer", "params": {"template": "my_styles_summary", "data": {"summaries": [{"style_id": "AW25-KFWTS101", "status": "正常", "current_stage": "出货"}, {"style_id": "AW25-KFWTT156", "status": "延期", "current_stage": "面料", "delay_days": 5}]}}}]}

【示例2：查询链（一级 + 二级）】
用户问题：Paula Cheng 面料阶段事件数>30的款号

Round 1:
输入：用户问题
输出：{"thought": "需要：1) Paula Cheng的款号列表 2) 每个款号的面料事件数。使用查询链，先查款号列表，再批量查面料事件，只返回需要的字段", "satisfied": false, "function_calls": [{"name": "kg_query", "params": {"type": "person_styles", "person_name": "Paula Cheng"}, "result": ["styles.style_id", "total_styles"]}, {"name": "kg_query", "params": {"type": "style_overview"}, "result": ["style_id", "by_category.面料"]}]}

[工具返回] {"person_styles": {"styles": [{"style_id": "S1"}, {"style_id": "S2"}], "total_styles": 50}, "style_overviews": [{"style_id": "S1", "by_category": {"面料": [{"description": "面料确认", "delay_days": 2}]}}, ...]}

Round 2:
输入：用户问题 + 查询链结果
输出：{"thought": "已获取所有款号的面料事件数，统计后发现没有超过30个的", "satisfied": true, "function_calls": [{"name": "generate_answer", "params": {"template": "style_list", "data": {"message": "Paula Cheng 的款号中，面料阶段事件数最多的为 XX 个，没有超过30个的款号"}}}]}

【示例3：术语翻译（单轮搞定）】
用户问题：taffeta 怎么翻译

Round 1:
输入：用户问题
输出：{"thought": "用户询问术语翻译，直接用 RAG 查询术语库，只取最佳匹配", "satisfied": false, "function_calls": [{"name": "rag_query", "params": {"type": "term_translation", "query": "taffeta"}, "result": ["best_match"]}]}

[工具返回] {"term_translation": {"best_match": {"chinese": "塔夫绸", "english": "taffeta", "category": "面料"}}}

Round 2:
输入：用户问题 + 术语结果
输出：{"thought": "已获取术语翻译结果，信息满足用户提问", "satisfied": true, "function_calls": [{"name": "generate_answer", "params": {"template": "term_translation", "data": {"term": "taffeta", "translation": "塔夫绸", "category": "面料"}}}]}

【示例4：语义检索（RAG+KG 联合）】
用户问题：我参与的款号里有提到拉链问题的吗

Round 1:
输入：用户问题
输出：{"thought": "用户询问拉链问题，需要先获取用户的款号范围，再用 RAG 语义检索。先查款号列表", "satisfied": false, "function_calls": [{"name": "kg_query", "params": {"type": "my_styles"}, "result": ["styles.style_id"]}]}

[工具返回] {"my_styles": {"styles": [{"style_id": "AW25-KFWTS101"}, {"style_id": "AW25-KFWTT156"}], "total_styles": 2}}

Round 2:
输入：用户问题 + 款号列表
输出：{"thought": "已获取用户款号范围，现在用 RAG 语义检索拉链相关问题，限制在用户的款号范围内", "satisfied": false, "function_calls": [{"name": "rag_query", "params": {"type": "semantic_search", "query": "拉链问题", "style_ids": ["AW25-KFWTS101", "AW25-KFWTT156"]}, "result": ["events.style_id", "events.description", "events.category"]}]}

[工具返回] {"semantic_search": {"events": [{"style_id": "AW25-KFWTS101", "description": "拉链尺寸不符", "category": "封样"}], "total": 1}}

Round 3:
输入：用户问题 + 检索结果
输出：{"thought": "已找到拉链相关事件，信息满足用户提问", "satisfied": true, "function_calls": [{"name": "generate_answer", "params": {"template": "style_list", "data": {"events": [{"style_id": "AW25-KFWTS101", "description": "拉链尺寸不符", "category": "封样"}]}}}]}
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
# DeepSeek V2 模拟器（新版，使用 V2FunctionExecutor）
# ---------------------------------------------------------------------------

class V2Simulator:
    """用 DeepSeek 模拟 V2 的多轮判断能力（支持查询链 + result 字段）"""

    def __init__(self, client):
        self.client = client
        self.executor = V2FunctionExecutor(max_workers=10)
        self.truncator = ResultTruncator()
        self.cm = ContextManager(max_tokens=MAX_TOKENS, reserve_tokens=RESERVE_TOKENS)

    def simulate(self, question: str, requires_interface: list, reasoning: str, max_rounds: int = MAX_ROUNDS) -> list:
        """
        模拟 V2 多轮交互，返回 messages 列表

        Args:
            question: 用户问题
            requires_interface: 问题对应的参考接口列表（含 result 字段）
            reasoning: 问题对应的参考推理说明

        Returns:
            list of {"role": "user"|"assistant", "content": str}
        """
        messages = []
        history_text = ""
        round_num = 0
        # 累积上下文，用于查询链中的依赖解析
        context = {}

        while round_num < max_rounds:
            round_num += 1

            # 构造 prompt（传入 requires_interface 和 reasoning 作为参考）
            prompt = self._build_round_prompt(question, history_text, requires_interface, reasoning, round_num)

            # 调用 DeepSeek
            v2_output = self._call_deepseek(prompt)
            if not v2_output:
                break

            # 解析 V2 输出
            try:
                v2_json = json.loads(v2_output)
            except json.JSONDecodeError:
                v2_json = self._extract_json(v2_output)

            if not v2_json:
                break

            # 记录 assistant 输出
            assistant_content = json.dumps(v2_json, ensure_ascii=False)
            messages.append({"role": "assistant", "content": assistant_content})

            # 检查是否 satisfied
            satisfied = v2_json.get("satisfied", False)
            function_calls = v2_json.get("function_calls", [])

            if satisfied:
                # V2 判断满足，结束多轮
                break

            # 执行 function_calls（使用 V2FunctionExecutor，支持查询链 + result 过滤）
            if not function_calls:
                break

            try:
                result = self.executor.execute(function_calls, context=context)
            except ValueError as e:
                # 查询链配置错误（如非法组合）
                result = {"status": "failed", "error": str(e)}
            except Exception as e:
                result = {"status": "failed", "error": f"执行异常: {str(e)}"}

            # 构造工具返回文本（使用 ResultTruncator + ContextManager 截断）
            tool_result_text = self._format_tool_result(result, messages)

            user_content = f"[工具返回] {tool_result_text}"
            messages.append({"role": "user", "content": user_content})

            # 更新历史
            history_text += f"\nRound {round_num}:\nV2输出: {assistant_content}\n工具返回: {tool_result_text}"

            # 更新上下文（用于查询链依赖解析）
            if result.get("status") == "success":
                context.update({k: v for k, v in result.items() if not k.startswith("_")})

        return messages

    def _format_tool_result(self, result: dict, current_messages: list) -> str:
        """
        格式化工具返回结果，使用 ResultTruncator + ContextManager 做 token 级截断

        Args:
            result: V2FunctionExecutor 的原始返回
            current_messages: 当前会话的消息列表（用于计算剩余空间）

        Returns:
            截断后的 JSON 字符串（可能带 [上下文警告]）
        """
        raw_text = json.dumps(result, ensure_ascii=False)
        raw_tokens = self.cm.estimate_tokens(raw_text)

        # 检查添加后是否溢出
        overflow_check = self.cm.check_content_overflow(current_messages, raw_text)

        if overflow_check.status == "ok":
            # 未超限，直接返回
            return raw_text

        # 需要截断——区分查询链结果和单轮结果
        # 查询链格式：{"status": "success", "<secondary_type>s": [...], "_meta": {...}}
        # 单轮格式：{"status": "success", "events": [...]} 或 {"status": "success", "styles": [...]}
        has_meta = "_meta" in result
        data_keys = [k for k in result.keys() if not k.startswith("_") and k != "status"]
        is_chain = has_meta and len(data_keys) == 1

        if is_chain:
            return self._truncate_chain_result(result, overflow_check)
        else:
            return self._truncate_single_result(result, overflow_check)

    def _truncate_chain_result(self, result: dict, check) -> str:
        """截断查询链结果（只保留二级结果 + _meta，一级结果已省略）"""
        # 查询链结果格式：{"status": "success", "<secondary_type>s": [...], "_meta": {...}}
        data_keys = [k for k in result.keys() if not k.startswith("_") and k != "status"]
        if not data_keys:
            return json.dumps(result, ensure_ascii=False)

        secondary_key = data_keys[0]
        secondary_data = result[secondary_key]

        # 推断截断规则类型
        secondary_type = "kg_query.style_summaries"  # 默认用 style_summaries 规则处理二级列表

        # 计算可用空间（当前结果可占用的 token 数）
        # 允许占用到 effective_limit 的 95%（留一点缓冲）
        available_tokens = int(self.cm.effective_limit * 0.95) - check.used_tokens + self.cm.estimate_tokens(json.dumps(result, ensure_ascii=False))
        available_tokens = max(1000, available_tokens)

        # 迭代截断二级结果直到满足限制
        best_result = None

        for max_s in [200, 150, 100, 50, 30, 20, 10]:
            # 二级数据包装为 summaries 格式以复用规则
            secondary_wrapped = {"summaries": secondary_data} if isinstance(secondary_data, list) else secondary_data
            r = self.truncator.truncate(secondary_wrapped, secondary_type, max_items=max_s)

            truncated = {
                "status": "success",
                secondary_key: r.truncated_data.get("summaries", r.truncated_data),
                "_meta": {
                    **result.get("_meta", {}),
                    "truncated": True,
                    "secondary_returned": r.returned_count,
                },
            }

            t = json.dumps(truncated, ensure_ascii=False)
            tokens = self.cm.estimate_tokens(t)

            if tokens <= available_tokens:
                # 找到满足条件的，选返回数量最多的
                if best_result is None or r.returned_count > best_result[1].returned_count:
                    best_result = (truncated, r, t)

        if best_result is None:
            # 极端情况：连 10 个都超，直接硬截断
            raw_text = json.dumps(result, ensure_ascii=False)
            return raw_text[:6000] + '\n...[truncated]'

        truncated, r, t = best_result

        # 添加警告
        if r.original_count > r.returned_count:
            warned = self.cm.add_warning(
                truncated,
                r.original_count,
                r.returned_count,
            )
            return warned

        return t

    def _truncate_single_result(self, result: dict, check) -> str:
        """截断单轮独立结果"""
        # 识别主数据字段和类型
        data_keys = [k for k in result.keys() if not k.startswith("_") and k != "status"]
        if not data_keys:
            return json.dumps(result, ensure_ascii=False)

        main_key = data_keys[0]
        main_data = result[main_key]

        # 推断规则类型
        if main_key == "events":
            query_type = "rag_query.semantic_search"
        elif main_key == "styles":
            query_type = "kg_query.my_styles"
        elif main_key == "summaries":
            query_type = "kg_query.style_summaries"
        elif main_key == "collaborators":
            query_type = "kg_query.collaborators"
        elif main_key == "factories":
            query_type = "kg_query.factory_delays"
        elif main_key == "translations":
            query_type = "rag_query.term_translation"
        else:
            query_type = "unknown"

        # 计算可用空间
        available_tokens = int(self.cm.effective_limit * 0.95) - check.used_tokens + self.cm.estimate_tokens(json.dumps(result, ensure_ascii=False))
        available_tokens = max(500, available_tokens)

        # 截断
        truncated_result = self.truncator.truncate(result, query_type)
        t = json.dumps(truncated_result.truncated_data, ensure_ascii=False)
        tokens = self.cm.estimate_tokens(t)

        if tokens <= available_tokens:
            # 未超限或截断后满足
            if truncated_result.original_count > truncated_result.returned_count:
                warned = self.cm.add_warning(
                    truncated_result.truncated_data,
                    truncated_result.original_count,
                    truncated_result.returned_count,
                )
                return warned
            return t

        # 还超，进一步限制数量
        rule = self.truncator.RULES.get(query_type)
        item_estimate = rule.item_token_estimate if rule else 100
        max_items = self.cm.calculate_max_items(item_estimate, available_tokens)

        truncated_result = self.truncator.truncate(result, query_type, max_items=max_items)
        t = json.dumps(truncated_result.truncated_data, ensure_ascii=False)

        if truncated_result.original_count > truncated_result.returned_count:
            warned = self.cm.add_warning(
                truncated_result.truncated_data,
                truncated_result.original_count,
                truncated_result.returned_count,
            )
            return warned

        return t

    def _build_round_prompt(self, question: str, history: str, requires_interface: list, reasoning: str, round_num: int) -> str:
        """构造每轮的 DeepSeek prompt（传入参考接口和推理）"""
        parts = [V2_SYSTEM_PROMPT]
        parts.append(FEW_SHOT_EXAMPLES)

        # 添加参考信息（帮助 DeepSeek 模拟时参考）
        parts.append("\n【参考信息】（这是该问题建议的查询策略，请学习其思路但根据实际情况调整）")
        parts.append(f"建议接口: {json.dumps(requires_interface, ensure_ascii=False)}")
        parts.append(f"建议推理: {reasoning}")
        parts.append("\n注意：以上仅供参考，你应根据实际问题和已返回结果做独立判断。如果已有信息足够，直接 satisfied=true。")

        parts.append(f"\n【当前任务】\n用户问题：{question}\n")

        if history:
            parts.append(f"【历史交互】\n{history}\n")

        parts.append(f"【Round {round_num}】请输出 JSON 格式的 V2 判断：")
        return "\n".join(parts)

    def _call_deepseek(self, prompt: str) -> str:
        """调用 DeepSeek API"""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": "你是一个专业的 V2 查询策略模型，只输出 JSON 格式。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                    timeout=REQUEST_TIMEOUT,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"      DeepSeek 调用失败: {e}")
                    return ""
        return ""

    def _extract_json(self, text: str) -> dict:
        """从文本中提取 JSON"""
        # 尝试 Markdown 代码块
        match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass

        # 尝试直接找 JSON 对象
        match = re.search(r'\{.*"thought".*"satisfied".*"function_calls".*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return None


# ---------------------------------------------------------------------------
# 训练数据组装
# ---------------------------------------------------------------------------

def build_sharegpt_record(question: str, chain_type: str, messages: list) -> dict:
    """组装成 ShareGPT 格式"""
    full_messages = [
        {"role": "system", "content": V2_SYSTEM_PROMPT},
        {"role": "user", "content": f"[用户提问] {question}"},
    ]

    # 交替添加 assistant 和 user
    for msg in messages:
        full_messages.append(msg)

    return {
        "messages": full_messages,
    }


def build_dpo_pair(question: str, chain_type: str, messages: list) -> dict:
    """
    从多轮交互中提取一个 DPO 对（取最后一轮决策）

    chosen: 正确的 satisfied 判断
    rejected: 构造一个错误的判断（如过早 satisfied 或错误查询）
    """
    if len(messages) < 2:
        return None

    # 找到最后一个 assistant 消息（satisfied=true 的决策）
    last_assistant = None
    last_user = None
    for msg in reversed(messages):
        if msg["role"] == "assistant" and not last_assistant:
            last_assistant = msg["content"]
        elif msg["role"] == "user" and not last_user:
            last_user = msg["content"]

    if not last_assistant:
        return None

    try:
        v2_json = json.loads(last_assistant)
    except:
        return None

    # 构造 input（最后一轮前的所有上下文）
    input_text = f"[用户提问] {question}\n{last_user}" if last_user else f"[用户提问] {question}"

    chosen = last_assistant

    # 构造 rejected：如果 satisfied=true，则 rejected 为 satisfied=false 继续查；反之亦然
    satisfied = v2_json.get("satisfied", False)
    if satisfied:
        # 错误：应该继续查而不是回答
        rejected_json = {
            "thought": "信息还不够完整，需要继续查询",
            "satisfied": False,
            "function_calls": [{"name": "kg_query", "params": {"type": "my_styles"}, "result": ["styles.style_id", "total_styles"]}],
        }
    else:
        # 错误：应该直接回答而不是继续查
        rejected_json = {
            "thought": "已有足够信息，可以直接回答",
            "satisfied": True,
            "function_calls": [{"name": "generate_answer", "params": {"template": "not_found", "data": {}}}],
        }

    rejected = json.dumps(rejected_json, ensure_ascii=False)

    return {
        "instruction": V2_SYSTEM_PROMPT,
        "input": input_text,
        "chosen": chosen,
        "rejected": rejected,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def build_v2_dataset(
    questions_path: str,
    output_dir: str,
    train_target: int = 400,
    val_target: int = 50,
    test_target: int = 50,
    max_workers: int = MAX_WORKERS,
    seed: int = 42,
):
    """生成 V2 训练数据（含训练集/验证集/测试集划分）

    划分策略：
    - 训练集：按 chain_type 分层采样，保证各接口组合比例
    - 验证集：从剩余样本中随机采样
    - 测试集：从剩余样本中随机采样
    - 三者互不重叠
    """
    random.seed(seed)

    print(f"[1/6] 加载问题数据: {questions_path} ...")
    with open(questions_path, "r", encoding="utf-8") as f:
        questions_data = json.load(f)
    all_questions = questions_data.get("questions", [])
    print(f"      总问题数: {len(all_questions)}")

    # 过滤掉验证失败的问题
    valid_questions = [q for q in all_questions if q.get("validation", {}).get("status") == "success"]
    failed_count = len(all_questions) - len(valid_questions)
    print(f"      验证通过: {len(valid_questions)} 条, 过滤失败: {failed_count} 条")

    # 按场景分组
    scene_groups = defaultdict(list)
    for q in valid_questions:
        scene_groups[q.get("chain_type") or q.get("interface_type", "unknown")].append(q)
    print(f"      场景分布: {dict((k, len(v)) for k, v in scene_groups.items())}")

    # 计算总目标
    total_target = train_target + val_target + test_target
    if len(valid_questions) > total_target:
        # 按场景比例采样总目标数量
        sampled = []
        for scene, items in scene_groups.items():
            scene_ratio = len(items) / len(valid_questions)
            scene_target = int(total_target * scene_ratio)
            if len(items) < scene_target:
                sampled.extend(items)
            else:
                sampled.extend(random.sample(items, scene_target))
        # 补足差额
        while len(sampled) < total_target:
            remaining = [q for q in valid_questions if q not in sampled]
            if remaining:
                sampled.append(random.choice(remaining))
            else:
                break
        valid_questions = sampled
    print(f"      采样目标: {len(valid_questions)} 条 (训练{train_target}/验证{val_target}/测试{test_target})")

    # 划分训练/验证/测试
    print(f"\n[2/6] 划分数据集 ...")
    random.shuffle(valid_questions)

    train_questions = valid_questions[:train_target]
    remaining = valid_questions[train_target:]

    val_questions = remaining[:val_target]
    test_questions = remaining[val_target:val_target + test_target]

    # 检查重叠（使用 question 文本作为唯一标识）
    train_qs = set(q["question"] for q in train_questions)
    val_qs = set(q["question"] for q in val_questions)
    test_qs = set(q["question"] for q in test_questions)
    overlap_tv = train_qs & val_qs
    overlap_tt = train_qs & test_qs
    overlap_vt = val_qs & test_qs
    if overlap_tv or overlap_tt or overlap_vt:
        print(f"      ⚠️ 重叠警告: train∩val={len(overlap_tv)}, train∩test={len(overlap_tt)}, val∩test={len(overlap_vt)}")
    else:
        print(f"      ✅ 数据集无重叠")
    print(f"      训练集: {len(train_questions)} 条")
    print(f"      验证集: {len(val_questions)} 条")
    print(f"      测试集: {len(test_questions)} 条")

    print(f"\n[3/6] 初始化 DeepSeek...")
    client = get_deepseek_client()
    print("      DeepSeek API 已启用")

    print(f"\n[4/6] 初始化 V2 模拟器（V2FunctionExecutor）...")
    simulator = V2Simulator(client)
    print("      V2FunctionExecutor 已加载（支持查询链 + result 字段过滤）")

    def process_split(questions, split_name):
        """处理一个数据分片，返回 SFT 和 DPO 记录"""
        if not questions:
            return [], []

        print(f"\n  处理 {split_name} ({len(questions)} 条，并发 {max_workers})...")
        sft_records = []
        dpo_records = []
        completed = 0
        success = 0
        failed = 0
        total_rounds = 0
        chain_used = 0
        result_used = 0
        start_time = time.time()

        def process_one(q_item):
            question = q_item["question"]
            chain_type = q_item.get("chain_type") or q_item.get("interface_type", "unknown")
            requires_interface = q_item.get("requires_interface", [])
            reasoning = q_item.get("reasoning", "")
            try:
                messages = simulator.simulate(question, requires_interface, reasoning)
                if not messages:
                    return None
                sft = build_sharegpt_record(question, chain_type, messages)
                dpo = build_dpo_pair(question, chain_type, messages)

                # 统计指标
                rounds = len([m for m in messages if m["role"] == "assistant"])
                has_chain = False
                has_result = False
                for m in messages:
                    if m["role"] == "assistant":
                        try:
                            mj = json.loads(m["content"])
                            fcs = mj.get("function_calls", [])
                            # 检查 result 字段
                            for fc in fcs:
                                if fc.get("result"):
                                    has_result = True
                                    break
                            # 检查查询链：2 个调用且第一个是 kg_query/rag_query 无 style_id
                            if len(fcs) == 2:
                                fc0 = fcs[0]
                                fc1 = fcs[1]
                                if (fc0.get("name") in ("kg_query", "rag_query") and
                                    fc1.get("name") in ("kg_query", "rag_query") and
                                    "style_id" not in fc0.get("params", {}) and
                                    "style_ids" not in fc0.get("params", {})):
                                    has_chain = True
                        except:
                            pass

                return {
                    "sft": sft,
                    "dpo": dpo,
                    "rounds": rounds,
                    "has_chain": has_chain,
                    "has_result": has_result,
                }
            except Exception as e:
                print(f"\n      处理失败 [{question[:30]}...]: {e}")
                return None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_one, q): q for q in questions}

            for future in as_completed(futures):
                result = future.result()
                completed += 1

                if result:
                    success += 1
                    sft_records.append(result["sft"])
                    if result["dpo"]:
                        dpo_records.append(result["dpo"])
                    total_rounds += result["rounds"]
                    if result["has_chain"]:
                        chain_used += 1
                    if result["has_result"]:
                        result_used += 1
                else:
                    failed += 1

                elapsed = time.time() - start_time
                avg_time = elapsed / completed if completed > 0 else 0
                remain = (len(questions) - completed) * avg_time
                avg_rounds = total_rounds / success if success > 0 else 0
                suffix = f"成功:{success} 失败:{failed} 平均轮次:{avg_rounds:.1f} 链:{chain_used} result:{result_used} 预计剩余:{remain/60:.1f}分钟"
                _print_progress_bar(completed, len(questions), prefix=f"  {split_name}", suffix=suffix)

        elapsed_total = time.time() - start_time
        print(f"\n  ✓ {split_name} 完成：成功 {success}/{len(questions)}，平均轮次 {total_rounds/max(success,1):.1f}，查询链使用 {chain_used}，result 使用 {result_used}，耗时 {elapsed_total/60:.1f} 分钟")
        return sft_records, dpo_records

    # 处理三个分片
    train_sft, train_dpo = process_split(train_questions, "训练集")
    val_sft, val_dpo = process_split(val_questions, "验证集")
    test_sft, test_dpo = process_split(test_questions, "测试集")

    # 保存
    print(f"\n[6/6] 保存结果到 {output_dir} ...")
    os.makedirs(output_dir, exist_ok=True)

    splits = {
        "train": (train_sft, train_dpo),
        "val": (val_sft, val_dpo),
        "test": (test_sft, test_dpo),
    }

    for split_name, (sft_data, dpo_data) in splits.items():
        split_dir = os.path.join(output_dir, split_name)
        os.makedirs(split_dir, exist_ok=True)

        # SFT
        sft_path = os.path.join(split_dir, "sft_v2_multiround.jsonl")
        with open(sft_path, "w", encoding="utf-8") as f:
            for r in sft_data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"      {split_name}/SFT: {len(sft_data)} 条 → {sft_path}")

        # DPO
        if dpo_data:
            dpo_path = os.path.join(split_dir, "dpo_v2_multiround.jsonl")
            with open(dpo_path, "w", encoding="utf-8") as f:
                for r in dpo_data:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"      {split_name}/DPO: {len(dpo_data)} 条 → {dpo_path}")

    # Stats
    def _split_stats(sft_data, dpo_data):
        round_dist = defaultdict(int)
        chain_count = 0
        result_count = 0
        for r in sft_data:
            assistant_count = len([m for m in r["messages"] if m["role"] == "assistant"])
            round_dist[assistant_count] += 1
            # 统计查询链和 result 使用率
            for m in r["messages"]:
                if m["role"] == "assistant":
                    try:
                        mj = json.loads(m["content"])
                        fcs = mj.get("function_calls", [])
                        # 检查 result 字段
                        for fc in fcs:
                            if fc.get("result"):
                                result_count += 1
                                break
                        # 检查查询链
                        if len(fcs) == 2:
                            fc0 = fcs[0]
                            fc1 = fcs[1]
                            if (fc0.get("name") in ("kg_query", "rag_query") and
                                fc1.get("name") in ("kg_query", "rag_query") and
                                "style_id" not in fc0.get("params", {}) and
                                "style_ids" not in fc0.get("params", {})):
                                chain_count += 1
                    except:
                        pass
        return {
            "sft_count": len(sft_data),
            "dpo_count": len(dpo_data),
            "round_distribution": dict(round_dist),
            "chain_count": chain_count,
            "result_count": result_count,
        }

    stats = {
        "generated_at": datetime.now().isoformat(),
        "seed": seed,
        "train": _split_stats(train_sft, train_dpo),
        "val": _split_stats(val_sft, val_dpo),
        "test": _split_stats(test_sft, test_dpo),
    }

    stats_path = os.path.join(output_dir, "v2_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"      Stats → {stats_path}")

    print(f"\n{'='*60}")
    print(f"✅ 全部完成！")
    print(f"{'='*60}")
    print(f"TRAIN: {output_dir}/train/sft_v2_multiround.jsonl ({len(train_sft)} 条)")
    print(f"VAL:   {output_dir}/val/sft_v2_multiround.jsonl ({len(val_sft)} 条)")
    print(f"TEST:  {output_dir}/test/sft_v2_multiround.jsonl ({len(test_sft)} 条)")
    print(f"{'='*60}")

    return train_sft, val_sft, test_sft


def main():
    parser = argparse.ArgumentParser(description="Build V2 multi-round dataset (v2 format with result + chain)")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS_FILE, help="Path to v2_questions.json")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--train-target", type=int, default=400, help="Target training samples")
    parser.add_argument("--val-target", type=int, default=50, help="Target validation samples")
    parser.add_argument("--test-target", type=int, default=50, help="Target test samples")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS, help="Concurrency")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    build_v2_dataset(
        questions_path=args.questions,
        output_dir=args.output_dir,
        train_target=args.train_target,
        val_target=args.val_target,
        test_target=args.test_target,
        max_workers=args.max_workers,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
# python build_v2_dataset.py --train-target 800 --val-target 100 --test-target 100 --max-workers 20