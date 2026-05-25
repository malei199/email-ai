#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build V1 timeline analysis fine-tuning dataset.

V1 时间线分析训练数据构造脚本

输入:
  - email_rag_pipeline/output/events_passed.json (事件数据)

输出:
  - email_finetuning_pipeline/datasets/v1/sft_v1_timeline.jsonl
  - email_finetuning_pipeline/datasets/val/val_v1_timeline.jsonl
  - email_finetuning_pipeline/datasets/v1/v1_stats.json

核心逻辑:
  1. 加载事件数据，按款号分组
  2. 过滤: 只保留>=2事件的款号
  3. 分层: rich(>=10) / medium(5-9) / poor(2-4)
  4. 采样: 训练集分层，验证集用poor
  5. 调用DeepSeek生成输出(10并发)
  6. 质量检查
  7. 保存sharegpt格式

使用:
    python build_v1_timeline_dataset.py
    python build_v1_timeline_dataset.py --train-target 500 --val-target 50
"""

import os
import sys
import json
import re
import argparse
import random
import time
from collections import defaultdict, Counter
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# DeepSeek API
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EVENTS_FILE = os.path.join(_SCRIPT_DIR, "../../email_rag_pipeline/output/events_passed.json")
DEFAULT_OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "../datasets")

DEEPSEEK_API_KEY = 'sk-c056cef347f84bef95c4601c88ffc1f8'
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
DEEPSEEK_MODEL = 'deepseek-chat'
MAX_WORKERS = 50
REQUEST_TIMEOUT = 120
MAX_RETRIES = 3
RETRY_DELAY = 2

# 分层比例
LAYER_DISTRIBUTION = {
    "rich": 0.50,    # >=10事件
    "medium": 0.35,  # 5-9事件
    "poor": 0.15,    # 2-4事件
}

SYSTEM_PROMPT_V1 = (
    "你是服装行业资深业务分析师，有20年跟单经验。"
    "请根据提供的事件记录，整理成结构化时间线并分析延期根因。"
    "\n\n要求："
    "\n1. 按阶段分表格（面料/样衣/封样/大货/出货等）"
    "\n2. 表格列：阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件"
    "\n3. 事件前加图标（提交📤/确认✅/给意见💬/修改🔧/出货🚚/延期申请⏰）"
    "\n4. 阶段前加图标（面料🧵/样衣👔/出货🚚/封样📦/Lab Dip🧪/调纸样📐/大货样🎽/其他📋）"
    "\n5. 列出风险点（高风险🔴/中风险🟡/低风险🟢）"
    "\n6. 梳理关键路径（阶段→阶段→...）"
    "\n7. 描述简化，去掉\"款号XXX的\"重复前缀"
    "\n8. 如果某阶段无记录，明确标注\"未找到记录\""
    "\n9. 不要编造不存在的事件"
)

CATEGORY_ICONS = {
    "面料": "🧵",
    "样衣": "👔",
    "出货": "🚚",
    "封样": "📦",
    "Lab Dip": "🧪",
    "调纸样": "📐",
    "大货样": "🎽",
    "大货订单": "📋",
    "船样": "🚢",
    "验货": "🔍",
    "其他": "📋",
}

EVENT_TYPE_ICONS = {
    "提交": "📤",
    "确认": "✅",
    "给意见": "💬",
    "修改": "🔧",
    "出货": "🚚",
    "延期申请": "⏰",
    "打样": "🧵",
    "完成": "✅",
    "回传": "📤",
    "批复": "✅",
    "等待反馈": "⏳",
    "其他": "📋",
}


def get_deepseek_client():
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def load_events(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def group_by_style(events: list) -> dict:
    """按款号分组事件"""
    style_events = defaultdict(list)
    for e in events:
        sid = e.get("style_id", "")
        if sid and sid != "UNKNOWN":
            style_events[sid].append(e)
    return dict(style_events)


def classify_layer(event_count: int) -> str:
    if event_count >= 10:
        return "rich"
    elif event_count >= 5:
        return "medium"
    elif event_count >= 2:
        return "poor"
    return "single"


def build_input_json(style_id: str, events: list) -> dict:
    """构造V1输入JSON"""
    # 按日期排序
    sorted_events = sorted(events, key=lambda e: e.get("date", ""))
    
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


def build_deepseek_prompt(input_json: dict) -> str:
    """构造DeepSeek生成prompt"""
    return f"""请根据以下事件记录，整理成结构化时间线并分析延期根因。

{json.dumps(input_json, ensure_ascii=False, indent=2)}

输出格式要求：
## 📋 款号 {{style_id}} 时间线分析

