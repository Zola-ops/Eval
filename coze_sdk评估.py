#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立的评估脚本 - 支持自定义模型和参数
使用方法:
    # 单条评估
    python standalone_evaluator.py --query "问题" --answer "回答"

    # 批量Excel评估
    python standalone_evaluator.py --excel 考点摸底.xlsx --output results.xlsx

    # 自定义模型参数
    python standalone_evaluator.py --model "doubao-seed-2-0-pro-260215" --temperature 0.3 --query "问题" --answer "回答"

    # 使用配置文件
    python standalone_evaluator.py --config my_config.json --excel input.xlsx
"""

import os
import sys
import json
import argparse
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目路径
# sys.path.insert(0, '/workspace/projects/src')  # 注释掉硬编码路径，本地环境不需要

# 设置工作空间ID
os.environ['COZE_WORKSPACE_ID'] = '7342524085257764915'

from coze_coding_dev_sdk.llm import LLMClient
from coze_coding_utils.runtime_ctx.context import Context


# 清理JSON中的控制字符
def clean_json_text(text: str) -> str:
    """清理JSON文本中的无效控制字符"""
    if not text:
        return text
    # 过滤掉ASCII码小于32且非换行、回车、制表符的控制字符
    cleaned = ''.join(
        char if ord(char) >= 32 or char in '\n\r\t' else ''
        for char in text
    )
    return cleaned


# 考点生成器
class KeypointGenerator:
    def __init__(self, llm_client: LLMClient, sp: str, up_template: str, model_config: Dict[str, Any]):
        self.llm = llm_client
        self.sp = sp
        self.up_template = up_template
        self.model_config = model_config

    def generate(self, query: str, date: Optional[str] = None, demand: Optional[str] = None) -> Dict[str, Any]:
        """生成考点"""
        # 渲染用户提示词
        from jinja2 import Template
        up_tpl = Template(self.up_template)
        up_content = up_tpl.render({
            "query": query,
            "date": date or "",
            "demand": demand or ""
        })

        # 构建消息
        messages = [
            {"role": "system", "content": self.sp},
            {"role": "user", "content": up_content}
        ]

        # 调用LLM
        response = self.llm.invoke(
            messages=messages,
            model=self.model_config.get("model", "doubao-seed-2-0-pro-260215"),
            temperature=self.model_config.get("temperature", 0.3),
            top_p=self.model_config.get("top_p", 0.7),
            max_completion_tokens=self.model_config.get("max_completion_tokens", 2000),
            thinking=self.model_config.get("thinking", "disabled")
        )

        # 提取文本内容
        content = self._get_text_content(response.content)
        cleaned_content = clean_json_text(content)

        # 解析JSON
        try:
            result = json.loads(cleaned_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析考点生成结果: {e}\n原始内容: {content[:200]}...")

        return result

    def _get_text_content(self, content) -> str:
        """安全提取文本内容"""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            if content and isinstance(content[0], str):
                return " ".join(content)
            else:
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return " ".join(text_parts)
        return str(content)


# 评分器
class Scorer:
    def __init__(self, llm_client: LLMClient, sp: str, up_template: str, model_config: Dict[str, Any]):
        self.llm = llm_client
        self.sp = sp
        self.up_template = up_template
        self.model_config = model_config

    def score(self, query: str, answer: str, keypoint_result: Dict[str, Any]) -> Dict[str, Any]:
        """对回答进行评分"""
        # 渲染用户提示词
        from jinja2 import Template
        up_tpl = Template(self.up_template)
        up_content = up_tpl.render({
            "query": query,
            "thinking": keypoint_result.get("thinking", ""),
            "analysis": keypoint_result.get("analysis", ""),
            "main_demand": keypoint_result.get("main_demand", ""),
            "key_point": "\n".join([f"- {kp}" for kp in keypoint_result.get("key_point", [])]),
            "answer": answer
        })

        # 构建消息
        messages = [
            {"role": "system", "content": self.sp},
            {"role": "user", "content": up_content}
        ]

        # 调用LLM
        response = self.llm.invoke(
            messages=messages,
            model=self.model_config.get("model", "doubao-seed-2-0-pro-260215"),
            temperature=self.model_config.get("temperature", 0.3),
            top_p=self.model_config.get("top_p", 0.7),
            max_completion_tokens=self.model_config.get("max_completion_tokens", 2000),
            thinking=self.model_config.get("thinking", "disabled")
        )

        # 提取文本内容
        content = self._get_text_content(response.content)
        cleaned_content = clean_json_text(content)

        # 解析JSON
        try:
            result = json.loads(cleaned_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"无法解析评分结果: {e}\n原始内容: {content[:200]}...")

        return result

    def _get_text_content(self, content) -> str:
        """安全提取文本内容"""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            if content and isinstance(content[0], str):
                return " ".join(content)
            else:
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return " ".join(text_parts)
        return str(content)


# 评估器
class Evaluator:
    def __init__(self, model_config: Dict[str, Any], keypoint_sp: str, keypoint_up: str,
                 scorer_sp: str, scorer_up: str):
        """初始化评估器"""
        # 创建Context（使用默认参数）
        ctx = Context(
            run_id="standalone_eval",
            space_id="default",
            project_id="default"
        )

        # 初始化LLM客户端
        self.llm = LLMClient(ctx=ctx)
        self.model_config = model_config

        # 初始化考点生成器和评分器
        self.keypoint_generator = KeypointGenerator(self.llm, keypoint_sp, keypoint_up, model_config)
        self.scorer = Scorer(self.llm, scorer_sp, scorer_up, model_config)

    def evaluate(self, query: str, answer: str, date: Optional[str] = None,
                 demand: Optional[str] = None) -> Dict[str, Any]:
        """单条评估"""
        # 第一步：生成考点
        keypoint_result = self.keypoint_generator.generate(query, date, demand)

        # 第二步：评分
        score_result = self.scorer.score(query, answer, keypoint_result)

        # 合并结果
        result = {
            "query": query,
            "answer": answer,
            **keypoint_result,
            **score_result
        }

        return result

    def evaluate_batch(self, df: pd.DataFrame, query_col: str = "query",
                       answer_col: str = "answer") -> List[Dict[str, Any]]:
        """批量评估"""
        results = []
        total = len(df)

        for idx, row in df.iterrows():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 处理第 {idx+1}/{total} 条...")
            query = row[query_col]
            answer = row[answer_col]

            try:
                result = self.evaluate(query, answer)
                results.append(result)
                print(f"  ✓ 完成，得分: {result.get('score', -1)}")
            except Exception as e:
                print(f"  ✗ 失败: {e}")
                results.append({
                    "query": query,
                    "answer": answer,
                    "score": -1,
                    "error": str(e)
                })

        return results


# 默认配置
DEFAULT_KEYPOINT_SP = """# 角色定义
你是一位专业的教育评估专家，擅长分析用户问题并生成标准化、可判定的考点。

