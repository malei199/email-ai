"""
V2 Function Calls 执行引擎

职责：
1. 接收 V2 输出的 function_calls 列表
2. 匹配查询链配置（一级 + 二级）
3. 按配置执行：先一级查询，提取依赖值，批量展开二级查询，并行执行
4. 支持 result 字段过滤
5. 返回标准化结果

规则：
- 一级报错 → 整体失败
- 二级报错 → 降级（省略错误项，继续）
- semantic_search 只能作为一级接口（不能作为二级）
- style_ids 列表过长不分批
- 返回格式按接口名包装
"""

import copy
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from email_agent.services import kg_adapter, rag_adapter


# ---------------------------------------------------------------------------
# 查询链配置
# ---------------------------------------------------------------------------

CALL_CHAIN_RULES = {
    # KG 一级 → KG/RAG 二级
    "my_styles": {
        "style_overview": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "semantic_search": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_date": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_conditions": {
            "primary": {"name": "kg_query", "type": "my_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
    },
    "person_styles": {
        "style_overview": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "semantic_search": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_date": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_conditions": {
            "primary": {"name": "kg_query", "type": "person_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
    },
    "factory_styles": {
        "style_overview": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "semantic_search": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_date": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_conditions": {
            "primary": {"name": "kg_query", "type": "factory_styles"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
    },
    "find_styles_with_conditions": {
        "style_overview": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "styles[].style_id", "to": "style_id", "auto_fill": True},
        },
        "semantic_search": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "rag_query", "type": "semantic_search"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_date": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "semantic_search_by_conditions": {
            "primary": {"name": "kg_query", "type": "find_styles_with_conditions"},
            "secondary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "dependency": {"from": "styles[].style_id", "to": "style_ids", "auto_fill": True},
        },
    },

    # RAG 一级 → KG 二级
    "semantic_search": {
        "style_overview": {
            "primary": {"name": "rag_query", "type": "semantic_search"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "rag_query", "type": "semantic_search"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "events[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "rag_query", "type": "semantic_search"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
    },
    "semantic_search_by_date": {
        "style_overview": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "events[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_date"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
    },
    "semantic_search_by_conditions": {
        "style_overview": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "secondary": {"name": "kg_query", "type": "style_overview"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
        "style_summaries": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "secondary": {"name": "kg_query", "type": "style_summaries"},
            "dependency": {"from": "events[].style_id", "to": "style_ids", "auto_fill": True},
        },
        "timeline": {
            "primary": {"name": "rag_query", "type": "semantic_search_by_conditions"},
            "secondary": {"name": "kg_query", "type": "timeline"},
            "dependency": {"from": "events[].style_id", "to": "style_id", "auto_fill": True},
        },
    },
}

# RAG 检索接口之间不能互相关联
RAG_SEARCH_TYPES = {"semantic_search", "semantic_search_by_date", "semantic_search_by_conditions"}


# ---------------------------------------------------------------------------
# 执行引擎
# ---------------------------------------------------------------------------

class V2FunctionExecutor:
    """V2 function_calls 执行引擎"""

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers

    # -----------------------------------------------------------------------
    # 主入口
    # -----------------------------------------------------------------------

    def execute(self, function_calls: List[dict], context: dict = None) -> dict:
        """
        执行 V2 的 function_calls 序列

        Args:
            function_calls: V2 输出的调用列表
            context: 前序轮次的累积结果（用于依赖解析）

        Returns:
            {
                "status": "success" | "failed" | "answer",
                ...
            }
        """
        if not function_calls:
            return {"status": "failed", "error": "function_calls 为空"}

        # 快速路径：generate_answer
        first_call = function_calls[0]
        if first_call.get("name") == "generate_answer":
            return {
                "status": "answer",
                "template": first_call["params"].get("template"),
                "data": first_call["params"].get("data"),
            }

        # 匹配查询链配置
        chain_rule = self._match_chain_rule(function_calls)

        if chain_rule:
            return self._execute_chain(function_calls, chain_rule)
        else:
            return self._execute_single(function_calls)

    # -----------------------------------------------------------------------
    # 查询链执行
    # -----------------------------------------------------------------------

    def _execute_chain(self, function_calls: List[dict], chain_rule: dict) -> dict:
        """执行查询链（一级 + 二级）"""
        primary_call = function_calls[0]
        secondary_template = function_calls[1]

        # 1. 执行一级查询
        primary_result = self._execute_call(primary_call)

        if primary_result.get("error"):
            return {
                "status": "failed",
                "failed_at": "primary",
                "error": primary_result["error"],
                "primary_result": primary_result,
            }

        # 2. 提取依赖值
        dep = chain_rule["dependency"]
        dependency_values = self._extract_dependency_value(
            primary_result, dep["from"]
        )

        if not dependency_values:
            return {
                "status": "failed",
                "failed_at": "dependency_extraction",
                "error": f"无法从一级结果提取依赖值: {dep['from']}",
                "primary_result": primary_result,
            }

        # 3. 批量展开二级调用
        secondary_calls = self._expand_secondary_calls(
            secondary_template, dependency_values, dep["to"]
        )

        # 4. 并行执行二级查询
        secondary_results = []
        secondary_errors = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_call = {
                executor.submit(self._execute_call, call): call
                for call in secondary_calls
            }

            for future in as_completed(future_to_call):
                call = future_to_call[future]
                try:
                    result = future.result()
                    if result.get("error"):
                        # 二级报错 → 降级（记录错误，省略错误项）
                        secondary_errors.append({
                            "call": call,
                            "error": result["error"],
                        })
                    else:
                        # result 字段过滤
                        filtered = self._apply_result_filter(
                            result, call.get("result", [])
                        )
                        secondary_results.append(filtered)
                except Exception as e:
                    secondary_errors.append({
                        "call": call,
                        "error": str(e),
                    })

        # 5. 按接口名包装返回（只保留二级结果 + 元信息，省略一级结果以节省上下文）
        secondary_type = secondary_template["params"]["type"]

        return {
            "status": "success",
            f"{secondary_type}s": secondary_results,  # 复数形式表示多个结果
            "_meta": {
                "primary_total": len(dependency_values),
                "secondary_total": len(secondary_calls),
                "secondary_success": len(secondary_results),
                "secondary_failed": len(secondary_errors),
            },
        }

    # -----------------------------------------------------------------------
    # 单轮独立执行
    # -----------------------------------------------------------------------

    def _execute_single(self, function_calls: List[dict]) -> dict:
        """执行单轮独立调用（无依赖关系）"""
        results = {}
        errors = []

        for i, call in enumerate(function_calls):
            result = self._execute_call(call)
            call_type = call.get("params", {}).get("type", f"call_{i}")

            if result.get("error"):
                errors.append({
                    "index": i,
                    "type": call_type,
                    "error": result["error"],
                })
            else:
                filtered = self._apply_result_filter(
                    result, call.get("result", [])
                )
                results[call_type] = filtered

        return {
            "status": "success" if not errors else "partial",
            **results,
            "_errors": errors if errors else None,
        }

    # -----------------------------------------------------------------------
    # 原子调用执行
    # -----------------------------------------------------------------------

    def _execute_call(self, call: dict) -> dict:
        """执行单个 function_call"""
        name = call.get("name", "")
        params = call.get("params", {})

        try:
            if name == "kg_query":
                return self._execute_kg(params)
            elif name == "rag_query":
                return self._execute_rag(params)
            else:
                return {"error": f"Unknown function: {name}"}
        except Exception as e:
            return {"error": f"执行失败: {str(e)}"}

    def _execute_kg(self, params: dict) -> dict:
        """执行 KG 查询"""
        qtype = params.get("type", "")

        if qtype == "my_styles":
            person = self._get_default_person()
            return kg_adapter.query_person_styles_with_stats(person)

        elif qtype == "person_styles":
            person = params.get("person_name", "")
            return kg_adapter.query_person_styles_with_stats(person)

        elif qtype == "factory_styles":
            factory = params.get("factory_name", "")
            return kg_adapter.query_styles_by_factory(factory)

        elif qtype == "style_summaries":
            style_ids = params.get("style_ids", [])
            summaries = []
            for sid in style_ids:
                overview = kg_adapter.get_style_overview(sid)
                if not overview.get("error"):
                    summaries.append({
                        "style_id": sid,
                        "latest_category": overview.get("latest_category", ""),
                        "total_events": overview.get("total_events", 0),
                        "total_delay_days": overview.get("total_delay_days", 0),
                        "last_update": overview.get("last_update", ""),
                    })
            return {"summaries": summaries, "total": len(style_ids)}

        elif qtype == "style_overview":
            sid = params.get("style_id", "")
            return kg_adapter.get_style_overview(sid)

        elif qtype == "timeline":
            sid = params.get("style_id", "")
            events = kg_adapter.query_timeline(sid)
            return {"style_id": sid, "events": events, "total": len(events)}

        elif qtype == "collaborators":
            person = params.get("person_name", "")
            top_k = params.get("top_k", 10)
            return kg_adapter.query_collaborators(person, top_k=top_k)

        elif qtype == "factory_delays":
            top_k = params.get("top_k", 10)
            return kg_adapter.query_factory_delays(top_k=top_k)

        elif qtype == "find_styles_with_conditions":
            return kg_adapter.find_styles_with_conditions(
                categories=params.get("categories"),
                min_delay_days=params.get("min_delay_days"),
                factory_name=params.get("factory_name"),
                person_name=params.get("person_name"),
            )

        else:
            return {"error": f"Unknown kg_query type: {qtype}"}

    def _execute_rag(self, params: dict) -> dict:
        """执行 RAG 查询"""
        qtype = params.get("type", "")

        if qtype == "term_translation":
            query = params.get("query", "")
            top_k = params.get("top_k", 3)
            return rag_adapter.translate_term(query, top_k=top_k)

        elif qtype == "semantic_search":
            query = params.get("query", "")
            style_ids = params.get("style_ids")
            top_k = params.get("top_k", 10)
            events = rag_adapter.query_email_events(
                style_ids=style_ids,
                query_text=query,
                top_k=top_k,
            )
            return {
                "query": query,
                "events": events,
                "total": len(events),
            }

        elif qtype == "semantic_search_by_conditions":
            style_ids = params.get("style_ids")
            categories = params.get("categories")
            min_delay_days = params.get("min_delay_days")
            top_k = params.get("top_k", 100)
            events = rag_adapter.query_email_events_by_conditions(
                style_ids=style_ids,
                categories=categories,
                min_delay_days=min_delay_days,
                top_k=top_k,
            )
            return {
                "events": events,
                "total": len(events),
            }

        elif qtype == "semantic_search_by_date":
            style_ids = params.get("style_ids")
            days = params.get("days", 7)
            events = rag_adapter.query_email_events_by_date(
                style_ids=style_ids,
                days=days,
            )
            return {
                "events": events,
                "total": len(events),
            }

        else:
            return {"error": f"Unknown rag_query type: {qtype}"}

    # -----------------------------------------------------------------------
    # 配置匹配
    # -----------------------------------------------------------------------

    def _match_chain_rule(self, function_calls: List[dict]) -> Optional[dict]:
        """匹配查询链配置

        规则：
        1. 必须是 2 个调用
        2. RAG 检索接口之间不能互相关联
        3. 一级接口必须在 CALL_CHAIN_RULES 中
        4. 二级接口必须在一级的配置中
        5. name 必须匹配
        """
        if len(function_calls) != 2:
            return None

        primary_type = function_calls[0].get("params", {}).get("type")
        secondary_type = function_calls[1].get("params", {}).get("type")

        # RAG 检索接口之间不能互相关联
        if primary_type in RAG_SEARCH_TYPES and secondary_type in RAG_SEARCH_TYPES:
            raise ValueError(
                f"非法组合：RAG 检索接口不能互相关联（{primary_type} → {secondary_type}）"
            )

        # 两级查找：primary_type → secondary_type
        primary_rules = CALL_CHAIN_RULES.get(primary_type)
        if not primary_rules:
            raise ValueError(f"非法组合：一级接口 {primary_type} 不支持查询链")

        rule = primary_rules.get(secondary_type)
        if not rule:
            raise ValueError(
                f"非法组合：{primary_type} → {secondary_type} 未在配置中定义"
            )

        # 校验 name 匹配
        primary_name = function_calls[0].get("name")
        secondary_name = function_calls[1].get("name")
        if (primary_name != rule["primary"]["name"] or
            secondary_name != rule["secondary"]["name"]):
            raise ValueError(
                f"非法组合：name 不匹配（{primary_name} → {secondary_name}）"
            )

        return rule

    # -----------------------------------------------------------------------
    # 依赖提取与展开
    # -----------------------------------------------------------------------

    def _extract_dependency_value(self, primary_result: dict, from_path: str) -> list:
        """从一级结果提取依赖值"""
        parts = from_path.split(".")
        current = primary_result

        for part in parts:
            if part.endswith("[]"):
                key = part.replace("[]", "")
                current = current.get(key, []) if isinstance(current, dict) else []
                if not isinstance(current, list):
                    return []
            else:
                if isinstance(current, list):
                    current = [item.get(part) for item in current if isinstance(item, dict)]
                elif isinstance(current, dict):
                    current = current.get(part)
                else:
                    return []

            if current is None:
                return []

        # 去重 + 过滤空值
        if isinstance(current, list):
            return list(dict.fromkeys([x for x in current if x is not None]))

        return [current] if current is not None else []

    def _expand_secondary_calls(self, secondary_template: dict, values: list, to_path: str) -> List[dict]:
        """批量展开二级调用"""
        calls = []

        if to_path == "style_id":
            # 单个参数：每个 value 一个调用
            for value in values:
                call = copy.deepcopy(secondary_template)
                call["params"]["style_id"] = value
                calls.append(call)

        elif to_path == "style_ids":
            # 列表参数：所有 value 合并成一个调用
            call = copy.deepcopy(secondary_template)
            call["params"]["style_ids"] = values
            calls.append(call)

        else:
            # 其他参数路径
            call = copy.deepcopy(secondary_template)
            self._set_param_by_path(call["params"], to_path, values)
            calls.append(call)

        return calls

    def _set_param_by_path(self, params: dict, path: str, value):
        """按路径设置参数值"""
        parts = path.split(".")
        current = params

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    # -----------------------------------------------------------------------
    # result 字段过滤
    # -----------------------------------------------------------------------

    def _apply_result_filter(self, result: dict, result_fields: List[str]) -> dict:
        """根据 result 字段列表过滤返回结果，保留原始数据结构
        
        示例：
        原始: {"styles": [{"style_id": "S1", "latest_category": "出货", "event_count": 5}], "total_styles": 253}
        过滤: ["styles.style_id", "styles.latest_category", "total_styles"]
        结果: {"styles": [{"style_id": "S1", "latest_category": "出货"}], "total_styles": 253}
        """
        if not result_fields:
            return result

        # 解析字段路径，按根字段分组
        # 如 ["styles.style_id", "styles.latest_category"] → {"styles": ["style_id", "latest_category"]}
        root_fields = {}
        for field_path in result_fields:
            parts = field_path.split(".")
            root = parts[0]
            sub_path = ".".join(parts[1:]) if len(parts) > 1 else None
            if root not in root_fields:
                root_fields[root] = []
            if sub_path:
                root_fields[root].append(sub_path)

        filtered = {}
        for root, sub_paths in root_fields.items():
            root_value = result.get(root)
            if root_value is None:
                continue

            if isinstance(root_value, list) and sub_paths:
                # 列表：过滤每个元素的字段
                filtered[root] = []
                for item in root_value:
                    if isinstance(item, dict):
                        filtered_item = self._filter_dict_fields(item, sub_paths)
                        if filtered_item:
                            filtered[root].append(filtered_item)
            elif isinstance(root_value, dict) and sub_paths:
                # 字典：递归过滤
                filtered[root] = self._filter_dict_fields(root_value, sub_paths)
            else:
                # 直接复制
                filtered[root] = root_value

        return filtered

    def _filter_dict_fields(self, data: dict, sub_paths: List[str]) -> dict:
        """从字典中过滤指定字段，支持嵌套路径"""
        if not sub_paths:
            return data

        # 按直接子字段分组
        direct_fields = {}
        nested_paths = {}

        for path in sub_paths:
            parts = path.split(".")
            direct = parts[0]
            rest = ".".join(parts[1:]) if len(parts) > 1 else None

            if direct not in direct_fields:
                direct_fields[direct] = []
            if rest:
                direct_fields[direct].append(rest)

        result = {}
        for field, nested in direct_fields.items():
            value = data.get(field)
            if value is None:
                continue

            if isinstance(value, list) and nested:
                # 列表嵌套
                result[field] = []
                for item in value:
                    if isinstance(item, dict):
                        filtered_item = self._filter_dict_fields(item, nested)
                        if filtered_item:
                            result[field].append(filtered_item)
            elif isinstance(value, dict) and nested:
                # 字典嵌套
                result[field] = self._filter_dict_fields(value, nested)
            else:
                # 叶子值
                result[field] = value

        return result

    # -----------------------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------------------

    def _get_default_person(self) -> str:
        """返回默认的高频人员作为'我'"""
        # 复用 kg_adapter 的逻辑或缓存
        candidates = ["Paula Cheng", "Iris Jiang", "Lisa Sun", "Sunny Padda"]
        best = None
        best_count = 0
        for p in candidates:
            r = kg_adapter.query_person_styles_with_stats(p)
            cnt = r.get("total_styles", 0)
            if cnt > best_count:
                best_count = cnt
                best = p
        return best or "Paula Cheng"
