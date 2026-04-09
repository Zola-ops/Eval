#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量评估执行脚本 - 带进度保存和恢复功能
"""

import os
import sys
import json
import time
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, '/Users/zhujiangdi/Desktop/evaluator_package')

from 豆包评估 import Evaluator, load_excel_data, flatten_result, save_excel_data

INPUT_FILE = '/Users/zhujiangdi/Desktop/0401.xlsx'
OUTPUT_FILE = '/Users/zhujiangdi/Desktop/0401_豆包评估结果.xlsx'
PROGRESS_FILE = '/Users/zhujiangdi/Desktop/evaluator_package/progress.json'

def load_progress():
    """加载进度"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'completed': 0, 'results': []}

def save_progress(completed, results):
    """保存进度"""
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump({'completed': completed, 'results': results}, f, ensure_ascii=False, indent=2)

def main():
    print(f"{'='*60}")
    print(f"批量评估任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # 创建评估器
    evaluator = Evaluator(config_file='豆包评估配置.json')
    
    # 加载数据
    data = load_excel_data(INPUT_FILE)
    total = len(data)
    print(f"加载了 {total} 条数据\n")
    
    # 加载进度
    progress = load_progress()
    start_idx = progress['completed']
    results = progress['results']
    
    if start_idx > 0:
        print(f"从第 {start_idx + 1} 条继续评估（已跳过 {start_idx} 条）\n")
    
    session_history = {}
    
    for idx in range(start_idx, total):
        item = data[idx]
        query = item.get('query', item.get('问题', ''))
        answer = item.get('answer', item.get('回答', ''))
        session_id = item.get('session_id', item.get('session', None))
        
        if not query or not answer:
            print(f"[{idx+1}/{total}] ⚠️ 跳过：缺少query或answer")
            continue
        
        print(f"[{idx+1}/{total}] 评估: {query[:50]}...")
        
        try:
            # 获取上下文
            context = session_history.get(session_id, []) if session_id else None
            
            # 评估
            result = evaluator.evaluate(
                query=query,
                answer=answer,
                date=item.get('date', None),
                demand=item.get('demand', None),
                context=context
            )
            
            # 保存到历史
            if session_id:
                if session_id not in session_history:
                    session_history[session_id] = []
                session_history[session_id].append({
                    'query': query,
                    'answer': answer,
                    'keypoints': result['keypoint_generation']
                })
            
            # 汇总结果
            flat = flatten_result(result)
            result_item = {
                **item,
                **flat,
                'evaluated_at': datetime.now().isoformat()
            }
            results.append(result_item)
            
            print(f"✅ 完成 - 得分: {result['scoring'].get('score', 'N/A')}")
            
            # 保存进度
            save_progress(idx + 1, results)
            
            # 延迟避免速率限制
            time.sleep(0.5)
            
        except Exception as e:
            print(f"❌ 失败: {str(e)}")
            # 保存错误信息
            results.append({
                **item,
                'error': str(e),
                'evaluated_at': datetime.now().isoformat()
            })
            save_progress(idx + 1, results)
    
    # 保存最终结果
    print(f"\n{'='*60}")
    print(f"评估完成！正在保存结果...")
    print(f"{'='*60}\n")
    
    save_excel_data(results, OUTPUT_FILE)
    
    # 清理进度文件
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    
    print(f"结果保存到: {OUTPUT_FILE}")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