### 一、📅 时间线梳理

#### 1. {{阶段图标}} {{阶段名}}
| 阶段 | 事件 | 时间 | 延期 | 描述 | 来源邮件 |
|------|------|------|------|------|----------|
| {{category}} | {{图标}}{{event_type}} | {{date}} | {{delay}} | {{简化描述}} | 📧 {{filename}} |
...

### 二、⚠️ 风险点
- {{风险等级图标}} **{{风险标题}}**：{{风险描述}}
...

### 三、🛤️ 关键路径
{{阶段图标}} {{阶段}}({{date}}) → {{阶段图标}} {{阶段}}({{date}}) → ...

注意：
1. 描述要简化，去掉重复前缀
2. 如果某阶段无记录，标注\"未找到记录\"
3. 不要编造不存在的事件
4. 风险点要具体，有据可依
"""


def clean_output_prefix(output: str) -> str:
    """清理DeepSeek输出的前缀废话"""
    # 找到第一个 ## 标题的位置
    match = re.search(r'##\s+📋', output)
    if match:
        return output[match.start():].strip()
    # 如果没有找到，尝试找第一个 #
    match = re.search(r'#\s+', output)
    if match:
        return output[match.start():].strip()
    return output.strip()


def generate_with_deepseek(client: OpenAI, input_json: dict, seed: int = 42) -> str:
    """调用DeepSeek生成输出
    
    根据事件数量动态调整max_tokens，避免大事件量样本输出被截断。
    """
    prompt = build_deepseek_prompt(input_json)
    event_count = len(input_json.get("events", []))
    
    # 动态计算所需token：基础800 + 每个事件约60 token
    needed_tokens = 800 + event_count * 60
    # 上限8192（DeepSeek-V3支持），下限2048
    max_tokens = min(max(needed_tokens, 2048), 8192)
    
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_V1},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
                timeout=REQUEST_TIMEOUT,
            )
            raw_output = response.choices[0].message.content.strip()
            return clean_output_prefix(raw_output)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                print(f"  [错误] DeepSeek API 调用失败: {e}")
                return ""
    return ""


def build_sharegpt_record(style_id: str, input_json: dict, output: str) -> dict:
    """构造sharegpt格式训练样本"""
    return {
        "style_id": style_id,
        "event_count": len(input_json["events"]),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_V1},
            {"role": "user", "content": json.dumps(input_json, ensure_ascii=False)},
            {"role": "assistant", "content": output},
        ],
    }


def quality_check(record: dict) -> dict:
    """质量检查"""
    output = record.get("messages", [])[2].get("content", "") if len(record.get("messages", [])) > 2 else ""
    
    checks = {
        "has_title": "## 📋" in output,
        "has_timeline": "### 一、📅" in output or "### 一、" in output,
        "has_risks": "### 二、⚠️" in output or "### 二、" in output,
        "has_path": "### 三、🛤️" in output or "### 三、" in output,
        "has_table": "| 阶段 |" in output,
        "has_source": "📧" in output,
        "has_icons": any(icon in output for icon in ["🧵", "👔", "🚚", "🔴", "🟡", "🟢"]),
        "output_length": len(output),
    }
    checks["passed"] = all([
        checks["has_title"],
        checks["has_timeline"],
        checks["has_risks"],
        checks["has_path"],
        checks["has_table"],
    ])
    return checks


def _print_progress_bar(current: int, total: int, prefix: str = "", suffix: str = "", bar_length: int = 40):
    """打印进度条"""
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


def _process_batch_with_progress(
    client: OpenAI,
    samples: list,
    label: str,
    max_workers: int = MAX_WORKERS,
) -> list:
    """批量处理样本并显示进度条"""
    total = len(samples)
    completed = 0
    success = 0
    failed = 0
    results = []
    lock = {"completed": 0, "success": 0, "failed": 0}  # 简单计数器
    
    def process_one(sid, evs):
        input_json = build_input_json(sid, evs)
        output = generate_with_deepseek(client, input_json)
        if not output:
            return None
        record = build_sharegpt_record(sid, input_json, output)
        return record
    
    print(f"  开始处理 {label}，共 {total} 条，并发数 {max_workers} ...")
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, sid, evs): (sid, evs) for sid, evs in samples}
        for future in as_completed(futures):
            result = future.result()
            lock["completed"] += 1
            if result:
                lock["success"] += 1
                results.append(result)
            else:
                lock["failed"] += 1
            
            # 每完成一条更新进度条
            elapsed = time.time() - start_time
            avg_time = elapsed / lock["completed"] if lock["completed"] > 0 else 0
            remain = (total - lock["completed"]) * avg_time
            suffix = f"成功:{lock['success']} 失败:{lock['failed']} 预计剩余:{remain/60:.1f}分钟"
            _print_progress_bar(lock["completed"], total, prefix=label, suffix=suffix)
    
    elapsed_total = time.time() - start_time
    print(f"  ✓ {label} 完成：成功 {lock['success']}/{total}，耗时 {elapsed_total/60:.1f} 分钟")
    return results


def build_all_datasets(
    events_path: str,
    output_dir: str,
    train_target: int = 500,
    val_target: int = 50,
    test_target: int = 50,
    seed: int = 42,
):
    """生成训练集、验证集、测试集
    
    数据划分策略：
    - 训练集：rich + medium + poor 分层采样
    - 验证集：poor styles，与训练集不重叠
    - 测试集：poor styles，与训练集/验证集不重叠
    """
    random.seed(seed)
    
    print(f"[1/7] 加载事件数据: {events_path} ...")
    events = load_events(events_path)
    style_events = group_by_style(events)
    
    # 过滤并分层
    layers = {"rich": [], "medium": [], "poor": []}
    for sid, evs in style_events.items():
        layer = classify_layer(len(evs))
        if layer in layers:
            layers[layer].append((sid, evs))
    
    print(f"      总款号数: {len(style_events)}")
    print(f"      丰富款号 (>=10事件): {len(layers['rich'])}")
    print(f"      中等款号 (5-9事件): {len(layers['medium'])}")
    print(f"      少量款号 (2-4事件): {len(layers['poor'])}")
    
    # 计算训练集各层目标数量
    train_targets = {k: int(train_target * v) for k, v in LAYER_DISTRIBUTION.items()}
    diff = train_target - sum(train_targets.values())
    train_targets["rich"] += diff
    
    print(f"[2/7] 采样训练数据 ...")
    train_samples = []
    for layer, target in train_targets.items():
        candidates = layers[layer]
        if len(candidates) < target:
            sampled = random.choices(candidates, k=target)
            print(f"      ⚠️ {layer} 层候选不足 ({len(candidates)} < {target})，允许重复采样")
        else:
            sampled = random.sample(candidates, target)
        train_samples.extend(sampled)
        layer_name = {"rich": "丰富", "medium": "中等", "poor": "少量"}[layer]
        print(f"      {layer_name}: {len(sampled)} 条 (可用: {len(candidates)})")
    
    # 验证集：只用poor，且与训练集不重叠
    print(f"[3/7] 采样验证数据 ...")
    train_sids = set(sid for sid, _ in train_samples)
    val_candidates = [(sid, evs) for sid, evs in layers["poor"] if sid not in train_sids]
    if len(val_candidates) < val_target:
        print(f"      ⚠️ 警告: 验证集候选仅 {len(val_candidates)} 条 (目标 {val_target})")
        val_samples = val_candidates
    else:
        val_samples = random.sample(val_candidates, val_target)
    print(f"      验证集 (少量款号): {len(val_samples)} 条")
    
    # 测试集：只用poor，且与训练集/验证集都不重叠
    print(f"[4/7] 采样测试数据 ...")
    val_sids = set(sid for sid, _ in val_samples)
    test_candidates = [(sid, evs) for sid, evs in layers["poor"] 
                       if sid not in train_sids and sid not in val_sids]
    if len(test_candidates) < test_target:
        print(f"      ⚠️ 警告: 测试集候选仅 {len(test_candidates)} 条 (目标 {test_target})")
        test_samples = test_candidates
    else:
        test_samples = random.sample(test_candidates, test_target)
    print(f"      测试集 (少量款号): {len(test_samples)} 条")
    
    # 检查款号重叠
    all_train = set(sid for sid, _ in train_samples)
    all_val = set(sid for sid, _ in val_samples)
    all_test = set(sid for sid, _ in test_samples)
    overlap_tv = all_train & all_val
    overlap_tt = all_train & all_test
    overlap_vt = all_val & all_test
    if overlap_tv or overlap_tt or overlap_vt:
        print(f"      ⚠️ 款号重叠警告: train∩val={len(overlap_tv)}, train∩test={len(overlap_tt)}, val∩test={len(overlap_vt)}")
    else:
        print(f"      ✅ 款号无重叠")
    
    # 调用DeepSeek生成
    print(f"[5/7] 调用 DeepSeek API 生成输出 ...")
    client = get_deepseek_client()
    
    train_data = _process_batch_with_progress(client, train_samples, "训练集", MAX_WORKERS)
    val_data = _process_batch_with_progress(client, val_samples, "验证集", MAX_WORKERS)
    test_data = _process_batch_with_progress(client, test_samples, "测试集", MAX_WORKERS)
    
    # 质量检查
    print(f"[6/7] 质量检查 ...")
    
    def _check_split(data, name):
        passed = 0
        failed_reasons = Counter()
        for r in data:
            checks = quality_check(r)
            if checks["passed"]:
                passed += 1
            else:
                for k, v in checks.items():
                    if k != "passed" and k != "output_length" and not v:
                        failed_reasons[k] += 1
        print(f"      {name}通过: {passed}/{len(data)} ({passed/len(data)*100:.1f}%)")
        if failed_reasons:
            print(f"      {name}失败原因:")
            for reason, count in failed_reasons.most_common():
                reason_cn = {
                    "has_title": "缺少标题",
                    "has_timeline": "缺少时间线",
                    "has_risks": "缺少风险点",
                    "has_path": "缺少关键路径",
                    "has_table": "缺少表格",
                    "has_source": "缺少来源邮件",
                    "has_icons": "缺少图标",
                }.get(reason, reason)
                print(f"        - {reason_cn}: {count} 条")
        return passed
    
    train_passed = _check_split(train_data, "训练集")
    val_passed = _check_split(val_data, "验证集")
    test_passed = _check_split(test_data, "测试集")
    
    # 保存
    print(f"[7/7] 保存数据到 {output_dir} ...")
    os.makedirs(output_dir, exist_ok=True)
    
    # 按分片保存
    splits = {
        "train": train_data,
        "val": val_data,
        "test": test_data,
    }
    
    for split_name, data in splits.items():
        split_dir = os.path.join(output_dir, split_name)
        os.makedirs(split_dir, exist_ok=True)
        sft_path = os.path.join(split_dir, "sft_v1_timeline.jsonl")
        with open(sft_path, "w", encoding="utf-8") as f:
            for d in data:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"      Saved {split_name}: {sft_path} ({len(data)} 条)")
    
    # 同时保存到根目录（兼容旧路径）
    #train_path = os.path.join(output_dir, "sft_v1_timeline.jsonl")
    #val_path = os.path.join(output_dir, "val_v1_timeline.jsonl")
    
    with open(train_path, "w", encoding="utf-8") as f:
        for d in train_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    with open(val_path, "w", encoding="utf-8") as f:
        for d in val_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    # 保存 val 到 val/ 子目录（兼容 dataset_info.json）
    val_dir = os.path.join(output_dir, "val")
    os.makedirs(val_dir, exist_ok=True)
    with open(os.path.join(val_dir, "val_v1_timeline.jsonl"), "w", encoding="utf-8") as f:
        for d in val_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    # 统计
    stats = {
        "generated_at": datetime.now().isoformat(),
        "seed": seed,
        "train": {
            "total": len(train_data),
            "quality_passed": train_passed,
            "layer_distribution": dict(Counter(classify_layer(r["event_count"]) for r in train_data)),
            "avg_events": sum(r["event_count"] for r in train_data) / len(train_data) if train_data else 0,
        },
        "val": {
            "total": len(val_data),
            "quality_passed": val_passed,
            "layer_distribution": dict(Counter(classify_layer(r["event_count"]) for r in val_data)),
            "avg_events": sum(r["event_count"] for r in val_data) / len(val_data) if val_data else 0,
        },
        "test": {
            "total": len(test_data),
            "quality_passed": test_passed,
            "layer_distribution": dict(Counter(classify_layer(r["event_count"]) for r in test_data)),
            "avg_events": sum(r["event_count"] for r in test_data) / len(test_data) if test_data else 0,
        },
    }
    
    stats_path = os.path.join(output_dir, "v1_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✅ 全部完成！")
    print(f"{'='*60}")
    print(f"TRAIN: {output_dir}/train/sft_v1_timeline.jsonl ({len(train_data)} 条)")
    print(f"VAL:   {output_dir}/val/sft_v1_timeline.jsonl ({len(val_data)} 条)")
    print(f"TEST:  {output_dir}/test/sft_v1_timeline.jsonl ({len(test_data)} 条)")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="构建 V1 时间线分析训练数据集")
    parser.add_argument("--events", default=DEFAULT_EVENTS_FILE, help="events_passed.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--train-target", type=int, default=500, help="目标训练样本数")
    parser.add_argument("--val-target", type=int, default=50, help="目标验证样本数")
    parser.add_argument("--test-target", type=int, default=50, help="目标测试样本数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()
    
    build_all_datasets(
        events_path=args.events,
        output_dir=args.output_dir,
        train_target=args.train_target,
        val_target=args.val_target,
        test_target=args.test_target,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
