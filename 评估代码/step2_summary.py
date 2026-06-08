#!/usr/bin/env python3
"""
========================================
Step 2: 总结模型合成最终考点
========================================
读取 3 个模型的考点输出，用总结模型合成最终考点。

用法：
  python3 step2_summary.py                          # 自动从评估数据/找最新的 3 个 step1 文件
  python3 step2_summary.py -f a.xlsx b.xlsx c.xlsx  # 手动指定 3 个文件
========================================
"""

import json
import pandas as pd
import sys
import time
import os
import asyncio
import glob
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI

# 强制刷新输出，避免 macOS 缓冲
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SUMMARY_MODEL, CONCURRENCY, TEMPERATURE, TASK_NAME, setup_logger, TokenTracker, get_checkpoint_path, get_step2_data_path, EVAL_DATA
from common import (parse_json, format_keypoint, format_keypoint_confidence,
                    CheckpointManager, compute_consistency,
                    compute_confidence, filter_by_confidence, estimate_source_count)

# ---------- 总结模型提示词（置信度评估体系） ----------
SUMMARY_SYSTEM_PROMPT = """# 角色定义
你是一位资深的教育评估专家，负责综合多个模型的考点生成结果，评估每个考点的置信度，产出最终的标准化考点。

# 任务目标
1. 合并去重三个模型的考点，语义相近的考点合并为一条
2. 将相关子需求组合为**复合考点**（如"字数约3000字且末尾附参考文献"）
3. 对每个合并后的考点，评估**显性程度**和**必要程度**
4. 标注每个考点来源于几个模型（source_count）

# 上下文感知规则
- 当提供会话上下文时，必须分析当前问题与前置轮次的关联
- 前置轮次已解决的问题，当前轮次不应重复判定
- 多轮对话中指代上文的表达不是模糊需求，应参考上下文理解

# 置信度评估维度

## 显性程度（0-100）— 最重要
用户是否明确提出该需求。
- 90-100：用户直接、明确地提出了该需求（如"要求3000字"）
- 70-89：用户暗示或间接表达了该需求（如"写详细点"）
- 50-69：该需求是合理推断但用户未明确提及
- <50：该需求属于理想化/锦上添花，用户完全未提及

## 必要程度（0-100）
缺失该考点是否会导致用户核心需求无法满足。
- 90-100：缺失则核心需求完全无法满足
- 70-89：缺失则回答质量显著下降
- 50-69：缺失不影响核心需求，但影响完整性
- <50：缺失对用户体验影响很小

## 多模型一致性（程序自动计算）
程序会自动对比三个模型的原始考点，计算每个合并考点的覆盖模型数，无需你输出。

# 复合考点规则
- 将语义相关、逻辑关联的子需求合并为一条复合考点
- 示例：不要拆成"字数3000字"和"附参考文献"两条，而应合并为"字数约3000字（±20%浮动），末尾附参考文献列表"
- 每条考点应是一个完整的、可独立判定的维度

# 语义合并规则
- 三个模型中语义相近的考点必须合并为一条
- 合并时取最准确、最全面的表述
- source_count = 识别出该考点的模型数量（1/2/3）

# 约束与规则
- main_demand（核心需求）和 key_point（考点列表）为必填字段
- 考点数量建议 4-8 个（后续会按置信度过滤，最终保留≤4个）
- 每个考点必须能通过"是/否"直接判定
- 如果三个模型的核心需求表述不同，选择最准确、最全面的版本

# 输出格式
⚠️ 重要：只输出纯JSON格式，不要添加任何markdown标记、说明文字或换行符。

{
  "main_demand": "最终核心需求",
  "key_point": [
    {"id": 1, "point": "复合考点内容", "explicitness": 95, "necessity": 95},
    {"id": 2, "point": "复合考点内容", "explicitness": 80, "necessity": 85},
    {"id": 3, "point": "复合考点内容", "explicitness": 55, "necessity": 70}
  ],
  "core_answer": "精准知识问答的核心答案（如有）",
  "exemption_boundary": "豁免边界（如有）"
}"""

