#!/bin/bash
# 邮件知识图谱构建脚本
# 功能：一键构建知识图谱

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
KG_DIR="${PROJECT_ROOT}/email_kg_pipeline"

echo "========================================"
echo "邮件知识图谱构建"
echo "========================================"
echo ""

# 检查依赖
echo "[1/4] 检查依赖..."
python3 -c "import networkx" 2>/dev/null || {
    echo "[ERROR] 缺少 networkx 依赖"
    echo "请运行: pip install networkx"
    exit 1
}
echo "      ✓ networkx 已安装"

# 检查数据文件
echo ""
echo "[2/4] 检查数据文件..."

EVENTS_FILE="${PROJECT_ROOT}/email_rag_pipeline/output/new/events_passed.json"
FACTORY_FILE="${KG_DIR}/data/factory_mapping.csv"
ORG_FILE="${KG_DIR}/data/organization.json"

if [ ! -f "$EVENTS_FILE" ]; then
    echo "[ERROR] 事件数据文件不存在: $EVENTS_FILE"
    echo "请先运行邮件事件提取流水线"
    exit 1
fi
echo "      ✓ 事件数据: $EVENTS_FILE"

if [ ! -f "$FACTORY_FILE" ]; then
    echo "[WARN] 工厂数据文件不存在: $FACTORY_FILE"
    echo "      将跳过工厂数据导入"
    FACTORY_ARG=""
else
    echo "      ✓ 工厂数据: $FACTORY_FILE"
    FACTORY_ARG="--factory $FACTORY_FILE"
fi

EMAIL_SUMMARY_ARG=""
if [ -f "$EMAIL_SUMMARY_FILE" ]; then
    echo "      ✓ 邮件摘要: $EMAIL_SUMMARY_FILE"
    EMAIL_SUMMARY_ARG="--email-summary $EMAIL_SUMMARY_FILE"
else
    echo "      [WARN] 邮件摘要文件不存在: $EMAIL_SUMMARY_FILE"
    echo "      将跳过客户数据导入"
fi

if [ ! -f "$ORG_FILE" ]; then
    echo "[WARN] 组织架构文件不存在: $ORG_FILE"
    echo "      将跳过组织架构导入"
    ORG_ARG=""
else
    echo "      ✓ 组织架构: $ORG_FILE"
    ORG_ARG="--org $ORG_FILE"
fi

# 构建图谱
echo ""
echo "[3/4] 构建知识图谱..."
python3 "${KG_DIR}/src/kg_builder.py" \
    --events "$EVENTS_FILE" \
    $FACTORY_ARG \
    $ORG_ARG \
    $EMAIL_SUMMARY_ARG \
    --output "${KG_DIR}/output/kg_graph_with_customers.pkl"

# 输出统计
echo ""
echo "[4/4] 构建完成！"
echo ""

if [ -f "${KG_DIR}/output/kg_stats.json" ]; then
    echo "图谱统计:"
    python3 -c "
import json
with open('${KG_DIR}/output/kg_stats.json') as f:
    stats = json.load(f)
print(f\"  节点总数: {stats['total_nodes']}\")
print(f\"  关系总数: {stats['total_edges']}\")
print(f\"  节点类型: {stats['node_types']}\")
print(f\"  关系类型: {stats['edge_types']}\")
"
fi

echo ""
echo "输出文件:"
echo "  图谱文件: ${KG_DIR}/output/kg_graph_with_customers.pkl"
echo "  统计文件: ${KG_DIR}/output/kg_stats.json"
echo ""
echo "下一步:"
echo "  测试查询: python3 ${KG_DIR}/src/kg_query.py --help"
