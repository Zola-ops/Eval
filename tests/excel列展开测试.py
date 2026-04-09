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
try:
    result = evaluator.evaluate(query, answer)

    # 按照新格式提取数据
    keypoint_list = result["keypoint_result"].get("key_point", [])
    scorer_keypoint_list = result["score_result"].get("key_point", [])
    keypoint_results = result["score_result"].get("key_point_result", [])

    flat_result = {
        "query": query,
        "answer": answer,
        # 考点生成部分
        "thinking": result["keypoint_result"].get("thinking", ""),
        "analysis": result["keypoint_result"].get("analysis", ""),
        "main_demand": result["keypoint_result"].get("main_demand", ""),
        "key_point": " | ".join(keypoint_list) if keypoint_list else "",
        "key_point_1": keypoint_list[0] if len(keypoint_list) > 0 else "",
        "key_point_2": keypoint_list[1] if len(keypoint_list) > 1 else "",
        "key_point_3": keypoint_list[2] if len(keypoint_list) > 2 else "",
        "key_point_4": keypoint_list[3] if len(keypoint_list) > 3 else "",
        "key_point_5": keypoint_list[4] if len(keypoint_list) > 4 else "",
        "key_point_6": keypoint_list[5] if len(keypoint_list) > 5 else "",
        # 评分部分
        "scorer_thinking": result["score_result"].get("thinking", ""),
        "scorer_analysis": result["score_result"].get("analysis", ""),
        "scorer_main_demand": result["score_result"].get("main_demand", ""),
        "scorer_key_point": " | ".join(scorer_keypoint_list) if scorer_keypoint_list else "",
        "scorer_key_point_1": scorer_keypoint_list[0] if len(scorer_keypoint_list) > 0 else "",
        "scorer_key_point_2": scorer_keypoint_list[1] if len(scorer_keypoint_list) > 1 else "",
        "scorer_key_point_3": scorer_keypoint_list[2] if len(scorer_keypoint_list) > 2 else "",
        "scorer_key_point_4": scorer_keypoint_list[3] if len(scorer_keypoint_list) > 3 else "",
        "scorer_key_point_5": scorer_keypoint_list[4] if len(scorer_keypoint_list) > 4 else "",
        "scorer_key_point_6": scorer_keypoint_list[5] if len(scorer_keypoint_list) > 5 else "",
        # key_point_result 展开为多列
        "keypoint_results_summary": f"{sum(1 for kp in keypoint_results if kp.get('satisfied'))}/{len(keypoint_results)}" if keypoint_results else "0/0",
        "keypoint_result_1": f"[{keypoint_results[0].get('satisfied', False)}] {keypoint_results[0].get('point', '')}" if len(keypoint_results) > 0 else "",
        "keypoint_result_1_satisfied": keypoint_results[0].get('satisfied', False) if len(keypoint_results) > 0 else "",
        "keypoint_result_1_evidence": keypoint_results[0].get('evidence', '') if len(keypoint_results) > 0 else "",
        "keypoint_result_2": f"[{keypoint_results[1].get('satisfied', False)}] {keypoint_results[1].get('point', '')}" if len(keypoint_results) > 1 else "",
        "keypoint_result_2_satisfied": keypoint_results[1].get('satisfied', False) if len(keypoint_results) > 1 else "",
        "keypoint_result_2_evidence": keypoint_results[1].get('evidence', '') if len(keypoint_results) > 1 else "",
        "keypoint_result_3": f"[{keypoint_results[2].get('satisfied', False)}] {keypoint_results[2].get('point', '')}" if len(keypoint_results) > 2 else "",
        "keypoint_result_3_satisfied": keypoint_results[2].get('satisfied', False) if len(keypoint_results) > 2 else "",
        "keypoint_result_3_evidence": keypoint_results[2].get('evidence', '') if len(keypoint_results) > 2 else "",
        "keypoint_result_4": f"[{keypoint_results[3].get('satisfied', False)}] {keypoint_results[3].get('point', '')}" if len(keypoint_results) > 3 else "",
        "keypoint_result_4_satisfied": keypoint_results[3].get('satisfied', False) if len(keypoint_results) > 3 else "",
        "keypoint_result_4_evidence": keypoint_results[3].get('evidence', '') if len(keypoint_results) > 3 else "",
        "keypoint_result_5": f"[{keypoint_results[4].get('satisfied', False)}] {keypoint_results[4].get('point', '')}" if len(keypoint_results) > 4 else "",
        "keypoint_result_5_satisfied": keypoint_results[4].get('satisfied', False) if len(keypoint_results) > 4 else "",
        "keypoint_result_5_evidence": keypoint_results[4].get('evidence', '') if len(keypoint_results) > 4 else "",
        "keypoint_result_6": f"[{keypoint_results[5].get('satisfied', False)}] {keypoint_results[5].get('point', '')}" if len(keypoint_results) > 5 else "",
        "keypoint_result_6_satisfied": keypoint_results[5].get('satisfied', False) if len(keypoint_results) > 5 else "",
        "keypoint_result_6_evidence": keypoint_results[5].get('evidence', '') if len(keypoint_results) > 5 else "",
        # 最终评分
        "score": result["score_result"].get("score", ""),
        "reason": result["score_result"].get("reason", ""),
        "timestamp": result["timestamp"]
    }

    # 创建DataFrame并保存
    result_df = pd.DataFrame([flat_result])

    print(f'\nExcel列名（共{len(result_df.columns)}列）:')
    for i, col in enumerate(result_df.columns, 1):
        print(f'  {i}. {col}')

    # 保存Excel
    output_excel = '/Users/zhujiangdi/Desktop/test_columns.xlsx'
    result_df.to_excel(output_excel, index=False, engine='openpyxl')
    print(f'\n✓ 测试Excel已保存: {output_excel}')

except Exception as e:
    print(f'评估失败: {e}')
    import traceback
    traceback.print_exc()
