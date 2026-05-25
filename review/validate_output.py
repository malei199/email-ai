#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出验证脚本：自动检查模型生成的时间线输出是否符合规范

用法：
    python validate_output.py --style <style_id>          # 验证指定款号
    python validate_output.py --file <output.jsonl>       # 批量验证文件
    python validate_output.py --stdin                     # 从标准输入读取

返回：
    0 - 无错误
    1 - 发现错误（具体错误打印到 stderr）
"""

import os
import sys
import json
import re
import argparse
from collections import Counter

# ---------------------------------------------------------------------------
# 规则配置
# ---------------------------------------------------------------------------
VALID_CATEGORIES = ["面料", "样衣", "出货", "大货订单", "Lab Dip", "调纸样", "核料", "封样", "大货样", "一般沟通", "其他"]
REQUIRED_SECTIONS = ["时间线", "根因", "分析"]  # 输出中应包含的关键词
MAX_TABLE_ROW_LENGTH = 200  # 单行表格字符数上限


# ---------------------------------------------------------------------------
# 解析工具
# ---------------------------------------------------------------------------
def extract_markdown_tables(text: str) -> list:
    """从文本中提取所有 Markdown 表格。"""
    tables = []
    lines = text.split("\n")
    current_table = []
    in_table = False

    for line in lines:
        if "|" in line:
            current_table.append(line)
            in_table = True
        else:
            if in_table and current_table:
                tables.append(current_table)
                current_table = []
            in_table = False

    if current_table:
        tables.append(current_table)

    return tables


def parse_table_rows(table_lines: list) -> list:
    """解析表格行，返回结构化数据。"""
    rows = []
    for line in table_lines:
        # 跳过分隔行 |---|---|
        if re.match(r"^\s*\|[-:\s|]+\|\s*$", line):
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]  # 去掉空字符串
        if len(parts) >= 4 and parts[0] not in ["阶段", "类别", "Category"]:
            rows.append({
                "category": parts[0],
                "event_type": parts[1] if len(parts) > 1 else "",
                "date": parts[2] if len(parts) > 2 else "",
                "related_date": parts[3] if len(parts) > 3 else "",
                "delay": parts[4] if len(parts) > 4 else "",
                "party": parts[5] if len(parts) > 5 else "",
                "description": parts[6] if len(parts) > 6 else "",
            })
    return rows


def extract_dates_from_text(text: str) -> list:
    """提取文本中所有日期。"""
    pattern = r"(\d{4}[-/]\d{2}[-/]\d{2})"
    return re.findall(pattern, text)


def extract_delay_claims(text: str) -> list:
    """提取延期相关的结论性陈述。"""
    claims = []
    # 匹配类似 "延期主要集中在**面料**阶段" 的句子
    patterns = [
        r"延期主要集中在[\*\s]*([^\*\n]+)[\*\s]*阶段",
        r"([\*\s]*[^\*\n]+[\*\s]*)阶段出现延期",
        r"累计延期约\s*(\d+)\s*天",
        r"最大单次延期\s*(\d+)\s*天",
    ]
    for p in patterns:
        matches = re.findall(p, text)
        claims.extend(matches)
    return claims


# ---------------------------------------------------------------------------
# 验证规则
# ---------------------------------------------------------------------------
def check_table_structure(tables: list) -> list:
    """检查表格结构是否规范。"""
    errors = []
    if not tables:
        errors.append("未发现 Markdown 表格")
        return errors

    for i, table in enumerate(tables):
        rows = parse_table_rows(table)
        if not rows:
            errors.append(f"表格 {i+1}: 未解析到有效数据行")
            continue

        for j, row in enumerate(rows):
            # 检查 category 是否合法
            if row["category"] not in VALID_CATEGORIES:
                errors.append(f"表格 {i+1} 行 {j+1}: 未知类别 '{row['category']}'")

            # 检查日期格式
            if row["date"] and row["date"] != "-":
                if not re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", row["date"]):
                    errors.append(f"表格 {i+1} 行 {j+1}: 日期格式错误 '{row['date']}'")

            # 检查行长度
            row_text = "|".join(row.values())
            if len(row_text) > MAX_TABLE_ROW_LENGTH:
                errors.append(f"表格 {i+1} 行 {j+1}: 行过长 ({len(row_text)} 字符)")

    return errors


def check_temporal_consistency(input_events: list, output_text: str) -> list:
    """检查时间一致性。"""
    errors = []
    output_dates = extract_dates_from_text(output_text)
    input_dates = [e.get("date", "") for e in input_events if e.get("date")]

    # 检查输出中是否有输入中不存在的日期（可能的编造）
    for d in output_dates:
        normalized = d.replace("/", "-")
        if normalized not in [x.replace("/", "-") for x in input_dates]:
            # 放宽：允许计划日期
            if "计划" not in output_text or d not in output_text.split("计划")[0]:
                errors.append(f"输出中出现输入没有的日期: {d}")

    # 检查时间顺序
    valid_dates = [d for d in output_dates if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", d)]
    if valid_dates and valid_dates != sorted(valid_dates):
        errors.append("表格中日期未按时间顺序排列")

    return errors


def check_completeness(input_events: list, output_text: str) -> list:
    """检查是否有遗漏事件。"""
    errors = []
    # 简单检查：输入中的 category 是否都在输出中提及
    input_cats = set(e.get("category", "") for e in input_events)
    output_cats = set()

    tables = extract_markdown_tables(output_text)
    for table in tables:
        rows = parse_table_rows(table)
        for row in rows:
            output_cats.add(row["category"])

    missing_cats = input_cats - output_cats - {"", "其他"}
    if missing_cats:
        errors.append(f"输出未包含以下类别的事件: {', '.join(missing_cats)}")

    return errors


def check_hallucination(input_events: list, output_text: str) -> list:
    """检查是否有编造内容。"""
    errors = []
    # 提取输入中的关键描述词
    input_descriptions = " ".join([e.get("description", "") for e in input_events])

    # 检查延期归因是否有依据
    delay_claims = extract_delay_claims(output_text)
    for claim in delay_claims:
        if isinstance(claim, str) and claim.strip() not in input_descriptions:
            # 放宽：category 名称不算编造
            if claim.strip() not in VALID_CATEGORIES:
                errors.append(f"延期归因可能无直接依据: '{claim}'")

    return errors


def check_format_completeness(output_text: str) -> list:
    """检查输出格式完整性。"""
    errors = []

    # 检查是否包含必要章节
    has_timeline = any(kw in output_text for kw in ["时间线", "###"])
    has_conclusion = any(kw in output_text for kw in ["根因", "结论", "分析"])

    if not has_timeline:
        errors.append("输出缺少时间线/表格部分")
    if not has_conclusion:
        errors.append("输出缺少根因分析部分")

    # 检查 Markdown 表格格式
    tables = extract_markdown_tables(output_text)
    for table in tables:
        if len(table) < 3:  # 表头 + 分隔 + 至少一行数据
            errors.append("表格格式不完整（少于3行）")

    return errors


# ---------------------------------------------------------------------------
# 主验证函数
# ---------------------------------------------------------------------------
def validate(style_id: str = None, input_events: list = None, output_text: str = None) -> dict:
    """
    执行完整验证。
    
    参数:
        style_id: 款号（用于加载事件）
        input_events: 直接传入事件列表（优先）
        output_text: 模型输出文本
    
    返回:
        {"valid": bool, "errors": list, "warnings": list, "stats": dict}
    """
    errors = []
    warnings = []
    stats = {}

    # 加载输入事件
    if input_events is None and style_id:
        events_file = os.path.join(os.path.dirname(__file__), "../email_rag_pipeline/output/events_passed.json")
        if os.path.exists(events_file):
            with open(events_file, "r", encoding="utf-8") as f:
                all_events = json.load(f)
            input_events = [e for e in all_events if e.get("style_id") == style_id]
        else:
            warnings.append(f"找不到事件文件: {events_file}")
            input_events = []

    if input_events is None:
        input_events = []

    stats["input_events"] = len(input_events)
    stats["output_length"] = len(output_text) if output_text else 0

    if not output_text:
        errors.append("输出为空")
        return {"valid": False, "errors": errors, "warnings": warnings, "stats": stats}

    # 执行各项检查
    tables = extract_markdown_tables(output_text)
    stats["table_count"] = len(tables)
    stats["total_table_rows"] = sum(len(parse_table_rows(t)) for t in tables)

    errors.extend(check_format_completeness(output_text))
    errors.extend(check_table_structure(tables))

    if input_events:
        errors.extend(check_temporal_consistency(input_events, output_text))
        errors.extend(check_completeness(input_events, output_text))
        errors.extend(check_hallucination(input_events, output_text))
    else:
        warnings.append("无输入事件，跳过事件一致性检查")

    # 去重
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="验证时间线模型输出")
    parser.add_argument("--style", help="指定款号进行验证")
    parser.add_argument("--file", help="批量验证 JSONL 文件（每行含 style_id 和 output）")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取输出文本")
    parser.add_argument("--events-file", default=None, help="事件文件路径")
    args = parser.parse_args()

    if args.style:
        # 需要同时提供输出文本
        print(f"验证款号: {args.style}")
        print("请粘贴模型输出文本（Ctrl+D 结束）:")
        output_text = sys.stdin.read()
        result = validate(style_id=args.style, output_text=output_text)

    elif args.file:
        print(f"批量验证文件: {args.file}")
        total = 0
        failed = 0
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    style_id = data.get("style_id", "unknown")
                    output_text = data.get("output", data.get("messages", [{}]*3)[2].get("content", ""))
                    input_events = data.get("input_events", None)

                    result = validate(style_id=style_id, input_events=input_events, output_text=output_text)
                    total += 1
                    if not result["valid"]:
                        failed += 1
                        print(f"\n[FAIL] {style_id}:")
                        for e in result["errors"]:
                            print(f"  ERROR: {e}")
                    for w in result["warnings"]:
                        print(f"  WARN: {w}")
                except Exception as e:
                    print(f"[SKIP] 解析失败: {e}")

        print(f"\n{'='*50}")
        print(f"总计: {total}, 通过: {total - failed}, 失败: {failed}")
        sys.exit(0 if failed == 0 else 1)

    elif args.stdin:
        print("从标准输入读取...")
        output_text = sys.stdin.read()
        result = validate(output_text=output_text)

    else:
        parser.print_help()
        sys.exit(1)

    # 打印结果
    print("\n" + "=" * 50)
    print(f"验证结果: {'✅ 通过' if result['valid'] else '❌ 失败'}")
    print("=" * 50)

    if result["errors"]:
        print(f"\n错误 ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"  ❌ {e}")

    if result["warnings"]:
        print(f"\n警告 ({len(result['warnings'])}):")
        for w in result["warnings"]:
            print(f"  ⚠️  {w}")

    print(f"\n统计:")
    for k, v in result["stats"].items():
        print(f"  {k}: {v}")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
