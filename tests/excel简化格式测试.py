#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from 智谱评估 import Evaluator, flatten_result
import pandas as pd
from datetime import datetime

print('初始化评估器...')
evaluator = Evaluator(config_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), '评估配置.json'))

print('读取Excel...')
df = pd.read_excel('/Users/zhujiangdi/Desktop/考点摸底.xlsx')
row = df.iloc[0]
query = str(row['query'])
answer = str(row['answer'])

print(f'\n评估第一条记录...')
try:
    result = evaluator.evaluate(query, answer)

    # 使用 flatten_result 展开字段
    flat = flatten_result(result)
    flat_result = {
        "query": query,
        "answer": answer,
        **flat,
        "evaluated_at": datetime.now().isoformat()
    }

    # 创建DataFrame并保存
    result_df = pd.DataFrame([flat_result])

    print(f'\nExcel列名（共{len(result_df.columns)}列）:')
    for i, col in enumerate(result_df.columns, 1):
        print(f'  {i}. {col}')

    # 保存Excel
    output_excel = '/Users/zhujiangdi/Desktop/test_columns_simple.xlsx'
    result_df.to_excel(output_excel, index=False, engine='openpyxl')
    print(f'\n测试Excel已保存: {output_excel}')
    print(f'\nkeypoint_results 示例内容:')
    kr = flat_result.get('keypoint_results', '')
    print(kr[:200] + '...' if len(kr) > 200 else kr)

except Exception as e:
    print(f'评估失败: {e}')
    import traceback
    traceback.print_exc()
