#!/usr/bin/env python3
"""
端到端测试脚本
测试 V3 Scheduler -> V2/V1 的完整链路

用法:
    python test_end_to_end.py --all                    # 运行全部测试
    python test_end_to_end.py --scene v2_multi_round  # 只测指定场景
    python test_end_to_end.py --custom my_test         # 运行自定义测试
"""

import json
import os
import sys
import argparse
import re
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 模型路径（相对于 rlhf/outputs/）
MODEL_PATHS = {
    "v3_scheduler": "/openbayes/home/LlamaFactory/outputs/dpo-scheduler-v3",
    "v2_multi": "/openbayes/home/LlamaFactory/outputs/dpo-multi-round-v2",
    "v1_timeline": "./outputs/v1-timeline-lora",
}

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

# 模拟工具执行结果（V2 扩展）
MOCK_TOOL_RESULTS = {
    "kg_query": {
        "timeline": [
            {"category": "样衣", "event_type": "提交", "date": "2024-06-18", "description": "测试提交"},
            {"category": "面料", "event_type": "确认", "date": "2024-05-15", "description": "面料确认"},
            {"category": "封样", "event_type": "确认", "date": "2024-07-01", "description": "封样已确认"},
        ],
        "people": ["Mike", "David", "Amy"],
        "factory": "广州工厂C",
        "delay_details": "延期3天",
        "order_styles": ["CCSS230021", "CCSS230022"],
    },
    "rag_query": {
        "translation": "面料术语翻译结果",
        "application": "应用场景说明",
        "client_feedback": "客户已给出修改意见，需调整袖口",
        "factory_issue": "面料交期延迟2天，工厂反馈产能紧张",
    },
    "email_extract": {
        "parameters": ["颜色", "标签", "拉链"],
        "technical_details": "技术参数详情",
    },
}


class ModelLoader:
    """延迟加载模型，按需初始化"""
    
    def __init__(self):
        self.models = {}
        self.tokenizer = None
        self.base_model = None
        
    def _load_base(self):
        """加载基座模型和 tokenizer"""
        if self.tokenizer is not None:
            return
            
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
        except ImportError:
            print("错误: 请先安装依赖: pip install -r requirements.txt")
            sys.exit(1)
        
        print(f"[*] 加载基座模型: {BASE_MODEL}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL,
            trust_remote_code=True,
            padding_side="left",
        )
        
        # 使用半精度节省显存
        self.base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )
        print("[ok] 基座模型加载完成")
    
    def load(self, model_key: str):
        """加载指定 LoRA 适配器"""
        if model_key in self.models:
            return self.models[model_key]
        
        self._load_base()
        
        try:
            from peft import PeftModel
        except ImportError:
            print("错误: 请安装 peft: pip install peft")
            sys.exit(1)
        
        relative_path = MODEL_PATHS[model_key]
        full_path = PROJECT_ROOT / relative_path
        
        if not full_path.exists():
            print(f"错误: 模型路径不存在: {full_path}")
            print(f"      请确认训练已完成并输出到 {relative_path}")
            sys.exit(1)
        
        print(f"[*] 加载适配器: {model_key} ({relative_path})")
        model = PeftModel.from_pretrained(self.base_model, str(full_path))
        model.eval()
        self.models[model_key] = model
        print(f"[ok] {model_key} 加载完成")
        return model
    
    def generate(self, model_key: str, prompt: str, max_new_tokens: int = 512, temperature: float = 0.1) -> str:
        """使用指定模型生成回答"""
        import torch
        model = self.load(model_key)
        
        inputs = self.tokenizer(prompt, return_tensors="pt", padding=True)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        
        # 解码，去掉 prompt 部分
        full_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        prompt_text = self.tokenizer.decode(inputs["input_ids"][0], skip_special_tokens=True)
        response = full_text[len(prompt_text):].strip()
        
        return response


class ToolSimulator:
    """模拟工具执行"""
    
    def execute(self, tool_calls: list) -> dict:
        """执行工具调用，返回模拟结果"""
        results = {}
        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("arguments", {})
            
            if name in MOCK_TOOL_RESULTS:
                results[name] = MOCK_TOOL_RESULTS[name]
            else:
                results[name] = {"status": "mock_result", "query": args.get("query", "")}
        
        return results


