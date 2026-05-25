#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试脚本：还原某款号的完整处理链路
用于排查用户投诉的时间线整理错误

用法：
    python debug_style.py <style_id>
    
示例：
    python debug_style.py AW25-KFWTS101
"""

import os
import sys
import json
import re
from collections import defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# 路径配置（根据实际部署调整）
# ---------------------------------------------------------------------------
EVENTS_FILE = os.path.join(os.path.dirname(__file__), "../email_rag_pipeline/output/events_passed.json")
KG_EMAIL_FILE = os.path.join(os.path.dirname(__file__), "../email_kg_pipeline/output/kg_email_detail.json")
LORA_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "../email_finetuning_pipeline/sft/output/timeline-reasoning-lora")

# ---------------------------------------------------------------------------
# 加载数据
# ---------------------------------------------------------------------------
def load_events(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_kg_emails(path: str):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 假设格式是 {style_id: [emails]}
    return data


# ---------------------------------------------------------------------------
# 事件提取与格式化
# ---------------------------------------------------------------------------
def get_events_for_style(events: list, style_id: str):
    """获取某款号的所有事件。"""
    return [e for e in events if e.get("style_id") == style_id]


def valid_date(d: str) -> bool:
    if not d or not isinstance(d, str):
        return False
    return bool(re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", d.strip()))


def sort_events(evts: list) -> list:
    def sort_key(e):
        d = e.get("date", "")
        return d if valid_date(d) else "9999-99-99"
    return sorted(evts, key=sort_key)


def format_event_line(idx: int, e: dict) -> str:
    cat = e.get("category", "其他")
    etype = e.get("event_type", "未知")
    date = e.get("date", "未明确")
    related = e.get("related_date", "")
    delay = e.get("delay_days") or 0
    party_from = e.get("party_from", "未知")
    party_to = e.get("party_to", "未知")
    desc = e.get("description", "").replace("\n", " ")

    delay_str = f" | 延期{delay}天" if delay else ""
    related_str = f" | 计划{related}" if related else ""
    return (
        f"[事件{idx}] {cat} | {etype} | {date}{related_str}{delay_str} | "
        f"{party_from} → {party_to} | {desc}"
    )


def build_prompt(style_id: str, evts: list) -> str:
    """构造给模型的输入 prompt（和训练时一致）。"""
    evts_sorted = sort_events(evts)
    event_lines = [format_event_line(i + 1, e) for i, e in enumerate(evts_sorted)]
    event_text = "\n".join(event_lines)
    return (
        f"款号: {style_id}\n\n"
        f"事件记录：\n{event_text}\n\n"
        f"请根据以上事件记录，整理成时间线表格并分析延期根因。"
    )


# ---------------------------------------------------------------------------
# 模型推理（加载 LoRA adapter）
# ---------------------------------------------------------------------------
def inference_with_lora(prompt: str) -> str:
    """
    使用微调后的 LoRA 模型进行推理。
    需要 transformers + peft 环境。
    """
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        import torch
    except ImportError:
        return "[错误] 未安装 transformers/peft，无法加载模型"

    base_model_name = "Qwen/Qwen2.5-7B-Instruct"
    adapter_path = LORA_OUTPUT_DIR

    if not os.path.exists(adapter_path):
        return f"[错误] 找不到 adapter 目录: {adapter_path}"

    print(f"  加载模型: {base_model_name}")
    print(f"  加载 adapter: {adapter_path}")

    tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()

    messages = [
        {"role": "system", "content": "你是服装行业业务分析师。请根据提供的事件记录，整理成结构化时间线表格并分析延期根因。输出必须使用 Markdown 表格。"},
        {"role": "user", "content": prompt},
    ]

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=2048,
            temperature=0.7,
            top_p=0.8,
        )

    response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
    return response


# ---------------------------------------------------------------------------
# 对比验证
# ---------------------------------------------------------------------------
def extract_events_from_markdown(output: str) -> list:
    """从模型输出的 Markdown 中提取事件信息（简化版）。"""
    # 提取表格行
    lines = output.split("\n")
    events = []
    for line in lines:
        if "|" in line and "阶段" not in line and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                events.append({
                    "category": parts[1] if len(parts) > 1 else "",
                    "event_type": parts[2] if len(parts) > 2 else "",
                    "date": parts[3] if len(parts) > 3 else "",
                })
    return events


def find_discrepancies(input_events: list, output: str) -> list:
    """对比输入事件和输出表格，找出差异。"""
    discrepancies = []
    output_events = extract_events_from_markdown(output)

    # 1. 检查遗漏
    input_keys = set()
    for e in input_events:
        key = f"{e.get('category','')}_{e.get('date','')}_{e.get('event_type','')}"
        input_keys.add(key)

    output_keys = set()
    for e in output_events:
        key = f"{e.get('category','')}_{e.get('date','')}_{e.get('event_type','')}"
        output_keys.add(key)

    missing = input_keys - output_keys
    hallucinated = output_keys - input_keys

    if missing:
        discrepancies.append(f"遗漏事件: {len(missing)} 个")
    if hallucinated:
        discrepancies.append(f"编造事件: {len(hallucinated)} 个")

    # 2. 检查时间顺序
    output_dates = [e.get("date", "") for e in output_events if e.get("date")]
    valid_dates = [d for d in output_dates if valid_date(d)]
    if valid_dates and valid_dates != sorted(valid_dates):
        discrepancies.append("时间顺序错误")

    return discrepancies


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def debug_style(style_id: str, run_inference: bool = False):
    print("=" * 70)
    print(f"调试款号: {style_id}")
    print("=" * 70)

    # 1. 加载数据
    print("\n[1/5] 加载事件数据...")
    all_events = load_events(EVENTS_FILE)
    style_events = get_events_for_style(all_events, style_id)
    print(f"  找到 {len(style_events)} 个事件")

    if not style_events:
        print(f"  [警告] 款号 {style_id} 在 events_passed.json 中无记录")
        return

    # 2. 显示原始事件
    print("\n[2/5] 事件列表（按时间排序）:")
    for i, e in enumerate(sort_events(style_events), 1):
        print(f"  {i}. [{e.get('category','?')}] {e.get('event_type','?')} | {e.get('date','?')} | {e.get('description','')[:50]}...")

    # 3. 构造 Prompt
    print("\n[3/5] 构造模型输入 Prompt...")
    prompt = build_prompt(style_id, style_events)
    print(f"  Prompt 长度: {len(prompt)} 字符")
    print(f"  前 300 字符:\n{prompt[:300]}...")

    # 4. 模型推理（可选）
    if run_inference:
        print("\n[4/5] 运行模型推理...")
        output = inference_with_lora(prompt)
    else:
        print("\n[4/5] 跳过模型推理（加 --infer 参数启用）")
        output = ""

    # 5. 对比验证
    if output:
        print("\n[5/5] 对比验证...")
        discrepancies = find_discrepancies(style_events, output)
        if discrepancies:
            print("  发现问题:")
            for d in discrepancies:
                print(f"    - {d}")
        else:
            print("  未发现明显差异")

        print("\n模型输出:\n")
        print(output[:1000])
        if len(output) > 1000:
            print("... (截断)")

    print("\n" + "=" * 70)
    print("调试完成")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python debug_style.py <style_id> [--infer]")
        print("示例: python debug_style.py AW25-KFWTS101")
        sys.exit(1)

    style_id = sys.argv[1]
    run_inference = "--infer" in sys.argv
    debug_style(style_id, run_inference)
