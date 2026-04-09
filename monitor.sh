#!/bin/bash
echo "=== 评估进度监控 ==="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 检查进程
PID=$(pgrep -f "run_batch_eval.py")
if [ -n "$PID" ]; then
    echo "✅ 评估进程运行中 (PID: $PID)"
    ps -p $PID -o pid,state,etime 2>/dev/null
else
    echo "⏹️ 评估进程未运行"
fi
echo ""

# 检查进度
if [ -f "/Users/zhujiangdi/Desktop/evaluator_package/progress.json" ]; then
    COMPLETED=$(grep -o '"completed": [0-9]*' /Users/zhujiangdi/Desktop/evaluator_package/progress.json | grep -o '[0-9]*')
    echo "📊 进度: $COMPLETED / 63 条 ($(echo "scale=1; $COMPLETED*100/63" | bc)%)"
else
    echo "📊 进度文件尚未生成"
fi
echo ""

# 检查输出
if [ -f "/Users/zhujiangdi/Desktop/0401_豆包评估结果.xlsx" ]; then
    echo "📁 输出文件已生成"
    ls -lh /Users/zhujiangdi/Desktop/0401_豆包评估结果.xlsx
else
    echo "⏳ 输出文件尚未生成"
fi
