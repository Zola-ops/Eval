#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立的评估脚本 - 使用直接 API 调用（无需 SDK）
使用方法:
    # 单条评估
    python standalone_evaluator_api.py --query "问题" --answer "回答"

    # 批量Excel评估
    python standalone_evaluator_api.py --excel 考点摸底.xlsx --output results.xlsx

    # 自定义API地址和token
    python standalone_evaluator_api.py --api_url "https://xxx.coze.site/run" --token "your-token" --query "问题" --answer "回答"
"""

import os
import sys
import json
import argparse
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any
from jinja2 import Template


# 清理JSON中的控制字符
def clean_json_text(text: str) -> str:
    """清理JSON文本中的无效控制字符"""
    if not text:
        return text
    cleaned = ''.join(
        char if ord(char) >= 32 or char in '\n\r\t' else ''
        for char in text
    )
    return cleaned


# API 客户端
class APIClient:
    def __init__(self, api_url: str, token: str, model_config: Dict[str, Any]):
        self.api_url = api_url
        self.token = token
        self.model_config = model_config
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM API"""
        # 构建请求 payload（根据实际 API 格式调整）
        payload = {
            "query": user_prompt,
            "date": {},
            "demand": {},
            "answer": ""
        }

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            
            # 尝试提取响应内容
            if isinstance(result, dict):
                if "content" in result:
                    return result["content"]
                elif "message" in result:
                    return result["message"]
                elif "choices" in result and len(result["choices"]) > 0:
                    return result["choices"][0].get("message", {}).get("content", "")
                elif "data" in result:
                    return str(result["data"])
                elif "result" in result:
                    return result["result"]
                elif "response" in result:
                    return result["response"]
                else:
                    # 返回整个 JSON 作为备用
                    return json.dumps(result, ensure_ascii=False, indent=2)
            else:
                return str(result)
                
        except requests.exceptions.RequestException as e:
            raise ValueError(f"API 调用失败: {e}\n状态码: {getattr(e.response, 'status_code', 'N/A') if hasattr(e, 'response') else 'N/A'}\n响应: {e.response.text[:500] if hasattr(e, 'response') and hasattr(e.response, 'text') else 'N/A'}")
        except json.JSONDecodeError as e:
            raise ValueError(f"API 响应解析失败: {e}\n原始响应: {response.text[:500]}")


