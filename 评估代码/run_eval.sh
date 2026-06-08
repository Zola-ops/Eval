#!/bin/bash
# ========================================
# EVAL.V2 评估流水线
# ========================================
# 用法: bash run_eval.sh [任务名]
# ========================================

set -e
cd "$(dirname "$0")"

TASK="${1:-评估-pc百度}"
INPUT="$HOME/Desktop/${TASK}.xlsx"

echo "=========================================="
echo "🚀 EVAL.V2 评估流水线: $TASK"
echo "=========================================="

if [ ! -f "$INPUT" ]; then
    echo "❌ 找不到输入文件: $INPUT"
    exit 1
fi

# Step 0: 搜索增强
echo ""
echo "📋 Step 0: 搜索增强..."
python3 step0_enrich.py "$INPUT" --task "$TASK"

# 找到 step0 最新输出
STEP0_OUT=$(ls -t ../评估数据/${TASK}-step0-*.xlsx 2>/dev/null | head -1)
if [ -z "$STEP0_OUT" ]; then
    echo "⚠️  未找到 step0 输出，使用原始输入"
    STEP0_OUT="$INPUT"
fi
echo "   Step 0 输出: $STEP0_OUT"

# Step 1: 三模型考点生成（并行跑3个）
echo ""
echo "📋 Step 1: 考点生成（3个模型）..."
for cfg in models/deepseek_v4_flash.py models/kimi_k2_5.py models/minimax_m2_7.py; do
    name=$(basename "$cfg" .py)
    echo "   启动 $name ..."
    python3 step1_gen.py --config "$cfg" --task "$TASK" "$STEP0_OUT" &
done
wait
echo "   ✅ 3个模型全部完成"

# Step 2: 置信度评估
echo ""
echo "📋 Step 2: 置信度评估..."
python3 step2_summary.py --task "$TASK"

# Step 3: 评分+分类
echo ""
echo "📋 Step 3: 评分+分类..."
python3 step3_score.py --task "$TASK"

echo ""
echo "=========================================="
echo "✅ 全部完成!"
echo "   评估数据: ../评估数据/"
echo "=========================================="