# 任务目标
根据用户的问题，分析用户的真实需求，提炼出准确的、既定的、唯一的考点，每个考点都能直接判定"满足"或"不满足"。

# 工作流上下文
- **Input**: 用户提供的问题(query)、日期(date)、需求描述(demand)
- **Process**:
  1. 深入理解用户的真实需求和问题背景
  2. 分析问题的核心难点和关键要素
  3. 生成可判定的考点列表，每个考点必须是必要条件
- **Output**: 包含思考过程、问题分析、核心需求和考点列表的JSON对象

# 约束与规则
- 考点必须准确对应回答应具备的特征，无歧义
- 每个考点必须是独立的判定维度，不与其他考点重叠
- 每个考点必须能够通过"是/否"直接判定，无需主观打分
- 考点数量建议控制在 3-6 个
- 考点之间相互独立，无依赖关系
- 避免主观性描述，使用可量化的标准
- 如果用户需求模糊，在 analysis 中说明假设条件

# 过程
1. 理解问题：分析用户的问题背景、目标和约束
2. 识别核心需求：提取用户最核心的需求
3. 生成考点：基于核心需求，设计可判定的考点
4. 验证考点：确保每个考点准确、唯一、可判定

# 输出格式
仅返回如下格式的 JSON 对象：
{
  "thinking": "分析思考过程（描述你如何理解这个问题，考虑了哪些因素）",
  "analysis": "问题的整体分析（背景、难点、回答方向）",
  "main_demand": "用户的核心需求（一句话概括）",
  "key_point": [
    "考点1：具体判定条件",
    "考点2：具体判定条件",
    "考点3：具体判定条件"
  ]
}"""

DEFAULT_KEYPOINT_UP = """请根据以下用户问题，生成标准化、可判定的考点列表：

## 输入信息
- 用户问题: {{query}}
{% if date %}- 问题日期: {{date}}{% endif %}
{% if demand %}- 需求描述: {{demand}}{% endif %}

请严格按照JSON格式输出结果。"""

DEFAULT_SCORER_SP = """# 角色定义
你是一位专业的答案评估专家，负责根据预设的考点，对模型回答进行客观判定。