# 考点生成器
class KeypointGenerator:
    def __init__(self, api_client: APIClient, sp: str, up_template: str, model_config: Dict[str, Any]):
        self.api = api_client
        self.sp = sp
        self.up_template = up_template
        self.model_config = model_config

    def generate(self, query: str, date: Optional[str] = None, demand: Optional[str] = None,
                context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """生成考点 - 使用专门的考点生成 API

        Args:
            query: 用户问题
            date: 问题日期(可选)
            demand: 需求描述(可选)
            context: 会话历史上下文(可选),包含前置轮次的query和answer
        """
        # 构建请求 payload
        payload = {
            "query": query,
            "date": date or "",
            "demand": demand or "",
            "answer": "",  # 考点生成时此字段为空
            "context": self._format_context(context) if context else ""  # 添加上下文信息
        }

        # 使用专门的 API 端点
        try:
            response = requests.post(
                self.api.api_url,
                headers=self.api.headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            result = response.json()

            # 提取内容
            if isinstance(result, dict):
                if "data" in result:
                    result_data = result["data"]
                    if isinstance(result_data, str):
                        return json.loads(result_data)
                    return result_data
                elif "result" in result:
                    return result["result"]
                elif "response" in result:
                    return result["response"]
                else:
                    return result
            else:
                return json.loads(str(result))

        except requests.exceptions.RequestException as e:
            error_detail = ""
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                error_detail = f"\n响应: {e.response.text[:500]}"
            raise ValueError(f"考点生成 API 调用失败: {e}{error_detail}")
        except json.JSONDecodeError as e:
            error_text = ""
            if hasattr(response, 'text'):
                error_text = f"\n原始响应: {response.text[:500]}"
            raise ValueError(f"考点生成结果解析失败: {e}{error_text}")

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        """格式化上下文信息为可读字符串"""
        if not context:
            return ""

        context_parts = []
        for idx, turn in enumerate(context, 1):
            query = turn.get("query", "")
            answer = turn.get("answer", "")
            # 限制长度避免token溢出
            answer_short = answer[:500] + "..." if len(answer) > 500 else answer
            context_parts.append(f"第{idx}轮:\nQ: {query}\nA: {answer_short}")

        return "\n\n".join(context_parts)


# 评分器
class Scorer:
    def __init__(self, api_client: APIClient, sp: str, up_template: str, model_config: Dict[str, Any]):
        self.api = api_client
        self.sp = sp
        self.up_template = up_template
        self.model_config = model_config

    def score(self, query: str, answer: str, keypoint_result: Dict[str, Any],
              context: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """对回答进行评分 - 使用专门的评分 API

        Args:
            query: 用户问题
            answer: 模型回答
            keypoint_result: 考点生成结果
            context: 会话历史上下文(可选),包含前置轮次的query和answer
        """
        # 构建请求 payload（评分时所有字段都需要）
        payload = {
            "query": query,
            "date": "",
            "demand": "",
            "answer": answer,
            "context": self._format_context(context) if context else "",  # 添加上下文信息
            "keypoint_result": keypoint_result  # 传递考点生成结果
        }

        # 使用专门的 API 端点
        try:
            response = requests.post(
                self.api.api_url,
                headers=self.api.headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            result = response.json()

            # 提取内容
            if isinstance(result, dict):
                if "data" in result:
                    result_data = result["data"]
                    if isinstance(result_data, str):
                        return json.loads(result_data)
                    return result_data
                elif "result" in result:
                    return result["result"]
                elif "response" in result:
                    return result["response"]
                else:
                    return result
            else:
                return json.loads(str(result))

        except requests.exceptions.RequestException as e:
            error_detail = ""
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                error_detail = f"\n响应: {e.response.text[:500]}"
            raise ValueError(f"评分 API 调用失败: {e}{error_detail}")
        except json.JSONDecodeError as e:
            error_text = ""
            if hasattr(response, 'text'):
                error_text = f"\n原始响应: {response.text[:500]}"
            raise ValueError(f"评分结果解析失败: {e}{error_text}")

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        """格式化上下文信息为可读字符串"""
        if not context:
            return ""

        context_parts = []
        for idx, turn in enumerate(context, 1):
            query = turn.get("query", "")
            answer = turn.get("answer", "")
            # 限制长度避免token溢出
            answer_short = answer[:500] + "..." if len(answer) > 500 else answer
            context_parts.append(f"第{idx}轮:\nQ: {query}\nA: {answer_short}")

        return "\n\n".join(context_parts)


# 评估器
class Evaluator:
    def __init__(self, model_config: Dict[str, Any], keypoint_sp: str, keypoint_up: str,
                 scorer_sp: str, scorer_up: str, api_url: str, token: str):
        """初始化评估器"""
        self.model_config = model_config

        # 初始化 API 客户端
        self.api = APIClient(api_url, token, model_config)

        # 初始化考点生成器和评分器
        self.keypoint_generator = KeypointGenerator(self.api, keypoint_sp, keypoint_up, model_config)
        self.scorer = Scorer(self.api, scorer_sp, scorer_up, model_config)

        # Session 历史记录维护
        # 结构: {session_id: [{"query_id": str, "query": str, "answer": str, "keypoint_result": dict, "score_result": dict}]}
        self.session_history: Dict[str, List[Dict[str, Any]]] = {}

    def evaluate(self, query: str, answer: str, date: Optional[str] = None,
                demand: Optional[str] = None, session_id: Optional[str] = None,
                query_id: Optional[str] = None) -> Dict[str, Any]:
        """执行完整评估流程

        Args:
            query: 用户问题
            answer: 模型回答
            date: 问题日期(可选)
            demand: 需求描述(可选)
            session_id: 会话ID,用于维护上下文(可选)
            query_id: 查询ID,用于标识具体问题(可选)

        Returns:
            评估结果字典
        """
        # 获取session历史上下文
        context = None
        if session_id and session_id in self.session_history:
            context = self.session_history[session_id]

        print(f"\n{'='*80}")
        print("单条评估")
        print(f"问题: {query}")
        print(f"回答: {answer[:50]}{'...' if len(answer) > 50 else ''}")
        if session_id:
            print(f"Session ID: {session_id}")
            print(f"前置轮次: {len(context) if context else 0} 条")
        print(f"{'='*80}\n")

        # 步骤1: 生成考点(带上下文)
        print("步骤1: 生成考点...")
        keypoint_result = self.keypoint_generator.generate(query, date, demand, context)
        print(f"  ✓ 考点生成完成，共 {len(keypoint_result.get('key_point', []))} 个考点")

        # 步骤2: 评分(带上下文)
        print("步骤2: 评估回答...")
        score_result = self.scorer.score(query, answer, keypoint_result, context)
        print(f"  ✓ 评分完成，得分: {score_result.get('score', 'N/A')}")

        # 合并结果
        result = {
            "query": query,
            "answer": answer,
            "session_id": session_id,
            "query_id": query_id,
            "keypoint_result": keypoint_result,
            "score_result": score_result,
            "timestamp": datetime.now().isoformat()
        }

        # 更新session历史
        if session_id:
            if session_id not in self.session_history:
                self.session_history[session_id] = []
            self.session_history[session_id].append({
                "query_id": query_id,
                "query": query,
                "answer": answer,
                "keypoint_result": keypoint_result,
                "score_result": score_result
            })

        print(f"\n{'='*80}")
        print("评估结果:")
        print(f"  得分: {score_result.get('score', 'N/A')}")
        print(f"  理由: {score_result.get('reason', 'N/A')[:100]}...")
        print(f"{'='*80}\n")

        return result

    def batch_evaluate(self, excel_path: str, output_excel: str, output_json: Optional[str] = None,
                      query_col: str = "query", answer_col: str = "answer",
                      session_id_col: Optional[str] = "session_id", query_id_col: Optional[str] = "query_id") -> pd.DataFrame:
        """批量评估 Excel 文件

        Args:
            excel_path: Excel文件路径
            output_excel: 输出Excel文件路径
            output_json: 输出JSON文件路径(可选)
            query_col: 问题列名
            answer_col: 回答列名
            session_id_col: session_id列名(可选)
            query_id_col: query_id列名(可选)
        """
        print(f"\n{'='*80}")
        print("批量评估")
        print(f"{'='*80}\n")

        # 读取Excel
        df = pd.read_excel(excel_path)
        print(f"读取数据: {len(df)} 条记录")

        # 检查是否包含session_id列
        has_session = session_id_col and session_id_col in df.columns
        has_query_id = query_id_col and query_id_col in df.columns

        if has_session:
            print(f"检测到 session_id 列,将启用上下文感知评估")

        results = []
        for idx, row in df.iterrows():
            query = row[query_col]
            answer = row[answer_col]

            # 提取session_id和query_id
            session_id = str(row[session_id_col]) if has_session else None
            query_id = str(row[query_id_col]) if has_query_id else None

            print(f"\n处理第 {idx + 1}/{len(df)} 条...")
            if session_id:
                print(f"  Session: {session_id}")
            if query_id:
                print(f"  Query ID: {query_id}")

            try:
                result = self.evaluate(query, answer, session_id=session_id, query_id=query_id)

                # 展开结果 - 保持完整字段
                keypoint_list = result["keypoint_result"].get("key_point", [])
                scorer_keypoint_list = result["score_result"].get("key_point", [])
                keypoint_results = result["score_result"].get("key_point_result", [])

                # 构建key_point_result列表，每个元素合并point和evidence
                keypoint_result_combined = []
                for kp in keypoint_results:
                    satisfied = kp.get('satisfied', False)
                    point = kp.get('point', '')
                    evidence = kp.get('evidence', '')
                    combined = f"[{'✓' if satisfied else '✗'}] {point}\n证据: {evidence}"
                    keypoint_result_combined.append(combined)

                # 将列表转换为字符串格式，便于在Excel中显示
                flat_result = {
                    "query": query,
                    "answer": answer,
                    "session_id": result.get("session_id", ""),
                    "query_id": result.get("query_id", ""),
                    # 考点生成部分
                    "thinking": result["keypoint_result"].get("thinking", ""),
                    "analysis": result["keypoint_result"].get("analysis", ""),
                    "main_demand": result["keypoint_result"].get("main_demand", ""),
                    "key_point": " | ".join(keypoint_list) if keypoint_list else "",
                    # 评分部分
                    "scorer_thinking": result["score_result"].get("thinking", ""),
                    "scorer_analysis": result["score_result"].get("analysis", ""),
                    "scorer_main_demand": result["score_result"].get("main_demand", ""),
                    "scorer_key_point": " | ".join(scorer_keypoint_list) if scorer_keypoint_list else "",
                    # key_point_result 合并为多列
                    "keypoint_results_summary": f"{sum(1 for kp in keypoint_results if kp.get('satisfied'))}/{len(keypoint_results)}" if keypoint_results else "0/0",
                    "keypoint_result_1": keypoint_result_combined[0] if len(keypoint_result_combined) > 0 else "",
                    "keypoint_result_2": keypoint_result_combined[1] if len(keypoint_result_combined) > 1 else "",
                    "keypoint_result_3": keypoint_result_combined[2] if len(keypoint_result_combined) > 2 else "",
                    "keypoint_result_4": keypoint_result_combined[3] if len(keypoint_result_combined) > 3 else "",
                    "keypoint_result_5": keypoint_result_combined[4] if len(keypoint_result_combined) > 4 else "",
                    "keypoint_result_6": keypoint_result_combined[5] if len(keypoint_result_combined) > 5 else "",
                    # 最终评分
                    "score": result["score_result"].get("score", ""),
                    "reason": result["score_result"].get("reason", ""),
                    "timestamp": result["timestamp"]
                }
                results.append(flat_result)

            except Exception as e:
                print(f"  ✗ 评估失败: {e}")
                results.append({
                    "query": query,
                    "answer": answer,
                    "session_id": session_id if session_id else "",
                    "query_id": query_id if query_id else "",
                    "score": "",
                    "reason": f"评估失败: {str(e)}",
                    "keypoint_count": 0,
                    "satisfied_count": 0,
                    "timestamp": datetime.now().isoformat()
                })

        # 保存结果
        result_df = pd.DataFrame(results)

        # 保存 Excel
        result_df.to_excel(output_excel, index=False, engine='openpyxl')
        print(f"\n{'='*80}")
        print(f"✓ Excel 结果已保存: {output_excel}")
        print(f"{'='*80}")

        # 保存 JSON
        if output_json:
            result_df.to_json(output_json, orient='records', force_ascii=False, indent=2)
            print(f"✓ JSON 结果已保存: {output_json}")

        return result_df


def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='独立的评估脚本 - 使用直接 API 调用')

    # 配置参数
    parser.add_argument('--config', default='evaluator_config.json', help='配置文件路径')
    parser.add_argument('--model', help='模型ID')
    parser.add_argument('--temperature', type=float, help='温度参数')
    parser.add_argument('--top_p', type=float, help='Top P参数')
    parser.add_argument('--max_tokens', type=int, help='最大token数')

    # API 配置
    parser.add_argument('--api_url', default='https://p6s8vpm3x5.coze.site/run', help='API 地址')
    parser.add_argument('--token', default='pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm', help='API Token')

    # 输入输出
    parser.add_argument('--query', help='单个评估的问题')
    parser.add_argument('--answer', help='单个评估的回答')
    parser.add_argument('--excel', help='批量评估的Excel文件')
    parser.add_argument('--output', help='批量评估的输出Excel文件')
    parser.add_argument('--query_col', default='query', help='Excel中的问题列名')
    parser.add_argument('--answer_col', default='answer', help='Excel中的回答列名')
    parser.add_argument('--session_id_col', default='session_id', help='Excel中的session_id列名')
    parser.add_argument('--query_id_col', default='query_id', help='Excel中的query_id列名')
    parser.add_argument('--json', help='输出JSON结果文件')

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    model_config = config.get("config", {})

    # 覆盖配置
    if args.model:
        model_config["model"] = args.model
    if args.temperature:
        model_config["temperature"] = args.temperature
    if args.top_p:
        model_config["top_p"] = args.top_p
    if args.max_tokens:
        model_config["max_completion_tokens"] = args.max_tokens

    # 打印配置
    print(f"{'='*80}")
    print("评估脚本")
    print(f"{'='*80}\n")
    print("模型配置:")
    print(f"  模型: {model_config.get('model', 'N/A')}")
    print(f"  温度: {model_config.get('temperature', 'N/A')}")
    print(f"  Top P: {model_config.get('top_p', 'N/A')}")
    print(f"  最大Token: {model_config.get('max_completion_tokens', 'N/A')}")
    print(f"{'='*80}\n")

    # 初始化评估器
    evaluator = Evaluator(
        model_config=model_config,
        keypoint_sp=config.get("sp", ""),
        keypoint_up=config.get("up", ""),
        scorer_sp=config.get("scorer_sp", ""),
        scorer_up=config.get("scorer_up", ""),
        api_url=args.api_url,
        token=args.token
    )

    # 单条评估
    if args.query and args.answer:
        result = evaluator.evaluate(args.query, args.answer)

        if args.json:
            with open(args.json, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {args.json}")

    # 批量评估
    elif args.excel:
        if not args.output:
            args.output = args.excel.replace('.xlsx', '_result.xlsx')

        evaluator.batch_evaluate(
            excel_path=args.excel,
            output_excel=args.output,
            output_json=args.json,
            query_col=args.query_col,
            answer_col=args.answer_col,
            session_id_col=args.session_id_col,
            query_id_col=args.query_id_col
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
