#!/usr/bin/env python3
"""
========================================
Step 1: 单模型考点生成
========================================
使用独立的模型配置文件，独立生成考点。

用法：
  python3 step1_gen.py --config models/deepseek_v4_pro.py
  python3 step1_gen.py --config models/glm_5_1.py 0511测试.xlsx
  python3 step1_gen.py --config models/minimax_m2_7.py --output my_out
========================================
"""

import json
import importlib.util
import pandas as pd
import sys
import time
import os
import asyncio
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI
from collections import defaultdict

# 强制刷新输出，避免 macOS 缓冲
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import INPUT_FILE, CONCURRENCY, TEMPERATURE, TASK_NAME, validate_columns, COLS_STEP1, check_input_data, setup_logger, TokenTracker, get_checkpoint_path, get_step1_data_path
from common import parse_json, count_chinese_chars, normalize_keypoint, format_keypoint_lite, CheckpointManager


def load_model_config(config_path: str) -> dict:
    """从独立配置文件加载 MODEL 字典"""
    spec = importlib.util.spec_from_file_location("model_config", config_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MODEL

# ---------- 提示词（与 step1 一致） ----------
SYSTEM_PROMPT = """# 角色定义
你是一位专业的教育评估专家，擅长分析用户问题并生成标准化、可判定的考点。

# 任务目标
根据用户的问题，分析用户的真实需求，提炼出准确的、既定的、可用的考点，包括核心考点和辅助考点，第三方可以通过核心考点直接判定"满足"或"不满足"。

# 上下文感知规则
- 当提供会话上下文时，必须仔细分析当前问题与前置轮次的关联
- 如果当前问题是对前置问题的追问或扩展，需要参考前置回答的内容
- 考点生成时要考虑：
  * 前置轮次已经解决的问题，当前轮次不应重复判定
  * 前置轮次的回答可能提供的信息背景
  * 当前问题可能依赖于前置回答中的信息
- 如果是单轮场景的问题，忽略上下文，仅针对当前问题生成考点

# 约束与规则
- main_demand（核心需求）和 key_point（考点列表）为必填字段，必须输出
- 考点必须准确对应回答应具备的特征，无歧义
- 每个考点必须是独立的判定维度，不与其他考点重叠
- 每个考点必须能够通过"是/否"直接判定，无需主观打分
- 考点应聚焦单一维度，保持粒度细（复合合并由下游完成）
- 考点数量建议 3-6 个，避免过泛或过细
- 考点之间相互独立，无依赖关系

# 考点分类规则
每个考点必须标注类型：
- core（核心满足项）：回答必须满足的条件，满足全部核心项即得1分
- bonus（辅助增益）：锦上添花的加分项，不满足不影响基本得分

分类标准（示例）：
- 满足用户query中直接提到的约束条件 = core
- 直接回答用户问题 = core
- 提供必要信息/步骤/解释 = core
- 引导澄清模糊需求 = core
- 语气友好、格式美观 = bonus
- 额外补充相关信息 = bonus
- 举例说明 = bonus

# 精准知识问答规则
当 query 为精准的知识问答时（如距离、时间、数量、定义、事实等），key_point中还需要包含：
- core_answer：核心答案（必须包含的正确答案内容）
- exemption_boundary：豁免边界（可接受的偏差范围）

判断标准：
- 包含具体数字的问题（多少公里、多少人、几点钟等）
- 包含明确定义的问题（什么是XX、XX的定义等）
- 包含事实性答案的问题（哪个国家、谁发明的等）
- 有标准答案的考试类问题

豁免边界原则：
- 距离类：允许路线规划差异，给出合理范围
- 时间类：允许不同时区/时制表述
- 人数/数量类：允许统计口径差异
- 定义类：允许表述方式不同，核心含义一致

# 模糊需求识别规则（重要！）

## 第一步：检查上下文
当 query 本身指代模糊、表意不清时，必须先检查会话上下文：
- 如果前序轮次有明确的任务模式（如连续翻译、连续写作等），当前 query 应结合上下文理解
- 示例：前序轮次为"严禁烟火翻译成英文"、"严禁吸烟翻译中文和英文"，当前 query"雨雪天气 小心地滑"→ 需求是将该句翻译为对应语言
- 有上下文时，模糊表达不是模糊需求，应参考上下文正常生成考点

## 第二步：判定模糊需求
仅当 query 真正模糊、无法判断意图、且无上下文可参考时，才判定为模糊需求：
- 明显截断（如"帮我写一个"后无内容）
- 语义严重不明的单个词/短语（如"馄饨"、"什么字"）
- 不完整的信息片段（如"67年6月20日出生"——出生什么？）
- 引用片段无明确指令（如仅给出一段古文出处，无具体要求）

## 第三步：模糊需求的考点生成
当确认为模糊需求时：
- 核心考点（core）：回答是否引导用户明确需求、是否主动询问澄清
- 评估标准：
  * 回答主动引导澄清、覆盖多种可能解读 → 满足
  * 回答直接给出答案，但覆盖了多种主要情况 → 基本满足
  * 回答仅给出一种解读，未提示其他可能 → 不满足

## 不属于模糊需求的情况
- 有上文上下文时，指代上文内容的代词/省略
- 意图清晰的短句、明确的指令、问题类查询
- 知识/文化类查询、商品/产品查询、人物/角色查询
- 简短 ≠ 模糊，只要结合上下文可判断意图就不应判定为模糊需求

# 富媒体/载体需求备注
当 query 涉及明确的富媒体需求（图片生成/编辑、视频、音乐等）或载体需求（链接、组件、AI人物等）时：
- 在考点中备注"该需求依赖视觉理解/富媒体生成能力，当前文本评估方案无法完整覆盖"
- 仍生成可评估的文本部分考点（如意图理解、文字描述准确性等）

# 输出格式
⚠️ 重要：只输出纯JSON格式，不要添加任何markdown标记、说明文字或换行符。
⚠️ 重要：main_demand 和 key_point 必须有值，不能为空。
⚠️ 重要：仅当 query 为精准知识问答时才输出 core_answer 和 exemption_boundary 字段。

仅返回如下格式的 JSON 对象：
{
  "main_demand": "用户的核心需求（必填）",
  "key_point": [
    {"id": 1, "type": "core", "point": "考点内容"},
    {"id": 2, "type": "bonus", "point": "考点内容"}
  ],
  "core_answer": "精准知识问答的核心答案（仅在知识问答类问题时填写）",
  "exemption_boundary": "豁免边界：可接受的偏差范围（仅在知识问答类问题时填写）"
}"""

USER_TEMPLATE = """请根据以下用户问题，生成标准化、可判定的考点列表：

## 输入信息
- 用户问题: {query}
{context}
{reference}

请严格按照JSON格式输出结果。"""


# ---------- 核心类 ----------
class SingleModelGenerator:
    def __init__(self, model_cfg: dict, config_name: str, output_dir: str, task: str = None):
        self.model_name = model_cfg["name"]
        self.model_id = model_cfg["model"]
        self.client = AsyncOpenAI(api_key=model_cfg["api_key"], base_url=model_cfg["base_url"])
        self.task = task or TASK_NAME
        self.logger = setup_logger(self.task or "default", f"step1_{config_name}")
        self.token_tracker = TokenTracker()
        self._save_counter = 0
        self._SAVE_EVERY = 20  # 每20条保存一次checkpoint
        # 断点放在任务文件夹下
        if self.task:
            Path(self.task).mkdir(parents=True, exist_ok=True)
            ckpt_path = get_checkpoint_path(self.task or "default", "step1", config_name)
        else:
            ckpt_path = get_checkpoint_path("default", "step1", config_name)
        self.checkpoint = CheckpointManager(ckpt_path)
        self.semaphore = asyncio.Semaphore(CONCURRENCY)
        self.completed = 0
        self.failed = 0
        self.total = 0
        self.start_time = None
        self.sessions = defaultdict(list)
        self.output_dir = output_dir

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        async with self.semaphore:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=TEMPERATURE,
                )
                self.token_tracker.add(response.usage)
                await asyncio.sleep(0.3)
                return response.choices[0].message.content
            except Exception as e:
                err_str = str(e)
                if "sensitive" in err_str.lower() or "1027" in err_str or "422" in err_str:
                    raise RuntimeError("SENSITIVE_SKIP") from e
                raise

    def build_context(self, session_id: str, current_query_id: int) -> str:
        session_data = self.sessions.get(session_id, [])
        previous_turns = [(qid, q, a) for qid, q, a, r in session_data if qid < current_query_id]
        if not previous_turns:
            return ""
        context_parts = ["\n## 会话上下文（前置轮次记录）"]
        for i, (qid, q, a) in enumerate(previous_turns, 1):
            context_parts.append(f"### 第{i}轮\n用户: {q}")
        last_qid, last_q, last_a = previous_turns[-1]
        answer_short = last_a[:300] + "..." if len(last_a) > 300 else last_a
        char_count = count_chinese_chars(last_a)
        context_parts.append(f"\n## 最近一轮回答参考\n模型: {answer_short}（共计：{char_count}字）")
        return "\n".join(context_parts)

    async def process_one(self, session_id: str, query_id: int, query: str, answer: str, context: str, reference: str = "") -> dict:
        key = f"{session_id}_{query_id}"
        if self.checkpoint.is_processed(key):
            self.completed += 1
            return None

        try:
            context_section = f"\n{context}" if context else ""
            reference_section = f"\n## 参考信息\n{reference}" if reference else ""
            user_prompt = USER_TEMPLATE.format(query=query, context=context_section, reference=reference_section)
            response = await self.chat(SYSTEM_PROMPT, user_prompt)
            kp = parse_json(response)
            normalized = normalize_keypoint(kp)

            result = {
                'session_id': session_id,
                'query_id': query_id,
                'query': query,
                'answer': answer,
                'answer_char_count': count_chinese_chars(answer),
                'main_demand': normalized.get('main_demand', ''),
                'key_point': format_keypoint_lite(normalized),
                'key_point_json': json.dumps(normalized, ensure_ascii=False),
                'core_answer': normalized.get('core_answer', ''),
                'exemption_boundary': normalized.get('exemption_boundary', ''),
                'reference_context': reference,
                'model': self.model_name,
            }

            self.checkpoint.mark_processed(key, result)
            self.completed += 1
            self._save_counter += 1
            if self._save_counter >= self._SAVE_EVERY:
                self.checkpoint.force_save()
                self._save_counter = 0

            elapsed = time.time() - self.start_time
            avg = elapsed / self.completed if self.completed > 0 else 0
            eta = avg * (self.total - self.completed)
            self.logger.info(f"  ✓ [{self.completed}/{self.total}] S{session_id} Q{query_id} | "
                  f"考点: {len(normalized.get('key_point', []))}个 | 剩余: {eta/60:.1f}分钟")
            return result

        except Exception as e:
            self.failed += 1
            err_msg = str(e)[:60]
            if "SENSITIVE_SKIP" in str(e):
                self.logger.info(f"  ⚠ [{self.completed+self.failed}/{self.total}] S{session_id} Q{query_id} 敏感内容跳过")
                err_msg = "敏感内容被API拦截"
            else:
                self.logger.info(f"  ✗ [{self.completed+self.failed}/{self.total}] S{session_id} Q{query_id} 错误: {err_msg}")
            error_result = {
                'session_id': session_id, 'query_id': query_id,
                'query': query, 'answer': answer,
                'answer_char_count': count_chinese_chars(answer),
                'main_demand': '', 'key_point': '', 'key_point_json': '{}',
                'core_answer': '', 'exemption_boundary': '',
                'reference_context': reference,
                'model': self.model_name,
            }
            self.checkpoint.mark_processed(key, error_result)
            return error_result

    async def run(self, df: pd.DataFrame):
        self.total = len(df)
        self.start_time = time.time()

        # 输入预检
        check_input_data(df, self.logger.info)

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"🚀 Step 1: 单模型考点生成")
        self.logger.info(f"   模型: {self.model_name} ({self.model_id})")
        self.logger.info(f"   数据量: {self.total} 条 | 并发: {CONCURRENCY}")
        self.logger.info(f"{'='*60}\n")

        for _, row in df.iterrows():
            sid = str(row['session_id'])
            qid = int(row['query_id'])
            ref = str(row.get('reference_context', '')) if 'reference_context' in df.columns else ''
            if ref == 'nan': ref = ''
            self.sessions[sid].append((qid, str(row['query']), str(row['answer']), ref))
        for sid in self.sessions:
            self.sessions[sid].sort(key=lambda x: x[0])

        tasks = []
        for sid, turns in self.sessions.items():
            for qid, query, answer, ref in turns:
                ctx = self.build_context(sid, qid)
                tasks.append(self.process_one(sid, qid, query, answer, ctx, ref))

        await asyncio.gather(*tasks)
        self.checkpoint.force_save()  # 最终保存
        self.save_excel()

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"✅ {self.model_name} 考点生成完成!")
        self.logger.info(f"   成功: {self.completed} | 失败: {self.failed}")
        self.logger.info(f"   {self.token_tracker.summary()}")
        self.logger.info(f"{'='*60}")

    def save_excel(self):
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = Path(get_step1_data_path(self.task or 'default', self.model_name))
        results = self.checkpoint.get_results()
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by=['session_id', 'query_id']).reset_index(drop=True)
            df.to_excel(output_file, sheet_name='考点生成', index=False)
            print(f"\n📁 已保存: {output_file}")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='模型配置文件路径 (如 models/deepseek_v4_pro.py)')
    parser.add_argument('input_file', nargs='?', default=INPUT_FILE)
    parser.add_argument('--output', default='output_step1')
    parser.add_argument('--task', default=None, help='任务名称（用于断点路径，默认从 config 自动提取）')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()

    config_name = os.path.splitext(os.path.basename(args.config))[0]

    if args.reset:
        ckpt = get_checkpoint_path(args.task or TASK_NAME or "default", "step1", config_name)
        if os.path.exists(ckpt):
            os.remove(ckpt)
            print(f"✅ 断点已清空: {ckpt}")
        return

    if not os.path.exists(args.config):
        print(f"❌ 找不到配置文件: {args.config}")
        sys.exit(1)

    if not os.path.exists(args.input_file):
        print(f"❌ 找不到文件: {args.input_file}")
        sys.exit(1)

    model_cfg = load_model_config(args.config)
    print(f"📋 模型配置: {model_cfg['name']} ({model_cfg['model']})")
    print(f"📋 API: {model_cfg['base_url']}")

    df = pd.read_excel(args.input_file, sheet_name=0)
    validate_columns(df, COLS_STEP1, "Step 1")
    check_input_data(df)

    gen = SingleModelGenerator(model_cfg, config_name, args.output, task=args.task)
    await gen.run(df)


if __name__ == '__main__':
    asyncio.run(main())