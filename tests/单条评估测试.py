#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from standalone_evaluator_api import load_config, Evaluator
import pandas as pd
import json

print("加载配置...")
config = load_config('evaluator_config.json')
model_config = config.get("config", {})

print("初始化评估器...")
api_url = "https://p6s8vpm3x5.coze.site/run"
token = "pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"

model_config["max_completion_tokens"] = 20000

evaluator = Evaluator(
    model_config=model_config,
    keypoint_sp=config.get("sp", ""),
    keypoint_up=config.get("up", ""),
    scorer_sp=config.get("scorer_sp", ""),
    scorer_up=config.get("scorer_up", ""),
    api_url=api_url,
    token=token
)

print("读取Excel...")
df = pd.read_excel("/Users/zhujiangdi/Desktop/考点摸底.xlsx")
print(f"总记录数: {len(df)}")

# 只评估第一条
row = df.iloc[0]
query = str(row['query'])
answer = str(row['answer'])

print(f"\n{'='*80}")
print(f"评估第 1 条记录")
print(f"{'='*80}")
print(f"问题: {query[:100]}...")
print(f"回答: {answer[:100]}...")

print("\n开始评估...")
try:
    result = evaluator.evaluate(query, answer)
    print(f"\n✓ 评估完成!")
    print(f"  评分: {result['score_result'].get('score')}")
    print(f"  理由: {result['score_result'].get('reason')[:200]}...")
    print(f"  考点数: {len(result['keypoint_result'].get('key_point', []))}")
    print(f"  满足数: {sum(1 for kp in result['score_result'].get('key_point_result', []) if kp.get('satisfied'))}")

    # 保存结果
    with open('/Users/zhujiangdi/Desktop/test_one_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: /Users/zhujiangdi/Desktop/test_one_result.json")

except Exception as e:
    print(f"\n✗ 评估失败: {str(e)}")
    import traceback
    traceback.print_exc()
