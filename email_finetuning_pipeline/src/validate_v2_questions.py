#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2 问题验证脚本

读取已生成的 v2_questions.json，对每个问题的 requires_interface 执行验证，
更新 validation 字段后保存。

使用：
    python validate_v2_questions.py
    python validate_v2_questions.py --input datasets/v2_questions.json
"""

import os
import sys
import json
import argparse
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
from email_agent.services.v2_executor import V2FunctionExecutor


def validate_questions(input_path: str, output_path: str = None):
    """验证问题可执行性"""
    
    if output_path is None:
        output_path = input_path
    
    print(f"[1/3] 加载问题数据: {input_path} ...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    questions = data.get("questions", [])
    print(f"      总问题数: {len(questions)}")
    
    print(f"\n[2/3] 初始化 V2 执行器...")
    executor = V2FunctionExecutor()
    print("      V2 执行器已加载")
    
    print(f"\n[3/3] 验证问题可执行性...")
    validated_count = 0
    failed_count = 0
    
    for i, q in enumerate(questions):
        interfaces = q.get("requires_interface", [])
        if not interfaces:
            q["validation"] = {
                "status": "failed",
                "executed_at": datetime.now().isoformat(),
                "result": "requires_interface 为空",
            }
            failed_count += 1
            continue
        
        try:
            result = executor.execute(interfaces)
            
            if result.get("status") == "success":
                # 检查返回是否为空
                has_data = False
                for key, value in result.items():
                    if key.startswith("_"):
                        continue
                    if value and (not isinstance(value, list) or len(value) > 0):
                        has_data = True
                        break
                
                if has_data:
                    q["validation"] = {
                        "status": "success",
                        "executed_at": datetime.now().isoformat(),
                        "result": "执行成功返回有数据",
                    }
                    validated_count += 1
                else:
                    q["validation"] = {
                        "status": "failed",
                        "executed_at": datetime.now().isoformat(),
                        "result": "执行成功但返回为空",
                    }
                    failed_count += 1
            elif result.get("status") == "answer":
                q["validation"] = {
                    "status": "success",
                    "executed_at": datetime.now().isoformat(),
                    "result": "generate_answer 调用",
                }
                validated_count += 1
            else:
                q["validation"] = {
                    "status": "failed",
                    "executed_at": datetime.now().isoformat(),
                    "result": result.get("error", "未知错误"),
                }
                failed_count += 1
                
        except Exception as e:
            q["validation"] = {
                "status": "failed",
                "executed_at": datetime.now().isoformat(),
                "result": f"执行异常: {str(e)}",
            }
            failed_count += 1
        
        # 进度
        percent = (i + 1) / len(questions) * 100
        print(f"\r  验证 {i+1}/{len(questions)} ({percent:.1f}%) 成功:{validated_count} 失败:{failed_count}", end="")
    
    print()  # 换行
    
    # 更新统计
    data["validated_success"] = validated_count
    data["validated_failed"] = failed_count
    data["validated_at"] = datetime.now().isoformat()
    
    print(f"\n验证完成:")
    print(f"  成功: {validated_count} 条")
    print(f"  失败: {failed_count} 条")
    
    # 保存
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"  已保存到: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Validate V2 questions executability")
    parser.add_argument("--input", default="email_finetuning_pipeline/datasets/v2_questions.json", help="Input JSON path")
    parser.add_argument("--output", default="email_finetuning_pipeline/datasets/v2_questions.json", help="Output JSON path (default: overwrite input)")
    args = parser.parse_args()
    
    validate_questions(args.input, args.output)


if __name__ == "__main__":
    main()
