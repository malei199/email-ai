#!/bin/bash
# 增量更新测试脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
KG_DIR="${PROJECT_ROOT}/email_kg_pipeline"
GRAPH_FILE="${KG_DIR}/output/kg_graph_with_customers.pkl"

echo "========================================"
echo "增量更新测试"
echo "========================================"
echo ""

if [ ! -f "$GRAPH_FILE" ]; then
    echo "[ERROR] 图谱文件不存在: $GRAPH_FILE"
    exit 1
fi

# 测试前统计
echo "【测试前】图谱统计:"
PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH" python3 -c "
import pickle
with open('$GRAPH_FILE', 'rb') as f:
    data = pickle.load(f)
G = data['graph']
style_node = 'Style:CCSS230021'
if style_node in G:
    print(f\"  CCSS230021 event_count: {G.nodes[style_node].get('event_count', 0)}\")
    print(f\"  CCSS230021 last_update: {G.nodes[style_node].get('last_update', '')}\")
print(f\"  总节点数: {G.number_of_nodes()}\")
print(f\"  总关系数: {G.number_of_edges()}\")
"
echo ""

# 创建测试事件
echo "【测试】添加新事件..."
TEST_EVENT='{
  "style_id": "CCSS230021",
  "category": "出货",
  "event_type": "确认",
  "date": "2025-08-20",
  "party_from": "工厂",
  "party_to": "客人",
  "description": "款号 CCSS230021 于 2025-08-20 确认出货",
  "source_filename": "test_new_email.eml",
  "confidence": 0.95
}'

PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH" python3 -c "
import json
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from email_kg_pipeline.src.kg_builder import EmailKnowledgeGraph
from email_kg_pipeline.src.kg_updater import KGUpdater

kg = EmailKnowledgeGraph.load('$GRAPH_FILE')
updater = KGUpdater(kg)

event = json.loads('$TEST_EVENT')
result = updater.add_event(event)

print(json.dumps(result, ensure_ascii=False, indent=2))

if result['success']:
    kg.save('$GRAPH_FILE')
    print('[SUCCESS] 增量更新完成，图谱已保存')
else:
    print('[ERROR] 增量更新失败')
"

echo ""
echo "【测试后】图谱统计:"
PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH" python3 -c "
import pickle
with open('$GRAPH_FILE', 'rb') as f:
    data = pickle.load(f)
G = data['graph']
style_node = 'Style:CCSS230021'
if style_node in G:
    print(f\"  CCSS230021 event_count: {G.nodes[style_node].get('event_count', 0)}\")
    print(f\"  CCSS230021 last_update: {G.nodes[style_node].get('last_update', '')}\")
print(f\"  总节点数: {G.number_of_nodes()}\")
print(f\"  总关系数: {G.number_of_edges()}\")
"

echo ""
echo "========================================"
echo "增量更新测试完成"
echo "========================================"