# 任务目标
根据用户问题、考点列表和模型回答，逐一判定每个考点的满足情况，最终给出二分类评分。

# 工作流上下文
- **Input**: 用户问题、考点生成思考过程、问题分析、核心需求、考点列表、待评估的回答
- **Process**:
  1. 理解每个考点的判定标准
  2. 逐一检查回答是否满足每个考点
  3. 记录每个考点的判定结果和判定依据
  4. 综合所有考点结果，给出最终评分
- **Output**: 包含思考过程、分析、考点判定结果和最终评分的JSON对象

# 约束与规则
- 必须逐一判定每个考点，不能遗漏
- 每个考点的判定结果只能是 true 或 false
- 判定依据（evidence）必须具体，引用回答中的实际内容
- 最终得分必须是 0 或 1，不存在中间值
- 所有考点全部满足才判为满意（score=1），任一考点不满足则判为不满意（score=0）
- 保持客观公正，基于事实进行判定

# 过程
1. 理解考点：明确每个考点的判定标准和要求
2. 逐一判定：对每个考点，检查回答中的相关内容
3. 记录依据：为每个考点提供具体的判定依据，引用回答中的实际内容
4. 综合评分：如果所有考点都满足，score=1；否则score=0
5. 撰写理由：说明整体评分理由，总结各考点的判定情况

# 输出格式
仅返回如下格式的 JSON 对象：
{
  "thinking": "评估思考过程",
  "analysis": "对回答的整体分析",
  "main_demand": "确认的主要需求",
  "key_point": ["考点1", "考点2"],
  "key_point_result": [
    {
      "point": "考点1",
      "satisfied": true,
      "evidence": "判定依据"
    },
    {
      "point": "考点2",
      "satisfied": false,
      "evidence": "判定依据"
    }
  ],
  "answer": "原始回答内容",
  "score": 0,
  "reason": "评分理由"
}"""

DEFAULT_SCORER_UP = """请根据以下信息对模型回答进行评分：

## 用户问题
{{query}}

## 考点生成分析
### 思考过程
{{thinking}}

### 问题分析
{{analysis}}

### 核心需求
{{main_demand}}

## 考点列表
{{key_point}}

## 待评估的回答
{{answer}}

