#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from standalone_evaluator_api import load_config, Evaluator
import pandas as pd
import json

print('加载配置...')
config = load_config('evaluator_config.json')
model_config = config.get('config', {})
model_config['max_completion_tokens'] = 2000

print('初始化评估器...')
api_url = 'https://p6s8vpm3x5.coze.site/run'
token = 'pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm'

evaluator = Evaluator(
    model_config=model_config,
    keypoint_sp=config.get('sp', ''),
    keypoint_up=config.get('up', ''),
    scorer_sp=config.get('scorer_sp', ''),
    scorer_up=config.get('scorer_up', ''),
    api_url=api_url,
    token=token
)

print('读取Excel...')
df = pd.read_excel('/Users/zhujiangdi/Desktop/考点摸底.xlsx')
row = df.iloc[0]
query = str(row['query'])
answer = str(row['answer'])

print(f'\n评估第一条记录...')
print(f'Query: {query[:50]}...')
print(f'Answer: {answer[:50]}...')

try:
    result = evaluator.evaluate(query, answer)

    # 按照期望格式提取数据
    output = {
        'query': query,
        'answer': answer,
        'thinking': result['keypoint_result'].get('thinking', ''),
        'analysis': result['keypoint_result'].get('analysis', ''),
        'main_demand': result['keypoint_result'].get('main_demand', ''),
        'key_point': result['keypoint_result'].get('key_point', []),
        'scorer_thinking': result['score_result'].get('thinking', ''),
        'scorer_analysis': result['score_result'].get('analysis', ''),
        'scorer_main_demand': result['score_result'].get('main_demand', ''),
        'scorer_key_point': result['score_result'].get('key_point', []),
        'key_point_result': result['score_result'].get('key_point_result', []),
        'score': result['score_result'].get('score', ''),
        'reason': result['score_result'].get('reason', '')
    }

    print(f'\n输出字段:')
    for key in output.keys():
        value = output[key]
        if isinstance(value, list):
            print(f'  {key}: (列表，{len(value)}项)')
        elif isinstance(value, str) and len(value) > 50:
            print(f'  {key}: {value[:50]}...')
        else:
            print(f'  {key}: {value}')

    # 保存为JSON查看完整格式
    with open('/Users/zhujiangdi/Desktop/test_format.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n完整结果已保存到: /Users/zhujiangdi/Desktop/test_format.json')

except Exception as e:
    print(f'评估失败: {e}')
    import traceback
    traceback.print_exc()
