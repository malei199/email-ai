#!/bin/bash
#
# 服装术语 RAG 全量构建一键脚本
# 功能：提取 PDF -> 质量过滤 -> 重建 ChromaDB
#
# 使用方法：
#   ./email_term_rag_pipeline/scripts/run_term_pipeline.sh
#
# 说明：
#   本脚本会从 data/pdf/汉英英汉服装分类词汇.pdf 中提取全部 491 页术语，
#   过滤去重后构建向量知识库。PDF 提取约需 8-12 分钟，支持断点恢复。
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PDF_FILE="${PROJECT_ROOT}/data/pdf/汉英英汉服装分类词汇.pdf"
EXTRACT_SCRIPT="${PROJECT_ROOT}/email_term_rag_pipeline/src/extract_pdf_terms.py"
BUILD_SCRIPT="${PROJECT_ROOT}/email_term_rag_pipeline/src/build_term_kb.py"
OUTPUT_DIR="${PROJECT_ROOT}/email_term_rag_pipeline/output"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  服装术语 RAG 全量构建流水线${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==================== 前置检查 ====================

if [ ! -f "$PDF_FILE" ]; then
    echo -e "${RED}[ERROR] PDF 文件不存在: ${PDF_FILE}${NC}"
    exit 1
fi

if [ ! -f "$EXTRACT_SCRIPT" ]; then
    echo -e "${RED}[ERROR] 提取脚本不存在: ${EXTRACT_SCRIPT}${NC}"
    exit 1
fi

if [ ! -f "$BUILD_SCRIPT" ]; then
    echo -e "${RED}[ERROR] 建库脚本不存在: ${BUILD_SCRIPT}${NC}"
    exit 1
fi

echo -e "${GREEN}[CHECK] 前置检查通过${NC}"
echo ""

# ==================== Step 1: PDF 提取 ====================
FILTERED_JSON="${OUTPUT_DIR}/filtered_terms.json"

if [ -f "$FILTERED_JSON" ]; then
    echo -e "${YELLOW}[Step 1/2] 发现已提取的过滤结果${NC}"
    echo "  ${FILTERED_JSON}"
    echo ""
    echo "是否跳过 PDF 重新提取，直接建库？"
    echo "  输入 y 跳过提取，输入 n 重新提取（约 8-12 分钟）"
    read -r -p "跳过提取? [y/N]: " SKIP_EXTRACT
    echo ""
    
    if [[ ! "$SKIP_EXTRACT" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}[Step 1/2] 开始重新提取 PDF...${NC}"
        echo -e "${BLUE}  提示：491 页 PDF，完整提取约需 8-12 分钟${NC}"
        echo ""
        cd "$PROJECT_ROOT"
        python "$EXTRACT_SCRIPT"
    else
        echo -e "${GREEN}[Step 1/2] 跳过提取，使用已有结果${NC}"
    fi
else
    echo -e "${YELLOW}[Step 1/2] 开始提取 PDF 术语...${NC}"
    echo -e "${BLUE}  提示：491 页 PDF，完整提取约需 8-12 分钟${NC}"
    echo -e "${BLUE}  如果中断，可重新运行本脚本或执行：${NC}"
    echo -e "${BLUE}    python email_term_rag_pipeline/src/extract_pdf_terms.py --resume${NC}"
    echo ""
    cd "$PROJECT_ROOT"
    python "$EXTRACT_SCRIPT"
fi

# 检查提取结果
if [ ! -f "$FILTERED_JSON" ]; then
    echo -e "${RED}[ERROR] 提取失败，未生成过滤结果: ${FILTERED_JSON}${NC}"
    exit 1
fi

EXTRACT_COUNT=$(python3 -c "import json; print(len(json.load(open('${FILTERED_JSON}'))))")
echo -e "${GREEN}[Step 1/2] 术语提取完成，共 ${EXTRACT_COUNT} 条${NC}"
echo ""

# ==================== Step 2: 建库 ====================
echo -e "${YELLOW}[Step 2/2] 重建 ChromaDB 术语知识库...${NC}"
cd "$PROJECT_ROOT"
python "$BUILD_SCRIPT" --input "$FILTERED_JSON"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  术语 RAG 构建完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "输出文件："
echo "  原始提取:    ${OUTPUT_DIR}/extracted_terms.json"
echo "  过滤结果:    ${OUTPUT_DIR}/filtered_terms.json"
echo "  提取统计:    ${OUTPUT_DIR}/extract_stats.json"
echo "  建库统计:    ${OUTPUT_DIR}/term_kb_stats.json"
echo ""
echo "后续步骤："
echo "  1. 测试检索: python email_term_rag_pipeline/src/rag_qa.py"
echo "  2. 集成双轨 RAG: 将术语 RAG (clothing_terms) 与邮件 RAG (email_events) 结合"
echo ""
