#!/bin/bash
# =============================================================================
# vLLM 模型服务启动脚本 (vLLM 0.19.1)
# 
# 说明:
#   - 基于 A6000 48GB 显存设计
#   - 采用单 vLLM 实例 + 多 LoRA 动态切换方案
#   - V3/V2/V1 三个模型共享同一个基座 (Qwen2.5-7B-Instruct)
#   - 通过请求时的 model 参数切换: "v3", "v2", "v1"
#
# 硬件要求:
#   - NVIDIA GPU, Compute Capability >= 8.0
#   - 显存 >= 48GB (A6000/A100-40GB 可能不够)
#   - CUDA 驱动 >= 525 (支持 CUDA 12.x)
#
# 依赖:
#   - vllm >= 0.19.1
#   - PyTorch >= 2.5.0 (cu124)
#
# 用法:
    #c d /openbayes/home
    # chmod +x start_vllm_servers.sh
#   ./start_vllm_servers.sh [start|stop|status|restart|logs]

#### pgrep -a "vllm"
#
# 示例:
#   ./start_vllm_servers.sh start    # 启动服务
#   ./start_vllm_servers.sh stop     # 停止服务
#   ./start_vllm_servers.sh status   # 查看状态
#   ./start_vllm_servers.sh logs     # 查看日志
# =============================================================================

set -e

# ---------------------------------------------------------------------------
# 配置项
# ---------------------------------------------------------------------------

# 基座模型路径 (本地 HuggingFace cache)
HF_HOME="${HF_HOME:-/openbayes/home/hub}"
MODEL_NAME="Qwen2.5-7B-Instruct"
SNAPSHOT_DIR=$(ls -d "$HF_HOME/models--Qwen--${MODEL_NAME}/snapshots/"* 2>/dev/null | head -1)

if [ -z "$SNAPSHOT_DIR" ]; then
    echo "错误: 找不到基座模型缓存"
    echo "路径: $HF_HOME/models--Qwen--${MODEL_NAME}/snapshots/"
    echo "请确认模型已下载，或设置 HF_HOME 环境变量"
    exit 1
fi

BASE_MODEL="$SNAPSHOT_DIR"

# LoRA 权重路径 (训练输出)
LORA_ROOT="${LORA_ROOT:-/openbayes/home/LlamaFactory/outputs}"

V3_LORA="$LORA_ROOT/dpo-v3/checkpoint-225"
V2_LORA="$LORA_ROOT/dpo-v2/checkpoint-243"
V1_LORA="$LORA_ROOT/sft-v1/checkpoint-189"

# 服务配置
PORT="${VLLM_PORT:-8001}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.90}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-32768}"
MAX_LORA_RANK="${VLLM_MAX_LORA_RANK:-64}"

# 日志
LOG_DIR="${VLLM_LOG_DIR:-/openbayes/home/vllm_logs}"
LOG_FILE="$LOG_DIR/vllm_server.log"
PID_FILE="$LOG_DIR/vllm_server.pid"

# ---------------------------------------------------------------------------
# 颜色输出
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_err() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_env() {
    log_info "检查环境..."
    
    # 检查 CUDA
    if ! command -v nvidia-smi &> /dev/null; then
        log_err "nvidia-smi 未找到，请确认 CUDA 驱动已安装"
        exit 1
    fi
    
    # 检查 GPU
    if ! nvidia-smi &> /dev/null; then
        log_err "无法访问 GPU，请确认 NVIDIA 驱动正常"
        exit 1
    fi
    
    # 检查 vllm
    if ! command -v vllm &> /dev/null; then
        log_err "vllm 命令未找到，请安装: pip install vllm==0.19.1"
        exit 1
    fi
    
    # 检查模型文件
    if [ ! -f "$BASE_MODEL/config.json" ]; then
        log_err "基座模型文件不完整: $BASE_MODEL"
        exit 1
    fi
    
    # 检查 LoRA 权重
    for lora_path in "$V3_LORA" "$V2_LORA" "$V1_LORA"; do
        if [ ! -f "$lora_path/adapter_config.json" ]; then
            log_err "LoRA 权重不完整: $lora_path"
            exit 1
        fi
    done
    
    # 创建日志目录
    mkdir -p "$LOG_DIR"
    
    log_ok "环境检查通过"
    echo ""
}

show_config() {
    echo "=========================================="
    echo "  vLLM 服务配置"
    echo "=========================================="
    echo "  基座模型: $BASE_MODEL"
    echo "  V3 LoRA:  $V3_LORA"
    echo "  V2 LoRA:  $V2_LORA"
    echo "  V1 LoRA:  $V1_LORA"
    echo "  服务端口: $PORT"
    echo "  GPU 利用率: $GPU_MEM_UTIL"
    echo "  Max Model Len: $MAX_MODEL_LEN"
    echo "  Max LoRA Rank: $MAX_LORA_RANK"
    echo "  日志文件: $LOG_FILE"
    echo "=========================================="
    echo ""
}

