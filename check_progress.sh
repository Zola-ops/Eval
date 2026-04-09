#!/bin/bash
LOG_FILE="/Users/zhujiangdi/Desktop/evaluator_package/batch_eval_0401.log"
OUTPUT_FILE="/Users/zhujiangdi/Desktop/0401_豆包评估结果.xlsx"

echo "=== 评估进度检查 ==="
echo ""

# 检查进程
PID=$(ps aux | grep "豆包评估.py" | grep -v grep | awk '{print $2}')
if [ -n "$PID" ]; then
    echo "✅ 评估进程运行中 (PID: $PID)"
else
    echo "⏹️  评估进程未运行"
fi
echo ""

# 统计进度
if [ -f "$LOG_FILE" ]; then
    TOTAL=$(grep -c "^\[" "$LOG_FILE" 2>/dev/null || echo "0")
    COMPLETED=$(grep -c "完成$" "$LOG_FILE" 2>/dev/null || echo "0")
    echo "📊 进度: $COMPLETED / 63 条"
    echo ""
    echo "--- 最近5条记录 ---"
    grep "^\[" "$LOG_FILE" | tail -5
fi
echo ""

# 检查输出文件
if [ -f "$OUTPUT_FILE" ]; then
    echo "📁 输出文件已生成: $OUTPUT_FILE"
    ls -lh "$OUTPUT_FILE"
else
    echo "⏳ 输出文件尚未生成"
fi