SUMMARY_USER_TEMPLATE = """请综合以下三个模型生成的考点，进行语义合并、复合考点构建，并评估每个考点的置信度。

## 用户问题
{query}
{context}

## 模型1（{model1_name}）生成的考点
{model1_output}

## 模型2（{model2_name}）生成的考点
{model2_output}

## 模型3（{model3_name}）生成的考点
{model3_output}

请按照置信度评估体系，输出最终考点JSON。"""

FALLBACK_USER_TEMPLATE = """请根据以下用户问题，直接生成标准化、可判定的考点列表。

## 用户问题
{query}
{context}

注意：
- 每个考点需要评估 explicitness（显性程度）和 necessity（必要程度），0-100
- 考点可以是复合考点

请输出最终考点JSON。"""


# ---------- 核心类 ----------
class SummaryGenerator:
    def __init__(self, model_files: list, output_dir: str, task: str = None):
        self.client = AsyncOpenAI(api_key=SUMMARY_MODEL["api_key"], base_url=SUMMARY_MODEL["base_url"])
        self.summary_model = SUMMARY_MODEL["model"]
        self.summary_name = SUMMARY_MODEL["name"]
        self.task = task or TASK_NAME
        self.logger = setup_logger(self.task or "default", "step2")
        self.token_tracker = TokenTracker()
        self._save_counter = 0
        self._SAVE_EVERY = 20
        # 断点放在任务文件夹下
        if self.task:
            Path(self.task).mkdir(parents=True, exist_ok=True)
            ckpt_path = get_checkpoint_path(self.task or "default", "step2")
        else:
            ckpt_path = get_checkpoint_path("default", "step2")
        self.checkpoint = CheckpointManager(ckpt_path)
        self.semaphore = asyncio.Semaphore(CONCURRENCY)
        self.completed = 0
        self.failed = 0
        self.total = 0
        self.start_time = None
        self.output_dir = output_dir
        self.quality_issues = 0  # 考点质检问题计数

        # 加载 3 个模型的输出
        self.dfs = []
        self.model_names = []
        for f in model_files:
            df = pd.read_excel(f, sheet_name=0)
            self.dfs.append(df)
            # 从数据中提取模型名
            if 'model' in df.columns and len(df) > 0:
                self.model_names.append(str(df['model'].iloc[0]))
            else:
                self.model_names.append(Path(f).stem)

        # 构建 session 索引（用于多轮上下文）
        self.sessions = {}
        for i, df_item in enumerate(self.dfs):
            for _, row in df_item.iterrows():
                sid = str(row.get('session_id', ''))
                qid = int(row.get('query_id', 0))
                if sid not in self.sessions:
                    self.sessions[sid] = []
                self.sessions[sid].append((qid, str(row.get('query', '')), str(row.get('answer', ''))))
        for sid in self.sessions:
            self.sessions[sid].sort(key=lambda x: x[0])
            # 去重（同一个 session_id+query_id 可能在多个 df 中出现）
            seen = set()
            deduped = []
            for qid, q, a in self.sessions[sid]:
                if qid not in seen:
                    seen.add(qid)
                    deduped.append((qid, q, a))
            self.sessions[sid] = deduped

        print(f"📋 模型1: {self.model_names[0]} ({len(self.dfs[0])} 条)")
        print(f"📋 模型2: {self.model_names[1]} ({len(self.dfs[1])} 条)")
        print(f"📋 模型3: {self.model_names[2]} ({len(self.dfs[2])} 条)")

    def build_context(self, session_id: str, current_query_id: int) -> str:
        """构建多轮会话上下文（与 step1a 保持一致）"""
        session_data = self.sessions.get(session_id, [])
        previous_turns = [(qid, q, a) for qid, q, a in session_data if qid < current_query_id]
        if not previous_turns:
            return ""
        context_parts = ["\n## 会话上下文（前置轮次记录）"]
        for i, (qid, q, a) in enumerate(previous_turns, 1):
            context_parts.append(f"### 第{i}轮\n用户: {q}")
        last_qid, last_q, last_a = previous_turns[-1]
        answer_short = last_a[:300] + "..." if len(last_a) > 300 else last_a
        char_count = len([c for c in last_a if '\u4e00' <= c <= '\u9fff'])
        context_parts.append(f"\n## 最近一轮回答参考\n模型: {answer_short}（共计：{char_count}字）")
        return "\n".join(context_parts)

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        async with self.semaphore:
            response = await self.client.chat.completions.create(
                model=self.summary_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=TEMPERATURE,
            )
            self.token_tracker.add(response.usage)
            await asyncio.sleep(0.3)
            return response.choices[0].message.content

    def get_kp_json(self, df, idx: int) -> dict:
        """从 DataFrame 中取第 idx 行的 key_point_json"""
        row = df.iloc[idx]
        kp_str = str(row.get('key_point_json', '{}'))
        try:
            return json.loads(kp_str)
        except:
            return {"main_demand": "", "key_point": [], "core_answer": "", "exemption_boundary": ""}

    def check_keypoint_quality(self, query: str, kp: dict) -> str:
        """考点质检：检查空考点、过泛、重复、无关"""
        points = kp.get("key_point", [])
        main_demand = kp.get("main_demand", "").strip()

        if not points:
            return "空考点"
        if not main_demand:
            return "空main_demand"

        # 检查考点内容是否过于宽泛
        vague_keywords = ["回答质量好", "内容丰富", "表述清晰", "格式正确", "信息准确"]
        vague_count = sum(1 for p in points if any(vk in p.get("point", "") for vk in vague_keywords))
        if vague_count >= len(points):
            return "全部考点过于宽泛"

        # 检查考点是否重复
        point_texts = [p.get("point", "").strip() for p in points]
        if len(point_texts) != len(set(point_texts)):
            return "存在重复考点"

        # 检查考点数量异常
        if len(points) > 10:
            return f"考点过多({len(points)}个)"

        return "OK"

    async def process_one(self, idx: int) -> dict:
        key = str(idx)
        if self.checkpoint.is_processed(key):
            self.completed += 1
            return None

        row0 = self.dfs[0].iloc[idx]
        query = str(row0['query'])
        answer = str(row0.get('answer', ''))
        session_id = str(row0.get('session_id', ''))
        query_id = int(row0.get('query_id', 0))
        reference_context = str(row0.get('reference_context', ''))
        if reference_context == 'nan': reference_context = ''

        try:
            kps = [
                (self.model_names[0], self.get_kp_json(self.dfs[0], idx)),
                (self.model_names[1], self.get_kp_json(self.dfs[1], idx)),
                (self.model_names[2], self.get_kp_json(self.dfs[2], idx)),
            ]

            # 过滤掉没有考点的模型
            valid_kps = [(name, kp) for name, kp in kps if kp.get('key_point')]

            # 构建多轮上下文
            context = self.build_context(session_id, query_id)
            context_section = f"\n{context}" if context else ""

            # 构建动态 prompt：只列出有效模型的考点
            if valid_kps:
                if len(valid_kps) == 3:
                    user_prompt = SUMMARY_USER_TEMPLATE.format(
                        query=query,
                        context=context_section,
                        model1_name=valid_kps[0][0],
                        model1_output=json.dumps(valid_kps[0][1], ensure_ascii=False, indent=2),
                        model2_name=valid_kps[1][0],
                        model2_output=json.dumps(valid_kps[1][1], ensure_ascii=False, indent=2),
                        model3_name=valid_kps[2][0],
                        model3_output=json.dumps(valid_kps[2][1], ensure_ascii=False, indent=2),
                    )
                elif len(valid_kps) == 2:
                    user_prompt = SUMMARY_USER_TEMPLATE.format(
                        query=query,
                        context=context_section,
                        model1_name=valid_kps[0][0],
                        model1_output=json.dumps(valid_kps[0][1], ensure_ascii=False, indent=2),
                        model2_name=valid_kps[1][0],
                        model2_output=json.dumps(valid_kps[1][1], ensure_ascii=False, indent=2),
                        model3_name="（无）",
                        model3_output="（此模型未生成有效考点）",
                    )
                else:
                    user_prompt = SUMMARY_USER_TEMPLATE.format(
                        query=query,
                        context=context_section,
                        model1_name=valid_kps[0][0],
                        model1_output=json.dumps(valid_kps[0][1], ensure_ascii=False, indent=2),
                        model2_name="（无）",
                        model2_output="（此模型未生成有效考点）",
                        model3_name="（无）",
                        model3_output="（此模型未生成有效考点）",
                    )
            else:
                # 所有模型都没考点，直接用 query 生成
                user_prompt = FALLBACK_USER_TEMPLATE.format(query=query, context=context_section)

            response = await self.chat(SUMMARY_SYSTEM_PROMPT, user_prompt)
            raw = parse_json(response)

            # 计算置信度、分配层级
            model_texts = [format_keypoint(kps[0][1]), format_keypoint(kps[1][1]), format_keypoint(kps[2][1])]
            final = {
                "main_demand": raw.get("main_demand", "").strip(),
                "key_point": [],
                "core_answer": raw.get("core_answer", "").strip() if raw.get("core_answer") else "",
                "exemption_boundary": raw.get("exemption_boundary", "").strip() if raw.get("exemption_boundary") else "",
            }
            for i, p in enumerate(raw.get("key_point", [])):
                if isinstance(p, dict) and p.get("point", "").strip():
                    explicitness = float(p.get("explicitness", 50))
                    necessity = float(p.get("necessity", 50))
                    source_count = estimate_source_count(p["point"], model_texts)
                    confidence = compute_confidence(explicitness, necessity, source_count)
                    final["key_point"].append({
                        "id": i + 1,
                        "point": p["point"].strip(),
                        "explicitness": explicitness,
                        "necessity": necessity,
                        "source_count": source_count,
                        "confidence": round(confidence, 1),
                    })

            # 按置信度过滤 + 层级分配 + 数量限制
            final = filter_by_confidence(final)

            result = {
                'session_id': row0['session_id'],
                'query_id': row0['query_id'],
                'query': query,
                'answer': answer,
                'answer_char_count': row0.get('answer_char_count', 0),
                'main_demand': final.get('main_demand', ''),
                'key_point_1': format_keypoint(kps[0][1]),
                'key_point_2': format_keypoint(kps[1][1]),
                'key_point_3': format_keypoint(kps[2][1]),
                'key_point': format_keypoint_confidence(final),
                'key_point_json': json.dumps(final, ensure_ascii=False),
                'core_answer': final.get('core_answer', ''),
                'exemption_boundary': final.get('exemption_boundary', ''),
                'gen_models': ' | '.join(self.model_names),
                'summary_model': self.summary_name,
                'kp_quality': '',
                'consistency': '',
                'reference_context': reference_context,
            }

            # 一致性分析
            consistency = compute_consistency(kps)
            result['consistency'] = consistency.get('disagreement_level', '')
            if consistency.get('disagreement_level') == 'HIGH':
                self.logger.info(f"  ⚠ 高分歧: S{row0['session_id']} Q{row0['query_id']} "
                      f"core={consistency['core_count_spread']} bonus={consistency['bonus_count_spread']}")

            # 考点质检
            quality = self.check_keypoint_quality(query, final)
            result['kp_quality'] = quality
            if quality != 'OK':
                self.quality_issues += 1
                self.logger.info(f"  ⚠ 质检: S{row0['session_id']} Q{row0['query_id']} {quality}")

            self.checkpoint.mark_processed(key, result)
            self.completed += 1
            self._save_counter += 1
            if self._save_counter >= self._SAVE_EVERY:
                self.checkpoint.force_save()
                self._save_counter = 0

            elapsed = time.time() - self.start_time
            avg = elapsed / self.completed if self.completed > 0 else 0
            eta = avg * (self.total - self.completed)
            self.logger.info(f"  ✓ [{self.completed}/{self.total}] S{row0['session_id']} Q{row0['query_id']} | "
                  f"考点: {len(final.get('key_point', []))}个 | 剩余: {eta/60:.1f}分钟")
            return result

        except Exception as e:
            self.failed += 1
            self.logger.info(f"  ✗ [{self.completed+self.failed}/{self.total}] S{row0['session_id']} Q{row0['query_id']} 错误: {str(e)[:60]}")
            error_result = {
                'session_id': row0['session_id'], 'query_id': row0['query_id'],
                'query': query, 'answer': answer,
                'answer_char_count': row0.get('answer_char_count', 0),
                'main_demand': '', 'key_point_1': '', 'key_point_2': '', 'key_point_3': '',
                'key_point': '', 'core_answer': '', 'exemption_boundary': '',
                'gen_models': ' | '.join(self.model_names),
                'summary_model': self.summary_name,
                'reference_context': reference_context,
            }
            self.checkpoint.mark_processed(key, error_result)
            return error_result

    async def run(self):
        self.total = len(self.dfs[0])
        self.start_time = time.time()

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"🚀 Step 2: 总结模型合成最终考点")
        self.logger.info(f"   总结模型: {self.summary_name} ({self.summary_model})")
        self.logger.info(f"   数据量: {self.total} 条 | 并发: {CONCURRENCY}")
        self.logger.info(f"{'='*60}\n")

        tasks = [self.process_one(i) for i in range(self.total)]
        await asyncio.gather(*tasks)
        self.checkpoint.force_save()
        self.save_excel()

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"✅ 总结完成!")
        self.logger.info(f"   成功: {self.completed} | 失败: {self.failed}")
        self.logger.info(f"   考点质检问题: {self.quality_issues} 条")
        self.logger.info(f"   {self.token_tracker.summary()}")
        self.logger.info(f"{'='*60}")

    def save_excel(self):
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = Path(get_step2_data_path(self.task or 'default'))
        results = self.checkpoint.get_results()
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by=['session_id', 'query_id']).reset_index(drop=True)
            df.to_excel(output_file, sheet_name='最终考点', index=False)
            print(f"\n📁 已保存: {output_file}")