start_server() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        log_warn "服务已在运行 (PID: $(cat "$PID_FILE"))"
        return 0
    fi
    
    check_env
    show_config
    
    log_info "启动 vLLM 服务..."
    log_info "命令: vllm serve <base_model> --lora-modules v3=<v3_path> v2=<v2_path> v1=<v1_path> ..."
    echo ""
    
    # 启动 vLLM (后台运行)
    nohup vllm serve "$BASE_MODEL" \
        --enable-lora \
        --lora-modules \
            v3="$V3_LORA" \
            v2="$V2_LORA" \
            v1="$V1_LORA" \
        --max-lora-rank "$MAX_LORA_RANK" \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --max-model-len "$MAX_MODEL_LEN" \
        --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    
    SERVER_PID=$!
    echo $SERVER_PID > "$PID_FILE"
    
    log_info "服务进程 PID: $SERVER_PID"
    log_info "等待服务就绪 (约 30-60 秒)..."
    
    # 等待服务启动
    for i in {1..300}; do
        if curl -s "http://localhost:$PORT/v1/models" > /dev/null 2>&1; then
            echo ""
            log_ok "服务已就绪!"
            echo ""
            show_status
            return 0
        fi
        
        # 检查进程是否还在
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            echo ""
            log_err "服务进程已退出，查看日志:"
            tail -50 "$LOG_FILE"
            rm -f "$PID_FILE"
            return 1
        fi
        
        echo -n "."
        sleep 1
    done
    
    echo ""
    log_err "服务启动超时，查看日志: $LOG_FILE"
    return 1
}

stop_server() {
    if [ ! -f "$PID_FILE" ]; then
        log_warn "PID 文件不存在，尝试查找并停止 vllm 进程..."
        pkill -f "vllm serve" || true
        return 0
    fi
    
    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        log_info "停止服务 (PID: $PID)..."
        kill "$PID"
        
        # 等待进程退出
        for i in {1..30}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                log_ok "服务已停止"
                rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done
        
        # 强制终止
        log_warn "强制终止进程..."
        kill -9 "$PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    else
        log_warn "进程已不存在"
        rm -f "$PID_FILE"
    fi
}

show_status() {
    echo "=========================================="
    echo "  服务状态"
    echo "=========================================="
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo -e "  运行状态: ${GREEN}运行中${NC}"
            echo "  进程 PID: $PID"
            echo "  服务地址: http://localhost:$PORT"
            echo "  日志文件: $LOG_FILE"
            
            # 显存占用
            echo ""
            echo "  GPU 显存占用:"
            nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | awk '{printf "    %.1f GB / %.1f GB (%.1f%%)\n", $1/1024, $2/1024, $1/$2*100}'
            
            # 已加载模型
            echo ""
            echo "  已加载模型:"
            curl -s "http://localhost:$PORT/v1/models" 2>/dev/null | python3 -m json.tool 2>/dev/null | grep '"id"' | sed 's/.*"id": "\(.*\)".*/    \1/' || echo "    (无法获取)"
        else
            echo -e "  运行状态: ${RED}已停止${NC} (PID 文件残留)"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "  运行状态: ${YELLOW}未运行${NC}"
    fi
    
    echo "=========================================="
}

show_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        log_warn "日志文件不存在: $LOG_FILE"
        return 1
    fi
    
    echo "=========================================="
    echo "  最近 100 行日志"
    echo "=========================================="
    tail -100 "$LOG_FILE"
}

test_models() {
    log_info "测试模型加载..."
    
    if ! curl -s "http://localhost:$PORT/v1/models" > /dev/null 2>&1; then
        log_err "服务未运行，请先启动"
        return 1
    fi
    
    echo ""
    echo "已加载模型列表:"
    curl -s "http://localhost:$PORT/v1/models" | python3 -m json.tool 2>/dev/null || true
    
    echo ""
    log_info "测试 V3 调度器..."
    curl -s "http://localhost:$PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "v3",
            "messages": [{"role": "user", "content": "8859114 进度怎么样"}],
            "max_tokens": 100,
            "temperature": 0.1
        }' | python3 -m json.tool 2>/dev/null || echo "请求失败"
    
    echo ""
    log_info "测试 V2 查询引擎..."
    curl -s "http://localhost:$PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "v2",
            "messages": [{"role": "user", "content": "我跟的款号有哪些"}],
            "max_tokens": 200,
            "temperature": 0.3
        }' | python3 -m json.tool 2>/dev/null || echo "请求失败"
    
    echo ""
    log_info "测试 V1 时间线生成..."
    curl -s "http://localhost:$PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "v1",
            "messages": [{"role": "user", "content": "整理 8859114 的时间线"}],
            "max_tokens": 800,
            "temperature": 0.3
        }' | python3 -m json.tool 2>/dev/null || echo "请求失败"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

show_help() {
    cat << EOF
用法: $0 [命令]

命令:
    start      启动 vLLM 服务 (单实例 + 多 LoRA)
    stop       停止服务
    restart    重启服务
    status     查看服务状态
    logs       查看日志
    test       测试模型加载和推理
    help       显示帮助

环境变量:
    HF_HOME              HuggingFace 缓存目录 (默认: /openbayes/home/hub)
    LORA_ROOT            LoRA 权重根目录 (默认: /openbayes/home/LlamaFactory/outputs)
    VLLM_PORT            服务端口 (默认: 8001)
    VLLM_GPU_MEM_UTIL    GPU 显存利用率 (默认: 0.90)
    VLLM_MAX_MODEL_LEN   最大序列长度 (默认: 8192)
    VLLM_MAX_LORA_RANK   最大 LoRA rank (默认: 64)
    VLLM_LOG_DIR         日志目录 (默认: /tmp/vllm_logs)

说明:
    本脚本采用单 vLLM 实例 + 多 LoRA 动态切换方案。
    三个模型 (v3/v2/v1) 共享同一个基座，通过请求时的 model 参数切换。
    
    推理时指定 model:
        - "v3" -> V3 调度器 (意图识别 + 路由)
        - "v2" -> V2 查询引擎 (多轮工具调用)
        - "v1" -> V1 时间线生成 (结构化报告)

示例:
    $0 start
    $0 status
    $0 test
    $0 stop

EOF
}

# 解析命令
case "${1:-help}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 2
        start_server
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    test)
        test_models
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_err "未知命令: $1"
        show_help
        exit 1
        ;;
esac
