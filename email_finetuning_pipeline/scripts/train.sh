#!/bin/bash
# 一键训练脚本：时间线推理微调 (LLaMA-Factory + LoRA)

set -e

echo "=========================================="
echo "  Timeline Reasoning LoRA 训练脚本"
echo "=========================================="

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 检查数据文件
check_data() {
    echo -e "${YELLOW}检查数据文件...${NC}"

    TRAIN_FILE="../datasets/timeline_train.jsonl"
    VAL_FILE="../datasets/timeline_val.jsonl"

    if [ ! -f "$TRAIN_FILE" ]; then
        echo -e "${RED}错误: 找不到训练数据 $TRAIN_FILE${NC}"
        echo "请先运行数据集构造脚本:"
        echo "  python src/build_timeline_dataset.py --input datasets/timeline_gold_samples.jsonl --augment --output datasets/timeline_augmented.jsonl"
        echo "  python src/build_timeline_dataset.py --input datasets/timeline_augmented.jsonl --finalize --val-ratio 0.1 --output datasets/timeline_train.jsonl"
        exit 1
    fi

    if [ -f "$VAL_FILE" ]; then
        VAL_COUNT=$(wc -l < "$VAL_FILE")
        echo -e "${GREEN}✓ 验证集: $VAL_COUNT 条${NC}"
    else
        echo -e "${YELLOW}⚠ 未找到独立验证集，将使用 val_size 从训练集自动切分${NC}"
    fi

    TRAIN_COUNT=$(wc -l < "$TRAIN_FILE")
    echo -e "${GREEN}✓ 训练集: $TRAIN_COUNT 条${NC}"
    echo ""
}

# 安装依赖
install_deps() {
    echo -e "${YELLOW}检查依赖...${NC}"

    if ! command -v llamafactory-cli &> /dev/null; then
        echo "安装 LLaMA-Factory..."
        pip install llama-factory
    fi

    echo -e "${GREEN}✓ 依赖检查完成${NC}"
    echo ""
}

# 执行训练
train() {
    echo -e "${YELLOW}开始训练...${NC}"

    CONFIG_FILE="../configs/llama_factory_timeline_lora.yaml"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}错误: 找不到配置文件 $CONFIG_FILE${NC}"
        exit 1
    fi

    # 复制数据到 LLaMA-Factory 数据目录
    mkdir -p data
    cp "$TRAIN_FILE" data/
    if [ -f "$VAL_FILE" ]; then
        cp "$VAL_FILE" data/
    fi
    cp ../configs/dataset_info.json data/

    echo "使用配置: $CONFIG_FILE"
    llamafactory-cli train "$CONFIG_FILE"
}

# 主流程
main() {
    check_data
    install_deps
    train

    echo ""
    echo -e "${GREEN}=========================================="
    echo "  训练完成!"
    echo "  权重目录: outputs/timeline-reasoning-lora"
    echo "==========================================${NC}"
}

# 帮助信息
show_help() {
    echo "用法: ./train.sh"
    echo ""
    echo "说明:"
    echo "  本脚本自动检查 timeline_train.jsonl 和 timeline_val.jsonl，"
    echo "  并使用 LLaMA-Factory 的 llama_factory_timeline_lora.yaml 配置启动 LoRA 训练。"
    echo ""
    echo "前置条件:"
    echo "  1. datasets/timeline_train.jsonl 已生成"
    echo "  2. DEEPSEEK_API_KEY 已设置（如需重新生成增强数据）"
}

if [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    show_help
    exit 0
fi

main