def find_latest_files(directory: str, pattern: str = "考点_*.xlsx", count: int = 3) -> list:
    """在目录下找最新的 N 个匹配文件"""
    files = sorted(glob.glob(os.path.join(directory, pattern)), key=os.path.getmtime, reverse=True)
    return files[:count]


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--files', nargs='+', help='手动指定 3 个考点文件')
    parser.add_argument('--input-dir', default=None, help='step1 输出目录（默认从评估数据/自动查找）')
    parser.add_argument('--output', default='output_step2')
    parser.add_argument('--task', default=None, help='任务名称（用于断点路径，默认从 config 自动提取）')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    if args.reset:
        ckpt = get_checkpoint_path(args.task or TASK_NAME or "default", "step2")
        if os.path.exists(ckpt):
            os.remove(ckpt)
            print(f"✅ 断点已清空: {ckpt}")
        return

    # 确定输入文件
    if args.files:
        model_files = args.files
        if len(model_files) != 3:
            print(f"❌ 需要恰好 3 个文件，提供了 {len(model_files)} 个")
            sys.exit(1)
    else:
        search_dir = args.input_dir or EVAL_DATA
        model_files = find_latest_files(search_dir, pattern="*-step1-*.xlsx")
        if len(model_files) < 3:
            print(f"❌ {search_dir}/ 下找到 {len(model_files)} 个考点文件，需要 3 个")
            print("   请先运行 step1_gen.py 生成 3 个模型的考点")
            sys.exit(1)
        model_files = model_files[:3]

    for f in model_files:
        if not os.path.exists(f):
            print(f"❌ 找不到文件: {f}")
            sys.exit(1)

    print(f"📋 总结模型: {SUMMARY_MODEL['name']}")

    gen = SummaryGenerator(model_files, args.output, task=args.task)
    await gen.run()


if __name__ == '__main__':
    asyncio.run(main())