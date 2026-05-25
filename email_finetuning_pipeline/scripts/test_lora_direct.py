#!/usr/bin/env python3
"""
直接用 transformers + PEFT 加载 LoRA，测试权重是否有效。
从训练数据中自动读取 system prompt，确保推理格式与训练一致。

用法:
    python test_lora_direct.py --model v3
    python test_lora_direct.py --model v2
    python test_lora_direct.py --model v1
"""

import argparse
import json
import os
import sys
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BASE_MODEL_PATH = "/openbayes/home/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots"
LORA_ROOT = "/openbayes/home/LlamaFactory/outputs"
DATASET_ROOT = "/openbayes/home/LlamaFactory/datasets/train"

LORA_CONFIG = {
    "v3": {
        "path": f"{LORA_ROOT}/dpo-v3/checkpoint-225",
        "dataset": f"{DATASET_ROOT}/sft_scheduler_v3.jsonl",
        "prompt": "8859114 进度怎么样",
    },
    "v2": {
        "path": f"{LORA_ROOT}/dpo-v2/checkpoint-243",
        "dataset": f"{DATASET_ROOT}/sft_v2_multiround.jsonl",
        "prompt": "我跟的款号有哪些",
    },
    "v1": {
        "path": f"{LORA_ROOT}/sft-v1/checkpoint-189",
        "dataset": f"{DATASET_ROOT}/sft_v1_timeline.jsonl",
        "prompt": "整理 8859114 的时间线",
    },
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_base_model_path():
    """获取基座模型的快照路径"""
    snapshots_dir = BASE_MODEL_PATH
    if not os.path.exists(snapshots_dir):
        print(f"错误: 基座模型路径不存在: {snapshots_dir}")
        sys.exit(1)
    
    snapshots = [d for d in os.listdir(snapshots_dir) 
                 if os.path.isdir(os.path.join(snapshots_dir, d))]
    if not snapshots:
        print(f"错误: 找不到快照目录: {snapshots_dir}")
        sys.exit(1)
    
    return os.path.join(snapshots_dir, snapshots[0])


def get_system_prompt(dataset_path):
    """从训练数据第一条读取 system prompt"""
    if not os.path.exists(dataset_path):
        print(f"警告: 训练数据不存在: {dataset_path}")
        return None
    
    with open(dataset_path, 'r', encoding='utf-8') as f:
        first_line = json.loads(f.readline())
    
    messages = first_line.get('messages', first_line.get('conversations', []))
    for msg in messages:
        if msg.get('role') == 'system':
            return msg.get('content')
    
    return None


def test_lora(model_name, lora_path, test_prompt, dataset_path):
    """测试单个 LoRA"""
    
    print(f"\n{'='*60}")
    print(f"测试 {model_name.upper()}")
    print(f"{'='*60}")
    print(f"LoRA 路径: {lora_path}")
    print(f"训练数据: {dataset_path}")
    print(f"测试输入: {test_prompt}")
    
    if not os.path.exists(lora_path):
        print(f"错误: LoRA 路径不存在: {lora_path}")
        return
    
    # 读取 system prompt
    system_prompt = get_system_prompt(dataset_path)
    if system_prompt:
        print(f"\nSystem prompt (前100字): {system_prompt[:100]}...")
    else:
        print("\n警告: 未找到 system prompt")
    
    base_path = get_base_model_path()
    print(f"基座模型: {base_path}")
    
    # 加载 tokenizer
    print("\n加载 tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(base_path, trust_remote_code=True)
    
    # 加载基座模型
    print("加载基座模型...")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_path,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    
    # 应用 chat template
    if system_prompt:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": test_prompt}
        ]
    else:
        messages = [{"role": "user", "content": test_prompt}]
    
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    print(f"\n实际输入 prompt (前300字):\n{text[:300]}...")
    
    # 基座模型输出
    print("\n" + "-"*40)
    print("【基座模型输出】（无 LoRA）:")
    print("-"*40)
    inputs = tokenizer(text, return_tensors="pt").to(base_model.device)
    outputs = base_model.generate(
        **inputs,
        max_new_tokens=500,
        temperature=0.1,
        do_sample=True,
    )
    base_output = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print(base_output[:500])
    
    # 加载 LoRA
    print("\n加载 LoRA 权重...")
    lora_model = PeftModel.from_pretrained(base_model, lora_path)
    
    # LoRA 模型输出
    print("\n" + "-"*40)
    print("【LoRA 模型输出】:")
    print("-"*40)
    inputs = tokenizer(text, return_tensors="pt").to(lora_model.device)
    outputs = lora_model.generate(
        **inputs,
        max_new_tokens=500,
        temperature=0.1,
        do_sample=True,
    )
    lora_output = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print(lora_output[:500])
    
    # 对比
    print("\n" + "="*60)
    if base_output.strip() == lora_output.strip():
        print("⚠️ 警告: 基座和 LoRA 输出完全相同，LoRA 可能没有生效!")
    else:
        print("✅ LoRA 输出与基座不同，LoRA 已生效")
    print("="*60)
    
    # 释放显存
    del base_model
    del lora_model
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description="直接测试 LoRA 权重")
    parser.add_argument(
        "--model",
        choices=["v3", "v2", "v1"],
        required=True,
        help="要测试的模型 (v3/v2/v1)",
    )
    
    args = parser.parse_args()
    
    config = LORA_CONFIG.get(args.model)
    if not config:
        print(f"错误: 未知模型 {args.model}")
        sys.exit(1)
    
    test_lora(args.model, config["path"], config["prompt"], config["dataset"])


if __name__ == "__main__":
    main()
