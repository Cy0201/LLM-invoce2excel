#!/bin/bash
# ══════════════════════════════════════════════════════════
#  票据智能提取台 v7 · 启动脚本
#  同一套 Anthropic Messages 协议：改下面三个变量即可在
#  内网网关 与 Claude 官方端点 之间切换，代码零改动。
# ══════════════════════════════════════════════════════════
cd "$(dirname "$0")"

# ── AI 网关（默认：内网）─────────────────────────────────
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
export CLAUDE_MODEL="${CLAUDE_MODEL:-}"
# 用 Claude 对照测试时：
#   export ANTHROPIC_BASE_URL="https://api.anthropic.com"
#   export ANTHROPIC_AUTH_TOKEN="sk-ant-…"
#   export CLAUDE_MODEL="claude-sonnet-4-6"

# ── 质量 / 速度旋钮（均有合理默认，可按需覆盖）───────────
export SCAN_MAX_SIDE="${SCAN_MAX_SIDE:-2000}"       # 扫描页送模型的长边像素
export REPAIR_IMG_SIDE="${REPAIR_IMG_SIDE:-2400}"   # 自动复核时的更高清长边
export TEXT_WORKERS="${TEXT_WORKERS:-8}"            # 电子件文本请求并发
export VISION_WORKERS="${VISION_WORKERS:-3}"        # 扫描件视觉请求并发
export MAX_TOKENS_CAP="${MAX_TOKENS_CAP:-16384}"    # 单页常规输出上限
export HARD_TOKENS_CAP="${HARD_TOKENS_CAP:-32768}"  # 截断升额后的硬上限
export REPAIR_MAX="${REPAIR_MAX:-6}"                # 每次任务最多自动复核的记录数
export AI_TIMEOUT="${AI_TIMEOUT:-300}"              # 单请求超时(秒)

PORT="${PORT:-5000}"

echo "══════════════════════════════════════════════"
echo "  票据智能提取台 v7"
echo "  网关: $ANTHROPIC_BASE_URL"
echo "  模型: $CLAUDE_MODEL"
echo "  http://localhost:$PORT"
echo "══════════════════════════════════════════════"
exec python3 app.py --port "$PORT" "$@"