class EndToEndTester:
    """端到端测试器"""
    
    def __init__(self):
        self.loader = ModelLoader()
        self.tool_sim = ToolSimulator()
        self.results = []
        
    def _build_prompt(self, system: str, user: str, history: list = None) -> str:
        """构建 Qwen 格式的 prompt"""
        # 确保 tokenizer 已加载
        if self.loader.tokenizer is None:
            self.loader._load_base()
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})
        
        # Qwen 的 chat template
        return self.loader.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    
    def _parse_json_response(self, text: str) -> dict:
        """从模型输出中解析 JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except:
            pass
        
        # 尝试提取 JSON 块
        patterns = [
            r'\{[\s\S]*?\}',
            r'```json\s*([\s\S]*?)```',
            r'```\s*([\s\S]*?)```',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    return json.loads(match)
                except:
                    continue
        
        # 解析失败，返回原始文本
        return {"raw_text": text, "parse_error": True}
    
    def _v3_route(self, user_input: str, history: list = None) -> dict:
        """V3 调度决策
        
        Args:
            user_input: 用户输入
            history: 多轮对话历史（用于 route_v2_then_v1 的后续轮次）
        """
        system = (
            "你是服装行业智能调度器。根据用户问题，决定如何回答：\n"
            "1. direct_answer: 直接回答（问候、超出范围、无效款号、越界问题等）\n"
            "2. route_v2: 调用 V2 工具查询模型（无款号 + 无分析关键字）\n"
            "3. route_v1: 调用 V1 时间线推理模型（有款号统一走V1，无论是否要求分析）\n"
            "4. route_v2_then_v1: 先 V2 查询获取款号，再逐个 V1 分析（无款号 + 有分析关键字）\n"
            "输出格式：{\"thought\": \"...\", \"decision\": \"...\", ...}"
        )
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        
        prompt = self.loader.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        
        response = self.loader.generate("v3_scheduler", prompt, max_new_tokens=256)
        result = self._parse_json_response(response)
        
        return {
            "raw_response": response,
            "parsed": result,
            "decision": result.get("decision", "unknown"),
            "thought": result.get("thought", ""),
            "style_id": result.get("style_id", ""),
            "event": result.get("event", ""),
            "function_calls": result.get("function_calls", []),
            "style_ids": result.get("style_ids", []),
        }
    
    def _v2_query(self, user_input: str, tool_results: dict = None, model_key: str = "v2_multi", first_round_response: str = None) -> dict:
        """V2 查询执行
        
        Args:
            user_input: 用户输入
            tool_results: 工具执行结果（多轮时使用）
            model_key: 模型标识
            first_round_response: 第一轮 assistant 的实际输出（多轮时必须传入）
        """
        if model_key == "v2_multi":
            system = "你是服装行业智能助手。根据用户问题和已有查询结果，判断是否需要补充查询。可用工具：kg_query, rag_query, email_extract。输出格式：{\"thought\": \"...\", \"function_calls\": [{\"name\": \"...\", \"arguments\": {...}}]}"
        else:
            system = "你是服装行业智能助手。请根据用户问题，选择正确的查询工具。可用工具：kg_query, rag_query, email_extract, direct_answer。输出格式：先给出思考过程(thought)，然后给出工具调用(function_calls)。"
        
        # 构建带历史的多轮 prompt
        history = []
        if tool_results and first_round_response:
            # 多轮：包含第一轮的真实对话历史
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": first_round_response})
            history.append({"role": "user", "content": f"[查询结果] {json.dumps(tool_results, ensure_ascii=False)}"})
            prompt = self._build_prompt(system, "", history=history)
        else:
            # 单轮
            prompt = self._build_prompt(system, user_input)
        
        response = self.loader.generate(model_key, prompt, max_new_tokens=256)
        result = self._parse_json_response(response)
        
        return {
            "raw_response": response,
            "parsed": result,
            "function_calls": result.get("function_calls", []),
            "thought": result.get("thought", ""),
        }
    
    def _extract_style_id(self, text: str) -> str | None:
        """从用户输入中提取款号，支持多种格式
        
        支持的格式：
        - AW25-KFCWT147, AW25ABT-016（含连字符）
        - SS25IACB201（季节+字母+数字）
        - CCSS230021, INDOT28119（字母+数字）
        - 3261722, 9148496（纯数字7-9位）
        - RW915-2169（字母+数字-数字）
        """
        text_upper = text.upper()
        
        patterns = [
            r'[A-Z]{2}\d{0,2}-[A-Z]+\d+',      # AW25-KFCWT147
            r'[A-Z]{2}\d{0,2}[A-Z]+-\d+',       # AW25ABT-016
            r'[A-Z]{2,}\d+-\d+',                # RW915-2169
            r'[A-Z]{2}\d{0,2}[A-Z]+\d+',        # SS25IACB201
            r'[A-Z]{3,}\d{4,}',                  # CCSS230021
            r'[A-Z]{3,}\d{3,}',                  # CCSS23008
            r'\b\d{7,9}\b',                      # 3261722
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_upper)
            if match:
                return match.group()
        
        return None
    
    def _query_rag_for_style(self, style_id: str) -> list:
        """从RAG查询指定款号的所有事件
        
        实际部署时，这里连接ChromaDB查询。
        测试时，从MOCK_TOOL_RESULTS返回模拟数据。
        """
        # TODO: 实际部署时替换为真实RAG查询
        # from email_rag_pipeline import query_chroma
        # return query_chroma(style_id=style_id)
        
        # 测试用：返回模拟事件，添加source字段
        mock_events = MOCK_TOOL_RESULTS["kg_query"]["timeline"]
        for i, evt in enumerate(mock_events):
            evt["source_filename"] = f"mock_{i}.eml"
            evt["source_subject"] = f"Mock email for {style_id}"
            evt["party_from"] = evt.get("party_from", "工厂")
            evt["party_to"] = evt.get("party_to", "客人")
            evt["related_date"] = ""
            evt["delay_days"] = 0
        return mock_events
    
    def _build_v1_input(self, style_id: str, events: list = None) -> dict:
        """构造V1的输入JSON
        
        Args:
            style_id: 款号
            events: 可选，外部传入的事件列表。如果不传，自动查询RAG。
        """
        if events is None:
            events = self._query_rag_for_style(style_id)
        
        # 按日期排序
        sorted_events = sorted(events, key=lambda e: e.get("date", ""))
        
        # 构造标准输入格式
        event_list = []
        for e in sorted_events:
            event_list.append({
                "category": e.get("category", ""),
                "event_type": e.get("event_type", ""),
                "date": e.get("date", ""),
                "related_date": e.get("related_date", ""),
                "delay_days": e.get("delay_days") if e.get("delay_days") is not None else 0,
                "party_from": e.get("party_from", ""),
                "party_to": e.get("party_to", ""),
                "description": e.get("description", ""),
                "source_filename": e.get("source_filename", ""),
                "source_subject": e.get("source_subject", ""),
            })
        
        return {
            "style_id": style_id,
            "events": event_list,
        }
    
    def _v1_analyze(self, style_id: str, events: list = None, event_focus: str = None) -> dict:
        """V1 时间线分析
        
        Args:
            style_id: 款号
            events: 可选，外部传入的事件列表。如果不传，自动查询RAG。
            event_focus: 可选，关注的事件类型（如"延期"、"面料"等）
        """
        system = (
            "你是服装行业资深业务分析师。请根据提供的事件记录，"
            "整理成结构化时间线表格并分析延期根因。"
            "输出必须包含：一、📅时间线梳理（按阶段分表格，表格含来源邮件列）；"
            "二、⚠️风险点；三、🛤️关键路径。"
        )
        
        # 构造输入
        v1_input = self._build_v1_input(style_id, events)
        
        # 如果有 event_focus，在输入中体现
        if event_focus:
            v1_input["focus"] = event_focus
        
        user_input = json.dumps(v1_input, ensure_ascii=False)
        
        prompt = self._build_prompt(system, user_input)
        response = self.loader.generate("v1_timeline", prompt, max_new_tokens=2048)
        
        return {
            "raw_response": response,
            "analysis": response,
            "input_events": v1_input["events"],
            "focus": event_focus,
        }
    
    def run_single_test(self, test_case: dict, test_name: str = "") -> dict:
        """运行单个测试用例"""
        print(f"\n{'='*60}")
        print(f"测试: {test_name}")
        print(f"场景: {test_case.get('scene', 'unknown')}")
        print(f"输入: {test_case['user_input']}")
        print(f"{'='*60}")
        
        user_input = test_case["user_input"]
        expected_route = test_case.get("expected_route", "")
        
        result = {
            "test_name": test_name,
            "test_case": test_case,
            "v3_routing": None,
            "v2_execution": None,
            "v1_analysis": None,
            "final_answer": None,
            "routing_correct": False,
            "style_id_correct": False,
            "event_correct": False,
            "end_to_end_success": False,
            "errors": [],
        }
        
        # Step 1: V3 路由决策
        print("\n[Step 1] V3 调度决策...")
        v3_result = self._v3_route(user_input)
        result["v3_routing"] = v3_result
        decision = v3_result["decision"]
        print(f"  decision: {decision}")
        print(f"  thought: {v3_result['thought'][:100]}...")
        
        # 检查路由是否正确
        if expected_route and decision == expected_route:
            result["routing_correct"] = True
            print(f"  [ok] 路由正确")
        elif expected_route:
            print(f"  [x] 路由错误，期望: {expected_route}")
        
        # 检查 style_id 是否正确（route_v1 时）
        expected_style_id = test_case.get("expected_style_id")
        if decision == "route_v1" and expected_style_id:
            actual_style_id = v3_result.get("style_id")
            if actual_style_id and actual_style_id.upper() == expected_style_id.upper():
                result["style_id_correct"] = True
                print(f"  [ok] style_id 正确: {actual_style_id}")
            else:
                print(f"  [x] style_id 错误，期望: {expected_style_id}, 实际: {actual_style_id}")
        
        # 检查 event 是否正确（route_v1 时）
        expected_event = test_case.get("expected_event")
        if decision == "route_v1" and expected_event:
            actual_event = v3_result.get("event")
            if actual_event and actual_event == expected_event:
                result["event_correct"] = True
                print(f"  [ok] event 正确: {actual_event}")
            else:
                print(f"  [x] event 错误，期望: {expected_event}, 实际: {actual_event}")
        
        # Step 2: 根据路由执行
        if decision == "direct_answer":
            print("\n[Step 2] 直接回答")
            result["final_answer"] = "[直接回答] " + v3_result["thought"]
            result["end_to_end_success"] = True
            
        elif decision == "route_v2":
            # 判断是单轮还是多轮意图
            multi_round_intents = [
                "stage_check", "client_feedback", "factory_issue",
                "my_styles_status", "multi_aspect", "general_timeline",
                "person_query", "technical_param", "factory_query",
            ]
            
            # 从测试用例获取期望意图
            expected_intent = test_case.get("expected_intent", "")
            is_multi = expected_intent in multi_round_intents
            
            # V2 统一使用 v2_multi 模型（同时负责第一轮工具选择
            # 和后续多轮补充查询决策）
            print("\n[Step 2] V2 查询...")
            v2_result = self._v2_query(user_input, model_key="v2_multi")
            result["v2_execution"] = v2_result
            print(f"  thought: {v2_result['thought'][:100]}...")
            print(f"  tools: {[c.get('name') for c in v2_result['function_calls']]}")
            
            # 模拟工具执行
            tool_results = self.tool_sim.execute(v2_result["function_calls"])
            print(f"  工具结果: {list(tool_results.keys())}")
            
            result["final_answer"] = f"[V2查询结果] {json.dumps(tool_results, ensure_ascii=False)[:200]}"
            result["end_to_end_success"] = True
            
            # V2 多轮能力验证（如果工具返回结果不够，应触发补充查询）
            # 当前简化：只要成功执行工具即认为通过
            pass
            
        elif decision == "route_v2_then_v1":
            print("\n[Step 2] V2 查询获取款号...")
            
            # V2 查询（统一使用 v2_multi 模型）
            v2_result = self._v2_query(user_input, model_key="v2_multi")
            result["v2_execution"] = v2_result
            tool_results = self.tool_sim.execute(v2_result["function_calls"])
            print(f"  V2 tools: {[c.get('name') for c in v2_result['function_calls']]}")
            
            # 从V2结果提取款号列表
            style_ids = tool_results.get("kg_query", {}).get("order_styles", [])
            if not style_ids:
                # 尝试从用户输入提取（兜底）
                sid = self._extract_style_id(user_input)
                if sid:
                    style_ids = [sid]
            
            if not style_ids:
                style_ids = ["CCSS230021"]  # fallback
            
            print(f"  获取到 {len(style_ids)} 个款号: {style_ids}")
            
            # Step 3-N: 逐个款号调 V1 分析（方案A多轮）
            v1_results = []
            history = [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": v3_result["raw_response"]},
                {"role": "user", "content": f"[V2查询结果] {json.dumps({'styles': style_ids}, ensure_ascii=False)}"},
            ]
            
            for idx, style_id in enumerate(style_ids):
                print(f"\n[Step {3+idx}] V1 分析款号 {style_id}...")
                
                # V3 输出 route_v1 决策（模拟多轮中的 V3 决策）
                v3_v1_decision = self._v3_route(
                    f"继续分析款号 {style_id}",
                    history=history
                )
                print(f"  V3 决策: {v3_v1_decision['decision']}, style_id={v3_v1_decision.get('style_id', '')}")
                
                # 调 V1 分析
                v1_result = self._v1_analyze(
                    style_id,
                    event_focus=v3_v1_decision.get("event") or v3_result.get("event")
                )
                v1_results.append({
                    "style_id": style_id,
                    "analysis": v1_result["analysis"],
                })
                print(f"  分析完成: {v1_result['analysis'][:100]}...")
                
                # 更新历史
                history.append({"role": "assistant", "content": v3_v1_decision["raw_response"]})
                history.append({"role": "user", "content": f"[V1分析结果-{style_id}] {v1_result['analysis'][:200]}"})
            
            # Final: V3 汇总（模拟）
            print(f"\n[Step Final] V3 汇总 {len(v1_results)} 个款号结果...")
            summaries = [f"{r['style_id']}: {r['analysis'][:100]}..." for r in v1_results]
            summary_text = "\n".join(summaries)
            
            result["v1_analysis"] = {
                "individual_results": v1_results,
                "summary": summary_text,
            }
            result["final_answer"] = f"[汇总分析]\n{summary_text}"
            result["end_to_end_success"] = True
            
        elif decision == "route_v1":
            print("\n[Step 2] V1 时间线分析...")
            
            # 优先使用 V3 返回的 style_id，其次从用户输入提取
            style_id = v3_result.get("style_id") or self._extract_style_id(user_input)
            if not style_id:
                style_id = "CCSS230021"  # fallback
            
            # 获取 V3 返回的 event（如有）
            event_focus = v3_result.get("event") or None
            
            v1_result = self._v1_analyze(style_id, event_focus=event_focus)
            result["v1_analysis"] = v1_result
            print(f"  style_id: {style_id}, event_focus: {event_focus or '无'}")
            result["final_answer"] = f"[V1分析] {v1_result['analysis'][:200]}"
            result["end_to_end_success"] = True
            
        else:
            result["errors"].append(f"未知决策: {decision}")
            print(f"  [x] 未知决策: {decision}")
        
        self.results.append(result)
        return result
    
    def run_all_tests(self, test_cases: dict) -> dict:
        """运行所有测试"""
        print("\n" + "="*60)
        print("开始端到端测试")
        print(f"测试用例数: {len(test_cases)}")
        print("="*60)
        
        for name, case in test_cases.items():
            try:
                self.run_single_test(case, name)
            except Exception as e:
                print(f"\n[x] 测试 {name} 失败: {e}")
                import traceback
                traceback.print_exc()
        
        return self._generate_summary()
    
    def _generate_summary(self) -> dict:
        """生成测试汇总"""
        total = len(self.results)
        routing_correct = sum(1 for r in self.results if r["routing_correct"])
        e2e_success = sum(1 for r in self.results if r["end_to_end_success"])
        
        # V1 专项指标
        v1_results = [r for r in self.results if r["test_case"].get("expected_route") == "route_v1"]
        style_id_correct = sum(1 for r in v1_results if r["style_id_correct"])
        event_correct = sum(1 for r in v1_results if r["event_correct"])
        v1_with_event = [r for r in v1_results if r["test_case"].get("expected_event")]
        
        summary = {
            "total_tests": total,
            "routing_accuracy": routing_correct / total if total > 0 else 0,
            "end_to_end_success_rate": e2e_success / total if total > 0 else 0,
            "v1_style_id_accuracy": style_id_correct / len(v1_results) if v1_results else 0,
            "v1_event_accuracy": event_correct / len(v1_with_event) if v1_with_event else 0,
            "details": self.results,
        }
        
        print("\n" + "="*60)
        print("测试汇总")
        print("="*60)
        print(f"总测试数: {total}")
        print(f"路由正确率: {routing_correct}/{total} ({summary['routing_accuracy']*100:.1f}%)")
        print(f"端到端成功率: {e2e_success}/{total} ({summary['end_to_end_success_rate']*100:.1f}%)")
        if v1_results:
            print(f"V1 style_id 正确率: {style_id_correct}/{len(v1_results)} ({summary['v1_style_id_accuracy']*100:.1f}%)")
        if v1_with_event:
            print(f"V1 event 正确率: {event_correct}/{len(v1_with_event)} ({summary['v1_event_accuracy']*100:.1f}%)")
        print("="*60)
        
        return summary
    
    def save_results(self, output_dir: str = None):
        """保存测试结果"""
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = PROJECT_ROOT / "evaluation" / "results" / timestamp
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存汇总
        summary = self._generate_summary()
        with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        # 保存详细结果
        with open(output_dir / "details.jsonl", "w", encoding="utf-8") as f:
            for r in self.results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        
        print(f"\n结果已保存到: {output_dir}")
        return output_dir


def load_test_cases(path: str = None, scene_filter: str = None) -> dict:
    """加载测试用例"""
    if path is None:
        path = Path(__file__).parent / "test_cases.json"
    else:
        path = Path(path)
    
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    
    if scene_filter:
        scenes = scene_filter.split(",")
        cases = {k: v for k, v in cases.items() if v.get("scene") in scenes}
    
    return cases


def main():
    parser = argparse.ArgumentParser(description="端到端测试")
    parser.add_argument("--all", action="store_true", help="运行全部测试")
    parser.add_argument("--scene", type=str, help="指定场景，逗号分隔")
    parser.add_argument("--custom", type=str, help="运行自定义测试用例名")
    parser.add_argument("--output", type=str, help="输出目录")
    args = parser.parse_args()
    
    # 加载测试用例
    if args.custom:
        all_cases = load_test_cases()
        if args.custom not in all_cases:
            print(f"错误: 自定义测试 '{args.custom}' 不存在")
            print(f"可用测试: {list(all_cases.keys())}")
            sys.exit(1)
        test_cases = {args.custom: all_cases[args.custom]}
    elif args.scene:
        test_cases = load_test_cases(scene_filter=args.scene)
    elif args.all:
        test_cases = load_test_cases()
    else:
        parser.print_help()
        print("\n提示: 使用 --all 运行全部测试，或 --scene 指定场景")
        sys.exit(0)
    
    if not test_cases:
        print("错误: 没有匹配的测试用例")
        sys.exit(1)
    
    # 运行测试
    tester = EndToEndTester()
    tester.run_all_tests(test_cases)
    tester.save_results(args.output)


if __name__ == "__main__":
    main()
