#!/bin/bash
#
# 邮件事件型 RAG 全量构建一键脚本
# 功能：清理旧数据 -> 全量 DeepSeek 提取 -> 提示复核 -> 重建 ChromaDB
#
# 使用方法：
#   export DEEPSEEK_API_KEY="your-api-key"
#   ./email_rag_pipeline/scripts/run_full_pipeline.sh
#

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/email_rag_pipeline/output/new"
PYTHON_SCRIPT="${PROJECT_ROOT}/email_rag_pipeline/build_email_event_rag.py"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  邮件事件型 RAG 全量构建流水线${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==================== 前置检查 ====================

# 1. 检查 API Key
# if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
#     echo -e "${RED}[ERROR] 未设置 DEEPSEEK_API_KEY 环境变量${NC}"
#     echo "请执行: export DEEPSEEK_API_KEY=\"your-api-key\""
#     exit 1
# fi

# 2. 检查过滤清单是否存在
FILTERED_MANIFEST="${OUTPUT_DIR}/filtered_email_manifest.jsonl"
if [ ! -f "$FILTERED_MANIFEST" ]; then
    echo -e "${RED}[ERROR] 过滤清单不存在: ${FILTERED_MANIFEST}${NC}"
    echo "请先运行前置过滤:"
    echo "  python email_rag_pipeline/pre_filter_emails.py"
    exit 1
fi

FILTERED_COUNT=$(wc -l < "$FILTERED_MANIFEST" | tr -d ' ')
echo -e "${GREEN}[CHECK] 过滤清单已就绪，共 ${FILTERED_COUNT} 封邮件待处理${NC}"

# 3. 检查 Python 脚本
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo -e "${RED}[ERROR] 主脚本不存在: ${PYTHON_SCRIPT}${NC}"
    exit 1
fi

# ==================== Step 1: 清理旧中间结果 ====================
echo ""
echo -e "${YELLOW}[Step 1/4] 清理旧的中间结果...${NC}"

rm -f "${OUTPUT_DIR}/events_raw.jsonl"
rm -f "${OUTPUT_DIR}/events_passed.json"
rm -f "${OUTPUT_DIR}/events_review.jsonl"
rm -f "${OUTPUT_DIR}/processing_stats.json"

echo -e "${GREEN}  已清理旧的提取结果和统计数据${NC}"

# ==================== Step 2: 全量 LLM 提取 ====================
echo ""
echo -e "${YELLOW}[Step 2/4] 开始全量 DeepSeek 事件提取...${NC}"
echo -e "${BLUE}  预计耗时: 20~50 分钟 | 预计费用: 15~40 元${NC}"
echo ""

cd "$PROJECT_ROOT"
python "$PYTHON_SCRIPT" --use-filtered --skip-rag --resume

# 提取完成后检查统计文件
STATS_FILE="${OUTPUT_DIR}/processing_stats.json"
if [ ! -f "$STATS_FILE" ]; then
    echo -e "${RED}[ERROR] 提取完成但统计文件未生成，可能发生了未知错误${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}[Step 2/4] LLM 提取完成！${NC}"
echo ""

# 解析并显示关键统计（需要 Python）
python3 - << PYEOF > /dev/null 2>&1 || true
import json, sys

try:
    with open("${STATS_FILE}", "r") as f:
        stats = json.load(f)
    
    print(f"  处理邮件数: {stats.get('total_emails', 'N/A')}")
    print(f"  通过事件数: {stats.get('passed_events', 'N/A')}")
    print(f"  待复核事件: {stats.get('review_events', 'N/A')}")
    print(f"  丢弃事件数: {stats.get('discarded_events', 'N/A')}")
    print(f"  覆盖款号数: {stats.get('unique_style_ids', 'N/A')}")
    print(f"  分类分布: {stats.get('category_distribution', {})}")
except Exception as e:
    print(f"  (统计解析失败: {e})")
PYEOF

echo ""

# ==================== Step 3: 人工复核提示 ====================
REVIEW_FILE="${OUTPUT_DIR}/events_review.jsonl"
REVIEW_COUNT=0
if [ -f "$REVIEW_FILE" ]; then
    REVIEW_COUNT=$(wc -l < "$REVIEW_FILE" | tr -d ' ')
fi

if [ "$REVIEW_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}[Step 3/4] 发现 ${REVIEW_COUNT} 条待复核事件${NC}"
    echo ""
    echo "请手动检查以下文件，确认正确后补充到 events_passed.json 中："
    echo "  ${REVIEW_FILE}"
    echo ""
    echo "复核建议操作："
    echo "  1. 打开 ${REVIEW_FILE}"
    echo "  2. 确认无误的事件，复制到 ${OUTPUT_DIR}/events_passed.json 数组中"
    echo "  3. 错误或模糊的事件，直接删除或忽略"
    echo ""
    echo -e "${YELLOW}按 Enter 键继续（如果你已经复核完成，或想跳过复核直接入库）...${NC}"
    read -r
else
    echo -e "${GREEN}[Step 3/4] 没有待复核事件，跳过此步骤${NC}"
fi

# ==================== Step 4: 重建向量库 ====================
echo ""
echo -e "${YELLOW}[Step 4/4] 重建 ChromaDB 向量库...${NC}"

cd "$PROJECT_ROOT"
python "$PYTHON_SCRIPT" --use-filtered --skip-extraction

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  全量流水线执行完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "输出文件："
echo "  通过事件:    ${OUTPUT_DIR}/events_passed.json"
echo "  复核事件:    ${OUTPUT_DIR}/events_review.jsonl"
echo "  统计报告:    ${OUTPUT_DIR}/processing_stats.json"
echo "  邮件清单:    ${OUTPUT_DIR}/filtered_email_manifest.jsonl"
echo ""
echo "下一步建议："
echo "  1. 使用 email_term_rag_pipeline/src/rag_qa.py 测试术语检索"
echo "  2. 基于 events_passed.json 构造时间线推理微调数据集"
echo ""
