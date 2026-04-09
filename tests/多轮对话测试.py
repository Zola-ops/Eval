#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试上下文感知评估功能
演示如何使用 session_id 和 query_id 进行多轮评估
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from standalone_evaluator_api import load_config, Evaluator

def test_single_session():
    """测试单session多轮评估"""
    print("=" * 80)
    print("测试1: 单Session多轮评估")
    print("=" * 80)

    # 初始化评估器
    config = load_config('evaluator_config.json')
    model_config = config.get("config", {})

    evaluator = Evaluator(
        model_config=model_config,
        keypoint_sp=config.get("sp", ""),
        keypoint_up=config.get("up", ""),
        scorer_sp=config.get("scorer_sp", ""),
        scorer_up=config.get("scorer_up", ""),
        api_url="https://p6s8vpm3x5.coze.site/run",
        token="pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"
    )

    # 第1轮: 独立问题
    print("\n--- 第1轮 ---")
    result1 = evaluator.evaluate(
        query="什么是Python?",
        answer="Python是一种高级编程语言,由Guido van Rossum于1991年创建。它具有简洁的语法和强大的标准库,广泛应用于Web开发、数据分析、人工智能等领域。",
        session_id="test_session_1",
        query_id="q_001"
    )
    print(f"得分: {result1['score_result']['score']}")

    # 第2轮: 基于第1轮的追问
    print("\n--- 第2轮 (参考第1轮) ---")
    result2 = evaluator.evaluate(
        query="那它有什么特点?",
        answer="Python的特点包括:1)语法简洁易读;2)跨平台;3)丰富的第三方库;4)动态类型;5)解释型语言;6)支持多种编程范式(面向对象、函数式等)。",
        session_id="test_session_1",
        query_id="q_002"
    )
    print(f"得分: {result2['score_result']['score']}")

    # 第3轮: 继续追问
    print("\n--- 第3轮 (参考第1、2轮) ---")
    result3 = evaluator.evaluate(
        query="能举个例子说明它的应用吗?",
        answer="当然!例如在数据分析领域,使用Pandas库可以轻松处理CSV文件:\n```python\nimport pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df.head())\n```\n这段代码会读取CSV文件并显示前5行数据。",
        session_id="test_session_1",
        query_id="q_003"
    )
    print(f"得分: {result3['score_result']['score']}")

    print("\n✓ 测试1完成")
    print(f"Session历史: {len(evaluator.session_history['test_session_1'])} 轮")

def test_multiple_sessions():
    """测试多session独立评估"""
    print("\n" + "=" * 80)
    print("测试2: 多Session独立评估")
    print("=" * 80)

    # 初始化评估器
    config = load_config('evaluator_config.json')
    model_config = config.get("config", {})

    evaluator = Evaluator(
        model_config=model_config,
        keypoint_sp=config.get("sp", ""),
        keypoint_up=config.get("up", ""),
        scorer_sp=config.get("scorer_sp", ""),
        scorer_up=config.get("scorer_up", ""),
        api_url="https://p6s8vpm3x5.coze.site/run",
        token="pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"
    )

    # Session 1
    print("\n--- Session 1 ---")
    result1 = evaluator.evaluate(
        query="什么是机器学习?",
        answer="机器学习是人工智能的一个分支,它使计算机能够从数据中学习并改进,而无需明确编程。",
        session_id="session_A",
        query_id="q_001"
    )
    print(f"得分: {result1['score_result']['score']}")

    # Session 2 (独立,不参考Session 1)
    print("\n--- Session 2 (独立) ---")
    result2 = evaluator.evaluate(
        query="什么是深度学习?",
        answer="深度学习是机器学习的一个子集,使用多层神经网络来模拟人脑的学习过程。",
        session_id="session_B",
        query_id="q_001"
    )
    print(f"得分: {result2['score_result']['score']}")

    # Session 1 继续 (应该只参考session_A的历史)
    print("\n--- Session 1 继续 ---")
    result3 = evaluator.evaluate(
        query="机器学习有哪些应用?",
        answer="机器学习应用包括:推荐系统、图像识别、自然语言处理、欺诈检测、预测分析等。",
        session_id="session_A",
        query_id="q_002"
    )
    print(f"得分: {result3['score_result']['score']}")

    print("\n✓ 测试2完成")
    print(f"Session A 历史: {len(evaluator.session_history.get('session_A', []))} 轮")
    print(f"Session B 历史: {len(evaluator.session_history.get('session_B', []))} 轮")

def test_without_session():
    """测试不带session_id的评估(向后兼容)"""
    print("\n" + "=" * 80)
    print("测试3: 不带Session ID (向后兼容)")
    print("=" * 80)

    # 初始化评估器
    config = load_config('evaluator_config.json')
    model_config = config.get("config", {})

    evaluator = Evaluator(
        model_config=model_config,
        keypoint_sp=config.get("sp", ""),
        keypoint_up=config.get("up", ""),
        scorer_sp=config.get("scorer_sp", ""),
        scorer_up=config.get("scorer_up", ""),
        api_url="https://p6s8vpm3x5.coze.site/run",
        token="pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"
    )

    # 不提供session_id
    print("\n--- 独立评估 (无上下文) ---")
    result = evaluator.evaluate(
        query="什么是Docker?",
        answer="Docker是一个开源的容器化平台,用于打包、分发和运行应用程序。"
    )
    print(f"得分: {result['score_result']['score']}")

    print("\n✓ 测试3完成")
    print(f"Session历史: {evaluator.session_history}")

if __name__ == "__main__":
    try:
        # 测试1: 单session多轮
        test_single_session()

        # 测试2: 多session独立
        test_multiple_sessions()

        # 测试3: 不带session
        test_without_session()

        print("\n" + "=" * 80)
        print("所有测试完成!")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
