#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build V3 scheduler (orchestrator) fine-tuning dataset —— v2.0 极简版

V3 职责：纯路由决策器（单轮）
  1. 有款号 → route_v1
  2. 无款号 → route_v2
  3. 问候/越界/模糊 → direct_answer

V3 不做：
  - 不接收 V1/V2 结果回传
  - 不做查询编排
  - 不做结果质量判断
  - 不学模板选择

数据来源：
  - events_passed.json（真实事件，用于构造有款号query）
  - 真实人物/工厂/客户名（用于构造无款号query）

输出：
  - email_finetuning_pipeline/datasets/sft_scheduler_v3.jsonl
  - email_finetuning_pipeline/datasets/dpo_scheduler_v3.jsonl

使用:
    python build_v3_scheduler_dataset.py
    python build_v3_scheduler_dataset.py --sft-target 800 --dpo-target 600
"""

import os
import json
import argparse
import random
from collections import Counter, defaultdict
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EVENTS_FILE = os.path.join(_SCRIPT_DIR, "../../email_rag_pipeline/output/events_passed.json")
DEFAULT_ORDER_MAPPING_FILE = os.path.join(_SCRIPT_DIR, "../datasets/order_mapping.json")
DEFAULT_OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "../datasets")

# 场景分布（3种路由）
SCENE_DISTRIBUTION = {
    "direct_answer": 0.12,      # 问候、能力说明、越界、模糊
    "route_v1": 0.40,           # 有款号 → V1分析（核心场景）
    "route_v2": 0.43,           # 无款号 → V2查询
    "boundary": 0.05,           # 越界问题
}

SYSTEM_PROMPT_V3 = (
    "你是服装行业智能调度器。根据用户问题，决定如何回答：\n"
    "1. direct_answer: 直接回答（问候、超出范围、模糊提问等）\n"
    "2. route_v2: 调用 V2 查询引擎（无款号）\n"
    "3. route_v1: 调用 V1 时间线推理模型（有款号）\n"
    "输出格式：{\"decision\": \"...\", ...}"
)

# ---------------------------------------------------------------------------
# 直接回答模板
# ---------------------------------------------------------------------------
DIRECT_ANSWER_TEMPLATES = {
    "greeting": {
        "questions": [
            "你好", "在吗", "嗨", "hello", "hi", "早上好", "下午好",
            "你好，请问在吗", "hi，在不在"
        ],
        "answer": "你好！我是服装行业智能助手，可以帮您查询款号信息、整理时间线、分析延期原因等。请告诉我您需要查询的款号。"
    },
    "capability": {
        "questions": [
            "你能做什么", "怎么查询", "有什么功能", "怎么用",
            "你可以帮我查什么", "这个系统能做什么"
        ],
        "answer": "我可以帮您：\n1. 查询款号的时间线和进度\n2. 查找相关人员信息\n3. 分析延期原因\n4. 查询技术参数（面料、拉链等）\n5. 术语翻译\n\n请直接输入款号和您想了解的内容。"
    },
    "out_of_scope": {
        "questions": [
            "今天天气怎么样", "帮我写代码", "推荐个餐厅", "讲个笑话",
            "帮我写一封邮件", "计算一下这个公式", "翻译这段英文"
        ],
        "answer": "抱歉，我是服装行业专用助手，只能处理与服装生产、款号查询相关的业务问题。请问有什么款号需要查询吗？"
    },
    "vague": {
        "questions": [
            "查一下", "那个款号", "帮我看看", "怎么样",
            "查查看", "帮我查一下", "看看情况", "查一下进度"
        ],
        "answer": "请提供具体的款号（如 CCSS230021 或 AW25-KFWTT156）和您想了解的信息，例如：\n- 时间线/进度\n- 相关人员\n- 延期原因\n- 技术参数"
    },
}

# ---------------------------------------------------------------------------
# 越界案例
# ---------------------------------------------------------------------------
BOUNDARY_CASES = [
    {"question": "9999999 的信息", "answer": "未找到款号 9999999 的相关记录，请确认款号是否正确。"},
    {"question": "ABCDEFG 的时间线", "answer": "款号格式不正确，请提供有效的款号（如 CCSS230021 或 AW25-KFWTT156）。"},
    {"question": "CCSS230021 的纽扣信息", "answer": "未找到 CCSS230021 的纽扣相关信息，建议查看原始邮件或联系工厂确认。"},
    {"question": "帮我订个外卖", "answer": "抱歉，我是服装行业专用助手，无法帮您订外卖。请问有什么款号需要查询吗？"},
    {"question": "CCSS230021 的信息，顺便帮我看看 Paula Cheng 的所有款号", "answer": "您的问题包含多个意图（有款号查询+无款号查询），请拆分后分别提问。"},
]

# ---------------------------------------------------------------------------
# route_v1 问题模板（有款号）
# ---------------------------------------------------------------------------
ROUTE_V1_TEMPLATES = [
    # 简单时间线查询（无特定事件）
    ("{sid} 的时间线", None),
    ("{sid} 现在到哪了", None),
    ("{sid} 进度如何", None),
    ("帮我整理 {sid} 的进度", None),
    ("{sid} 到哪一步了", None),
    # 延期分析
    ("{sid} 为什么延期了？", "延期"),
    ("{sid} 延期原因", "延期"),
    ("{sid} 还能按时出货吗", "出货"),
    ("{sid} 是不是要延期", "延期"),
    # 综合查询
    ("{sid} 的所有信息", None),
    ("{sid} 完整情况", None),
    ("{sid} 详细进度", None),
    ("{sid} 现在到什么阶段了", None),
    ("帮我看看 {sid} 的整体情况", None),
    # 特定方面
    ("{sid} 谁在跟？", None),
    ("{sid} 的负责人是谁？", None),
    ("{sid} 有哪些人参与？", None),
    ("{sid} 是哪个工厂的？", None),
    ("{sid} 工厂信息", None),
    ("{sid} 的拉链信息", "拉链"),
    ("{sid} 面料成分", "面料"),
    ("{sid} 尺寸规格", "尺寸"),
    # 阶段检查
    ("{sid} 封样了没有", "封样"),
    ("{sid} 样衣好了吗", "样衣"),
    ("{sid} 面料确认了吗", "面料确认"),
    ("{sid} 出货了吗", "出货"),
    ("{sid} Lab Dip 通过了没", "Lab Dip"),
    # 客户/工厂反馈
    ("{sid} 客户意见给了吗", "客户意见"),
    ("{sid} 客人回复了吗", "客户回复"),
    ("{sid} 客人确认了吗", "客户确认"),
    ("{sid} 工厂那边有困难吗", "工厂问题"),
    ("{sid} 工厂反映什么问题", "工厂问题"),
]

# ---------------------------------------------------------------------------
# 无款号问题模板
# ---------------------------------------------------------------------------
BASE_NO_STYLE_TEMPLATES = [
    # 人员查询
    ("{person} 在跟哪些款号", "person"),
    ("帮我查一下 {person} 负责的订单", "person"),
    ("{person} 最近有什么款号要出货", "person"),
    ("{person} 跟的款号有没有延期", "person"),
    ("{person} 的款号进度怎么样", "person"),
    # 工厂查询
    ("{factory} 最近在做什么款号", "factory"),
    ("{factory} 的产能怎么样", "factory"),
    ("{factory} 的款号进度", "factory"),
    # 术语翻译
    ("{term} 是什么意思", "term"),
    ("{term} 怎么翻译", "term"),
    ("帮我翻译这封邮件", "fixed"),
    # 我的款号状态
    ("我跟的款号有哪些", "fixed"),
    ("我负责的款号都到什么阶段了", "fixed"),
    ("我手上有哪些款号要出货了", "fixed"),
    ("我的款号进度怎么样", "fixed"),
    # 多客户/多工厂
    ("{person} 和 {person2} 在跟哪些款号", "person_multi"),
    ("帮我看看 {factory} 和 {factory2} 的进度", "factory_multi"),
    # 客户/工厂问题
    ("我跟的客人有没有延期", "fixed"),
    ("我负责的客户的款号情况", "fixed"),
    ("最近的工厂有什么问题", "fixed"),
    ("帮我看看最近的订单进度", "fixed"),
]

TERM_POOL = [
    "enzyme wash", "taffeta", "shell fabric", "lining", "twill", "denim",
    "jersey", "fleece", "canvas", "satin", "velvet", "chiffon", "lace",
    "interlock", "pique", "oxford", "poplin", "flannel", "corduroy",
]


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_events(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_real_entities(events: list, order_mapping: dict = None) -> dict:
    """从真实事件数据中提取可用于构造query的实体"""
    style_events = defaultdict(list)
    person_styles = defaultdict(list)
    factory_styles = defaultdict(list)
    
    for e in events:
        sid = e.get("style_id", "")
        if sid and sid != "UNKNOWN":
            style_events[sid].append(e)
        
        pf = e.get("party_from", "")
        pt = e.get("party_to", "")
        for p in [pf, pt]:
            if p and p not in ["工厂", "客人", "未知", "供应商", ""]:
                person_styles[p].append(sid)
    
    # 提取工厂（中文名且出现多次）
    for sid, evs in style_events.items():
        for e in evs:
            pf = e.get("party_from", "")
            if pf and len(pf) >= 2 and any("\u4e00" <= c <= "\u9fff" for c in pf):
                if pf not in ["工厂", "客人", "未知", "供应商", "面料厂"]:
                    factory_styles[pf].append(sid)
    
    # 筛选有价值的实体
    people = [p for p, sids in person_styles.items() if len(set(sids)) >= 3]
    factories = [f for f, sids in factory_styles.items() if len(set(sids)) >= 2]
    
    # 款号分类
    styles_rich = []
    styles_medium = []
    styles_poor = []
    
    for sid, evs in style_events.items():
        if len(evs) >= 10:
            styles_rich.append(sid)
        elif len(evs) >= 5:
            styles_medium.append(sid)
        elif len(evs) >= 2:
            styles_poor.append(sid)
    
    return {
        "people": people,
        "factories": factories,
        "styles_rich": styles_rich,
        "styles_medium": styles_medium,
        "styles_poor": styles_poor,
        "style_events": dict(style_events),
        "order_mapping": order_mapping or {},
    }


# ---------------------------------------------------------------------------
# 场景构造（单轮）
# ---------------------------------------------------------------------------

def build_direct_answer_scene(scene_type: str, seed: int = 42) -> dict:
    """构造直接回答场景（单轮）"""
    random.seed(seed)
    templates = DIRECT_ANSWER_TEMPLATES[scene_type]
    question = random.choice(templates["questions"])
    answer = templates["answer"]
    
    return {
        "scene": "direct_answer",
        "scene_type": scene_type,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_V3},
            {"role": "user", "content": question},
            {"role": "assistant", "content": json.dumps({
                "thought": f"用户{scene_type}，直接回答",
                "decision": "direct_answer",
                "answer": answer,
            }, ensure_ascii=False)}
        ]
    }


def build_route_v1_scene(style_id: str, entities: dict, seed: int = 42) -> dict:
    """构造 route_v1 场景（单轮）
    
    V3 只输出路由决策，不参与后续 V1 调用
    """
    random.seed(seed)
    template, event_type = random.choice(ROUTE_V1_TEMPLATES)
    question = template.format(sid=style_id)
    
    # thought 要体现"有款号"这个关键判断
    if event_type:
        thoughts = [
            f"用户提供了款号{style_id}，并询问'{event_type}'相关情况，有款号统一走V1",
            f"问题包含款号{style_id}和事件类型'{event_type}'，直接路由到V1",
            f"检测到款号{style_id}，用户关注'{event_type}'，V1负责款号级分析",
        ]
    else:
        thoughts = [
            f"用户提供了款号{style_id}，按规则有款号统一走V1",
            f"问题包含款号{style_id}，直接路由到V1进行时间线分析",
            f"检测到款号{style_id}，V1负责款号级别的深度分析",
        ]
    
    assistant_output = {
        "thought": random.choice(thoughts),
        "decision": "route_v1",
        "style_id": style_id,
    }
    if event_type:
        assistant_output["event"] = event_type
    
    return {
        "scene": "route_v1",
        "style_id": style_id,
        "event": event_type,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_V3},
            {"role": "user", "content": question},
            {"role": "assistant", "content": json.dumps(assistant_output, ensure_ascii=False)},
        ]
    }


def build_route_v2_scene(entities: dict, seed: int = 42) -> dict:
    """构造 route_v2 场景（单轮）
    
    V3 只输出路由决策，V2 引擎自己决定怎么查
    """
    random.seed(seed)
    
    people = entities["people"]
    factories = entities["factories"]
    
    template_info = random.choice(BASE_NO_STYLE_TEMPLATES)
    template = template_info[0]
    template_type = template_info[1]
    
    # 填充模板
    if template_type == "person":
        person = random.choice(people) if people else "Paula Cheng"
        question = template.format(person=person)
    elif template_type == "person_multi":
        if len(people) >= 2:
            p1, p2 = random.sample(people, 2)
            question = template.format(person=p1, person2=p2)
        else:
            question = "我跟的款号有哪些"
    elif template_type == "factory":
        factory = random.choice(factories) if factories else "南通利丰"
        question = template.format(factory=factory)
    elif template_type == "factory_multi":
        if len(factories) >= 2:
            f1, f2 = random.sample(factories, 2)
            question = template.format(factory=f1, factory2=f2)
        else:
            question = "最近的工厂有什么问题"
    elif template_type == "term":
        term = random.choice(TERM_POOL)
        question = template.format(term=term)
    else:  # fixed
        question = template
    
    # thought 多样性
    thoughts = [
        "用户问题不含款号，需要V2查询",
        "未检测到款号，路由到V2查询引擎",
        "问题属于信息查询类型，走V2",
        "无款号输入，调用V2处理",
    ]
    
    return {
        "scene": "route_v2",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_V3},
            {"role": "user", "content": question},
            {"role": "assistant", "content": json.dumps({
                "thought": random.choice(thoughts),
                "decision": "route_v2",
            }, ensure_ascii=False)},
        ]
    }


def build_boundary_scene(case_idx: int = 0) -> dict:
    """构造边界/异常场景（单轮）"""
    case = BOUNDARY_CASES[case_idx % len(BOUNDARY_CASES)]
    
    return {
        "scene": "boundary",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_V3},
            {"role": "user", "content": case["question"]},
            {"role": "assistant", "content": json.dumps({
                "thought": "款号不存在、信息缺失或问题越界",
                "decision": "direct_answer",
                "answer": case["answer"],
            }, ensure_ascii=False)}
        ]
    }


# ---------------------------------------------------------------------------
# DPO 构造（单轮）
# ---------------------------------------------------------------------------

def build_dpo_from_scene(scene: dict) -> dict:
    """从场景构造DPO偏好对（单轮决策）
    
    错误模式：
    1. route_v1 → route_v2（有款号却走V2，违反核心规则）
    2. route_v2 → direct_answer（无款号查询被错误拒绝）
    3. route_v2 → route_v1（无款号却走V1，V1无输入）
    4. direct_answer → route_v2（问候/越界问题被错误路由）
    """
    messages = scene.get("messages", [])
    if len(messages) < 3:
        return None
    
    # 获取 assistant 的决策
    try:
        assistant_msg = messages[2]  # system(0) + user(1) + assistant(2)
        chosen_obj = json.loads(assistant_msg.get("content", ""))
        chosen_decision = chosen_obj.get("decision", "")
    except:
        return None
    
    chosen = assistant_msg.get("content", "")
    chosen_style_id = chosen_obj.get("style_id", "")
    chosen_event = chosen_obj.get("event")
    
    # 构造错误决策
    rejected_obj = None
    
    if chosen_decision == "route_v1":
        rejected_obj = {
            "thought": f"用户问的是{chosen_style_id}的信息，先走V2查询",
            "decision": "route_v2",
        }
        if chosen_event:
            rejected_obj["event"] = chosen_event
    
    elif chosen_decision == "route_v2":
        error_type = random.choice(["direct_answer", "route_v1"])
        if error_type == "direct_answer":
            rejected_obj = {
                "thought": "用户问题不够具体，直接回答",
                "decision": "direct_answer",
                "answer": "请提供具体的款号信息。",
            }
        else:
            rejected_obj = {
                "thought": "这个问题需要深度分析，走V1",
                "decision": "route_v1",
                "style_id": "",
            }
    
    elif chosen_decision == "direct_answer":
        rejected_obj = {
            "thought": "用户有问题，走V2查询看看",
            "decision": "route_v2",
        }
    
    if not rejected_obj:
        return None
    
    rejected = json.dumps(rejected_obj, ensure_ascii=False)
    
    # 提取 system prompt 和 user input
    instruction = messages[0].get("content", "")
    user_input = messages[1].get("content", "")
    
    return {
        "instruction": instruction,
        "input": user_input,
        "chosen": chosen,
        "rejected": rejected,
        "scene": scene["scene"],
    }


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def _generate_split(
    entities: dict,
    sft_target: int,
    dpo_target: int,
    seed: int,
    use_poor_styles: bool,
    split_name: str,
) -> tuple:
    """生成单个数据分片（训练集/验证集/测试集）"""
    print(f"\n[{split_name}] 生成 {sft_target} 条 SFT + {dpo_target} 条 DPO (seed={seed}, poor_styles={use_poor_styles})")
    
    # 计算各场景目标数量
    scene_targets = {k: int(sft_target * v) for k, v in SCENE_DISTRIBUTION.items()}
    diff = sft_target - sum(scene_targets.values())
    scene_targets["route_v1"] += diff
    
    sft_data = []
    
    # 1. direct_answer
    direct_types = list(DIRECT_ANSWER_TEMPLATES.keys())
    for i in range(scene_targets["direct_answer"]):
        scene_type = direct_types[i % len(direct_types)]
        sft_data.append(build_direct_answer_scene(scene_type, seed=seed + i))
    
    # 2. route_v1（有款号）
    if use_poor_styles:
        all_styles = entities["styles_poor"]
        print(f"      使用 {len(all_styles)} 个少量事件款号")
    else:
        all_styles = entities["styles_rich"] + entities["styles_medium"]
        print(f"      使用 {len(entities['styles_rich'])} 个丰富款号 + {len(entities['styles_medium'])} 个中等款号")
    
    random.shuffle(all_styles)
    route_v1_target = scene_targets["route_v1"]
    
    for i in range(route_v1_target):
        if i < len(all_styles):
            sid = all_styles[i]
        else:
            sid = random.choice(all_styles) if all_styles else "CCSS230021"
        sft_data.append(build_route_v1_scene(sid, entities, seed=seed + i))
    
    print(f"      ✓ route_v1 完成：{route_v1_target} 条")
    
    # 3. route_v2（无款号）
    for i in range(scene_targets["route_v2"]):
        sft_data.append(build_route_v2_scene(entities, seed=seed + i + 1000))
    
    print(f"      ✓ route_v2 完成：{scene_targets['route_v2']} 条")
    
    # 4. boundary
    for i in range(scene_targets["boundary"]):
        sft_data.append(build_boundary_scene(i))
    
    random.shuffle(sft_data)
    sft_data = sft_data[:sft_target]
    
    # 生成DPO
    dpo_data = []
    for scene in sft_data:
        dpo = build_dpo_from_scene(scene)
        if dpo:
            dpo_data.append(dpo)
    random.shuffle(dpo_data)
    dpo_data = dpo_data[:dpo_target]
    
    scene_dist = Counter(s["scene"] for s in sft_data)
    print(f"      生成 SFT: {len(sft_data)} 条, 场景分布: {dict(scene_dist)}")
    print(f"      生成 DPO: {len(dpo_data)} 条")
    
    return sft_data, dpo_data


def _save_split(
    sft_data: list,
    dpo_data: list,
    output_dir: str,
    split_name: str,
):
    """保存单个数据分片"""
    split_dir = os.path.join(output_dir, split_name)
    os.makedirs(split_dir, exist_ok=True)
    
    sft_path = os.path.join(split_dir, "sft_scheduler_v3.jsonl")
    dpo_path = os.path.join(split_dir, "dpo_scheduler_v3.jsonl")
    
    with open(sft_path, "w", encoding="utf-8") as f:
        for d in sft_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    with open(dpo_path, "w", encoding="utf-8") as f:
        for d in dpo_data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    print(f"      已保存到 {split_dir}/")
    return sft_path, dpo_path


def build_all_datasets(
    events_path: str,
    output_dir: str,
    order_mapping_path: str = None,
    sft_target: int = 800,
    dpo_target: int = 600,
    val_sft_target: int = 100,
    val_dpo_target: int = 80,
    test_sft_target: int = 100,
    test_dpo_target: int = 80,
    seed: int = 42,
):
    """生成训练集、验证集、测试集"""
    random.seed(seed)
    
    print(f"[1/4] 加载事件数据: {events_path} ...")
    events = load_events(events_path)
    
    order_mapping = {}
    if order_mapping_path and os.path.exists(order_mapping_path):
        with open(order_mapping_path, "r", encoding="utf-8") as f:
            order_mapping = json.load(f)
        print(f"      已加载 {len(order_mapping)} 个订单")
    
    entities = extract_real_entities(events, order_mapping)
    
    print(f"      总事件数: {len(events)}")
    print(f"      唯一款号数: {len(entities['style_events'])}")
    print(f"      人员 (>=3 个款号): {len(entities['people'])}")
    print(f"      工厂 (>=2 个款号): {len(entities['factories'])}")
    print(f"      丰富款号 (>=10 条事件): {len(entities['styles_rich'])}")
    print(f"      中等款号 (5-9 条事件): {len(entities['styles_medium'])}")
    print(f"      少量款号 (2-4 条事件): {len(entities['styles_poor'])}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 2. 生成训练集
    print(f"\n[2/4] 生成训练集 ...")
    train_sft, train_dpo = _generate_split(
        entities, sft_target, dpo_target,
        seed=seed, use_poor_styles=False,
        split_name="train",
    )
    train_sft_path, train_dpo_path = _save_split(train_sft, train_dpo, output_dir, "train")
    
    # 3. 生成验证集
    print(f"\n[3/4] 生成验证集 ...")
    val_sft, val_dpo = _generate_split(
        entities, val_sft_target, val_dpo_target,
        seed=seed + 10000, use_poor_styles=True,
        split_name="val",
    )
    val_sft_path, val_dpo_path = _save_split(val_sft, val_dpo, output_dir, "val")
    
    # 4. 生成测试集
    print(f"\n[4/4] 生成测试集 ...")
    test_sft, test_dpo = _generate_split(
        entities, test_sft_target, test_dpo_target,
        seed=seed + 20000, use_poor_styles=True,
        split_name="test",
    )
    test_sft_path, test_dpo_path = _save_split(test_sft, test_dpo, output_dir, "test")
    
    # 保存训练集到根目录（兼容旧路径）
    print(f"\n[5/5] 保存训练集到根目录 ...")
    with open(os.path.join(output_dir, "sft_scheduler_v3.jsonl"), "w", encoding="utf-8") as f:
        for d in train_sft:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(os.path.join(output_dir, "dpo_scheduler_v3.jsonl"), "w", encoding="utf-8") as f:
        for d in train_dpo:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    # 保存验证集到 val/ 子目录
    os.makedirs(os.path.join(output_dir, "val"), exist_ok=True)
    with open(os.path.join(output_dir, "val", "sft_scheduler_v3.jsonl"), "w", encoding="utf-8") as f:
        for d in val_sft:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    
    # 统计
    all_stats = {
        "generated_at": datetime.now().isoformat(),
        "seed": seed,
        "train": _compute_stats(train_sft, train_dpo),
        "val": _compute_stats(val_sft, val_dpo),
        "test": _compute_stats(test_sft, test_dpo),
    }
    
    stats_path = os.path.join(output_dir, "scheduler_v3_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✅ 所有数据集生成完成!")
    print(f"{'='*60}")
    print(f"训练集:  {train_sft_path} ({len(train_sft)} 条 SFT, {len(train_dpo)} 条 DPO)")
    print(f"验证集:  {val_sft_path} ({len(val_sft)} 条 SFT, {len(val_dpo)} 条 DPO)")
    print(f"测试集:  {test_sft_path} ({len(test_sft)} 条 SFT, {len(test_dpo)} 条 DPO)")
    print(f"{'='*60}")
    
    return {
        "train": (train_sft, train_dpo),
        "val": (val_sft, val_dpo),
        "test": (test_sft, test_dpo),
    }


def _compute_stats(sft_data: list, dpo_data: list) -> dict:
    """计算数据统计"""
    scene_dist = Counter(s["scene"] for s in sft_data)
    dpo_scene_dist = Counter(d.get("scene", "unknown") for d in dpo_data)
    
    dpo_decisions = {"chosen": Counter(), "rejected": Counter()}
    for d in dpo_data:
        try:
            c = json.loads(d["chosen"])
            r = json.loads(d["rejected"])
            dpo_decisions["chosen"][c.get("decision", "")] += 1
            dpo_decisions["rejected"][r.get("decision", "")] += 1
        except:
            pass
    
    return {
        "sft_total": len(sft_data),
        "sft_scenes": dict(scene_dist),
        "dpo_total": len(dpo_data),
        "dpo_scenes": dict(dpo_scene_dist),
        "dpo_chosen": dict(dpo_decisions["chosen"]),
        "dpo_rejected": dict(dpo_decisions["rejected"]),
    }


def main():
    parser = argparse.ArgumentParser(description="Build V3 scheduler dataset (v2.0)")
    parser.add_argument("--events", default=DEFAULT_EVENTS_FILE, help="Path to events_passed.json")
    parser.add_argument("--order-mapping", default=DEFAULT_ORDER_MAPPING_FILE, help="Path to order_mapping.json")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--sft-target", type=int, default=800, help="Target SFT records for training")
    parser.add_argument("--dpo-target", type=int, default=600, help="Target DPO records for training")
    parser.add_argument("--val-sft-target", type=int, default=100, help="Target SFT records for validation")
    parser.add_argument("--val-dpo-target", type=int, default=80, help="Target DPO records for validation")
    parser.add_argument("--test-sft-target", type=int, default=100, help="Target SFT records for testing")
    parser.add_argument("--test-dpo-target", type=int, default=80, help="Target DPO records for testing")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    
    build_all_datasets(
        events_path=args.events,
        output_dir=args.output_dir,
        order_mapping_path=args.order_mapping,
        sft_target=args.sft_target,
        dpo_target=args.dpo_target,
        val_sft_target=args.val_sft_target,
        val_dpo_target=args.val_dpo_target,
        test_sft_target=args.test_sft_target,
        test_dpo_target=args.test_dpo_target,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
