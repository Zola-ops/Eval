#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from standalone_evaluator_api import load_config, Evaluator
import pandas as pd

def test_batch():
    print("加载配置...")
    config = load_config('evaluator_config.json')
    model_config = config.get("config", {})
    
    api_url = "https://p6s8vpm3x5.coze.site/run"
    token = "pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"
    
    print("初始化评估器...")
    evaluator = Evaluator(
        model_config=model_config,
        keypoint_sp=config.get("sp", ""),
        keypoint_up=config.get("up", ""),
        scorer_sp=config.get("scorer_sp", ""),
        scorer_up=config.get("scorer_up", ""),
        api_url=api_url,
        token=token
    )
    
    print("读取Excel文件...")
    excel_path = "/Users/zhujiangdi/Desktop/考点摸底.xlsx"
    df = pd.read_excel(excel_path)
    print(f"总共 {len(df)} 条记录")
    
    # 只处理前3条
    df = df.head(3)
    print(f"测试模式：只处理前 {len(df)} 条记录")
    
    results = []
    for idx, row in df.iterrows():
        print(f"\n{'='*80}")
        print(f"处理第 {idx+1}/{len(df)} 条记录")
        print(f"{'='*80}")
        
        query = str(row['query']) if 'query' in row else ""
        answer = str(row['answer']) if 'answer' in row else ""
        
        print(f"问题: {query[:50]}...")
        print(f"回答: {answer[:50]}...")
        
        try:
            result = evaluator.evaluate(query, answer)
            results.append(result)
            print(f"✓ 第 {idx+1} 条评估完成")
            print(f"  考点数量: {result.get('keypoint_count', 0)}")
            print(f"  满足数量: {result.get('satisfied_count', 0)}")
            print(f"  评分: {result.get('score', 0)}")
        except Exception as e:
            print(f"✗ 第 {idx+1} 条评估失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # 保存结果
    if results:
        result_df = pd.DataFrame(results)
        output_path = "/Users/zhujiangdi/Desktop/test_result.xlsx"
        result_df.to_excel(output_path, index=False, engine='openpyxl')
        print(f"\n{'='*80}")
        print(f"✓ 测试结果已保存: {output_path}")
        print(f"{'='*80}")
    else:
        print("\n✗ 没有成功完成任何评估")

if __name__ == "__main__":
    test_batch()
