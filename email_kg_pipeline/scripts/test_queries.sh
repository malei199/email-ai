#!/bin/bash
# 知识图谱查询测试脚本 (V2 - 含 Customer 节点)
# 功能：一键运行常用查询，验证图谱构建是否正确

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
KG_DIR="${PROJECT_ROOT}/email_kg_pipeline"
GRAPH_FILE="${KG_DIR}/output/kg_graph_with_customers.pkl"
TEST_SCRIPT="${KG_DIR}/scripts/test_queries.py"

echo "========================================"
echo "知识图谱查询测试 (V2 - 含 Customer)"
echo "========================================"
echo ""

if [ ! -f "$GRAPH_FILE" ]; then
    echo "[ERROR] 图谱文件不存在: $GRAPH_FILE"
    echo "请先运行构建脚本: python email_kg_pipeline/src/kg_builder.py"
    exit 1
fi

# 测试款号
TEST_STYLE="CCSS230011"
TEST_PERSON="Paula Cheng"
TEST_CUSTOMER="heidi@curated-collective.co.uk"

# 测试 1: 款号完整信息（含客户）
echo "【测试 1】查询款号完整信息（含客户）"
echo "查询: $TEST_STYLE"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --style "$TEST_STYLE" 2>/dev/null | head -60
echo ""

# 测试 2: 人员查询
echo "【测试 2】查询人员参与的款号"
echo "查询: $TEST_PERSON"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --person "$TEST_PERSON" 2>/dev/null | head -40
echo ""

# 测试 3: 客户列表
echo "【测试 3】查询活跃客户列表"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --customers --min-styles 1 2>/dev/null | head -20
echo ""

# 测试 4: 客户详情
echo "【测试 4】查询客户详细信息"
echo "查询: $TEST_CUSTOMER"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --customer "$TEST_CUSTOMER" --customer-detail 2>/dev/null | head -40
echo ""

# 测试 5: 工厂延期
echo "【测试 5】查询工厂延期统计"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --delays 2>/dev/null | head -20
echo ""

# 测试 6: 客户关联款号
echo "【测试 6】查询客户关联款号"
echo "查询: $TEST_CUSTOMER"
python3 "$TEST_SCRIPT" --graph "$GRAPH_FILE" --customer "$TEST_CUSTOMER" 2>/dev/null | head -30
echo ""

echo "========================================"
echo "测试完成"
echo "========================================"
echo ""
echo "更多查询示例:"
echo "  python3 $TEST_SCRIPT --style AW25-KFWTS101 --detail"
echo "  python3 $TEST_SCRIPT --factory HF001"
echo "  python3 $TEST_SCRIPT --style CCSS230021 --question 拉链"
