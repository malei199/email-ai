#!/usr/bin/env python3
"""增量更新测试脚本"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
from email_kg_pipeline.src.kg_updater import KGUpdater

GRAPH_FILE = PROJECT_ROOT / "email_kg_pipeline" / "output" / "kg_graph_with_customers.pkl"

def main():
    print("=" * 50)
    print("增量更新测试")
    print("=" * 50)
    print()
    
    # 加载图谱
    kg = EmailKnowledgeGraph.load(str(GRAPH_FILE))
    updater = KGUpdater(kg)
    
    # 测试前统计
    print("【测试前】CCSS230021 统计:")
    style_node = "Style:CCSS230021"
    if style_node in kg.G:
        print(f"  event_count: {kg.G.nodes[style_node].get('event_count', 0)}")
        print(f"  last_update: {kg.G.nodes[style_node].get('last_update', '')}")
    print(f"  总节点数: {kg.G.number_of_nodes()}")
    print(f"  总关系数: {kg.G.number_of_edges()}")
    print()
    
    # 创建测试事件
    test_event = {
        "style_id": "CCSS230021",
        "category": "出货",
        "event_type": "确认",
        "date": "2025-08-20",
        "party_from": "工厂",
        "party_to": "客人",
        "description": "款号 CCSS230021 于 2025-08-20 确认出货",
        "source_filename": "test_new_email.eml",
        "confidence": 0.95
    }
    
    print("【测试】添加新事件:")
    print(json.dumps(test_event, ensure_ascii=False, indent=2))
    print()
    
    # 执行增量更新
    result = updater.add_event(test_event)
    print("更新结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    
    if result["success"]:
        # 保存
        kg.save(str(GRAPH_FILE))
        
        # 测试后统计
        print("【测试后】CCSS230021 统计:")
        if style_node in kg.G:
            print(f"  event_count: {kg.G.nodes[style_node].get('event_count', 0)}")
            print(f"  last_update: {kg.G.nodes[style_node].get('last_update', '')}")
        print(f"  总节点数: {kg.G.number_of_nodes()}")
        print(f"  总关系数: {kg.G.number_of_edges()}")
        print()
        
        # 验证查询
        from email_kg_pipeline.src.kg_query import KGQueryEngine
        engine = KGQueryEngine(kg)
        
        print("【验证】查询最后更新时间:")
        update_result = engine.get_last_update("CCSS230021")
        print(json.dumps(update_result, ensure_ascii=False, indent=2))
    else:
        print("[ERROR] 增量更新失败")

if __name__ == "__main__":
    main()
