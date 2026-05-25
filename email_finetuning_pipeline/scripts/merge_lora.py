#!/usr/bin/env python3
"""
合并 LoRA 权重到基座模型，生成独立的完整模型。
用于绕过 vLLM 动态 LoRA 加载的 bug。

用法:
    python merge_lora.py --model v3
    python merge_lora.py --model v2
    python merge_lora.py --model v1
    python merge_lora.py --all
"""

import argparse
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
OUTPUT_ROOT = "/openbayes/home/models"

LORA_CONFIG = {
    "v3": {
        "path": f"{LORA_ROOT}/dpo-v3/checkpoint-225",
        "output": f"{OUTPUT_ROOT}/v3-merged",
    },
    "v2": {
        "path": f"{LORA_ROOT}/dpo-v2/checkpoint-243",
        "output": f"{OUTPUT_ROOT}/v2-merged",
    },
    "v1": {
        "path": f"{LORA_ROOT}/sft-v1/checkpoint-189",
        "output": f"{OUTPUT_ROOT}/v1-merged",
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


def merge_lora(model_name, lora_path, output_path):
    """合并单个 LoRA 到基座模型"""
    
    print(f"\n{'='*50}")
    print(f"合并 {model_name.upper()}")
    print(f"{'='*50}")
    
    if os.path.exists(output_path) and os.path.exists(os.path.join(output_path, "config.json")):
        print(f"输出目录已存在，跳过: {output_path}")
        return
    
    base_path = get_base_model_path()
    print(f"基座模型: {base_path}")
    print(f"LoRA 路径: {lora_path}")
    print(f"输出路径: {output_path}")
    
    # 检查路径
    if not os.path.exists(lora_path):
        print(f"错误: LoRA 路径不存在: {lora_path}")
        sys.exit(1)
    
    # 加载基座模型
    print("\n[1/4] 加载基座模型...")
    model = AutoModelForCausalLM.from_pretrained(
        base_path,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    
    # 加载 tokenizer
    print("[2/4] 加载 tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(base_path, trust_remote_code=True)
    
    # 加载 LoRA
    print("[3/4] 加载 LoRA 权重...")
    model = PeftModel.from_pretrained(model, lora_path)
    
    # 合并
    print("[4/4] 合并权重...")
    model = model.merge_and_unload()
    
    # 保存
    print(f"\n保存到 {output_path}...")
    os.makedirs(output_path, exist_ok=True)
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    
    print(f"✅ {model_name.upper()} 合并完成!")
    
    # 释放显存
    del model
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description="合并 LoRA 到基座模型")
    parser.add_argument(
        "--model",
        choices=["v3", "v2", "v1"],
        help="要合并的模型 (v3/v2/v1)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="合并所有模型",
    )
    
    args = parser.parse_args()
    
    if not args.model and not args.all:
        parser.print_help()
        sys.exit(1)
    
    models_to_merge = ["v3", "v2", "v1"] if args.all else [args.model]
    
    for model_name in models_to_merge:
        config = LORA_CONFIG.get(model_name)
        if not config:
            print(f"错误: 未知模型 {model_name}")
            continue
        
        merge_lora(model_name, config["path"], config["output"])
    
    print(f"\n{'='*50}")
    print("全部完成!")
    print(f"{'='*50}")
    
    for model_name in models_to_merge:
        output_path = LORA_CONFIG[model_name]["output"]
        print(f"  {model_name}: {output_path}")
    
    print(f"\n启动命令示例:")
    print(f"  vllm serve {LORA_CONFIG['v3']['output']} --port 8001")


if __name__ == "__main__":
    main()