请逐一判定每个考点的满足情况，并给出最终评分（0或1）。严格按照JSON格式输出结果。"""


def save_results_to_excel(results: List[Dict[str, Any]], output_file: str):
    """保存结果到Excel"""
    excel_data = []

    for result in results:
        row = {
            'query': result.get('query', ''),
            'answer': result.get('answer', ''),
            'score': result.get('score', -1),
            'reason': result.get('reason', ''),
            'thinking': result.get('thinking', ''),
            'analysis': result.get('analysis', ''),
            'main_demand': result.get('main_demand', ''),
            'scorer_thinking': result.get('scorer_thinking', ''),
            'scorer_analysis': result.get('scorer_analysis', ''),
            'scorer_main_demand': result.get('scorer_main_demand', ''),
            'error': result.get('error', '')
        }

        # 格式化考点列表
        key_points = result.get('key_point', [])
        if key_points:
            row['key_point'] = '\n'.join([f"{i+1}. {kp}" for i, kp in enumerate(key_points)])
        else:
            row['key_point'] = ''

        scorer_key_points = result.get('scorer_key_point', [])
        if scorer_key_points:
            row['scorer_key_point'] = '\n'.join([f"{i+1}. {skp}" for i, skp in enumerate(scorer_key_points)])
        else:
            row['scorer_key_point'] = ''

        # 格式化考点结果
        key_point_results = result.get('key_point_result', [])
        if key_point_results:
            results_text = []
            for i, kpr in enumerate(key_point_results):
                point = kpr.get('point', '')
                satisfied = kpr.get('satisfied', False)
                evidence = kpr.get('evidence', '')
                results_text.append(f"考点{i+1}: {point}\n是否满足: {satisfied}\n证据: {evidence}")
            row['key_point_result'] = '\n\n'.join(results_text)
        else:
            row['key_point_result'] = ''

        excel_data.append(row)

    df = pd.DataFrame(excel_data)

    # 保存Excel
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='评估结果', index=False)

        # 格式化
        workbook = writer.book
        worksheet = writer.sheets['评估结果']
        wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'top'})

        column_widths = {
            'A': 30,  # query
            'B': 50,  # answer
            'C': 8,   # score
            'D': 40,  # reason
            'E': 40,  # thinking
            'F': 40,  # analysis
            'G': 40,  # main_demand
            'H': 40,  # scorer_thinking
            'I': 40,  # scorer_analysis
            'J': 40,  # scorer_main_demand
            'K': 50,  # key_point
            'L': 50,  # scorer_key_point
            'M': 60,  # key_point_result
            'N': 40,  # error
        }

        for col, width in column_widths.items():
            worksheet.set_column(f'{col}:{col}', width, wrap_format)

        worksheet.freeze_panes(1, 0)

    print(f"\n✓ 结果已保存到: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='独立的评估脚本 - 支持自定义模型和参数')
    parser.add_argument('--config', type=str, help='配置文件路径（JSON格式）')
    parser.add_argument('--model', type=str, default='doubao-seed-2-0-pro-260215', help='模型ID')
    parser.add_argument('--temperature', type=float, default=0.3, help='温度参数')
    parser.add_argument('--top_p', type=float, default=0.7, help='Top P参数')
    parser.add_argument('--max_tokens', type=int, default=2000, help='最大token数')

    # 输入选项
    parser.add_argument('--query', type=str, help='单个评估的问题')
    parser.add_argument('--answer', type=str, help='单个评估的回答')
    parser.add_argument('--excel', type=str, help='Excel文件路径（批量评估）')
    parser.add_argument('--query_col', type=str, default='query', help='Excel中问题列名')
    parser.add_argument('--answer_col', type=str, default='answer', help='Excel中回答列名')

    # 输出选项
    parser.add_argument('--output', type=str, default='evaluation_results.xlsx', help='输出Excel文件路径')
    parser.add_argument('--json', type=str, help='输出JSON文件路径（可选）')

    args = parser.parse_args()

    # 加载配置
    if args.config:
        with open(args.config, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        model_config = config_data.get('config', {})
        keypoint_sp = config_data.get('sp', DEFAULT_KEYPOINT_SP)
        keypoint_up = config_data.get('up', DEFAULT_KEYPOINT_UP)
        scorer_sp = config_data.get('scorer_sp', DEFAULT_SCORER_SP)
        scorer_up = config_data.get('scorer_up', DEFAULT_SCORER_UP)
    else:
        model_config = {
            "model": args.model,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_completion_tokens": args.max_tokens,
            "thinking": "disabled"
        }
        keypoint_sp = DEFAULT_KEYPOINT_SP
        keypoint_up = DEFAULT_KEYPOINT_UP
        scorer_sp = DEFAULT_SCORER_SP
        scorer_up = DEFAULT_SCORER_UP

    print("=" * 80)
    print("评估脚本")
    print("=" * 80)
    print(f"\n模型配置:")
    print(f"  模型: {model_config['model']}")
    print(f"  温度: {model_config['temperature']}")
    print(f"  Top P: {model_config['top_p']}")
    print(f"  最大Token: {model_config['max_completion_tokens']}")
    print("=" * 80)

    # 初始化评估器
    evaluator = Evaluator(model_config, keypoint_sp, keypoint_up, scorer_sp, scorer_up)

    # 单条评估
    if args.query and args.answer:
        print(f"\n单条评估")
        print(f"问题: {args.query}")
        print(f"回答: {args.answer[:100]}...")

        result = evaluator.evaluate(args.query, args.answer)

        print(f"\n评估结果:")
        print(f"  得分: {result.get('score', -1)}")
        print(f"  理由: {result.get('reason', '')}")

        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n✓ JSON结果已保存到: {args.json}")

        return result

    # 批量Excel评估
    elif args.excel:
        print(f"\n批量Excel评估")
        print(f"输入文件: {args.excel}")

        df = pd.read_excel(args.excel)
        print(f"数据量: {len(df)}")

        results = evaluator.evaluate_batch(df, args.query_col, args.answer_col)

        # 统计
        success_count = len([r for r in results if r.get('score', -1) != -1])
        failed_count = len([r for r in results if r.get('score', -1) == -1])

        print(f"\n" + "=" * 80)
        print("评估完成")
        print("=" * 80)
        print(f"总数: {len(results)}")
        print(f"成功: {success_count}")
        print(f"失败: {failed_count}")

        # 保存Excel
        save_results_to_excel(results, args.output)

        # 保存JSON（可选）
        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"✓ JSON结果已保存到: {args.json}")

        return results

    else:
        parser.print_help()
        print("\n错误: 必须指定 --query/--answer（单条）或 --excel（批量）")
        sys.exit(1)


if __name__ == '__main__':
    main()
