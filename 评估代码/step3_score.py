#!/usr/bin/env python3
"""
========================================
Step 3: 评分及原因脚本
========================================
输入：Step 1 输出的 Excel（含 main_demand, key_point）
输出：Excel（新增 score, reason 列）

使用：python3 step2_score.py
========================================
"""

import json
import pandas as pd
import sys
import time
import os
import asyncio
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI

# 强制刷新输出，避免 macOS 缓冲
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    SCORE_MODEL, TEMPERATURE, CONCURRENCY_SCORE, DELAY_BETWEEN_REQUESTS, TASK_NAME,
    validate_columns, COLS_STEP3, setup_logger, TokenTracker, get_checkpoint_path, get_step3_data_path,
)
from common import parse_json, count_chinese_chars, CheckpointManager

# ---------- 配置 ----------
API_BASE_URL = SCORE_MODEL["base_url"]
API_KEY = SCORE_MODEL["api_key"]
MODEL_NAME = SCORE_MODEL["model"]

SHEET_NAME = 0
CONCURRENCY = CONCURRENCY_SCORE

# ---------- 提示词 ----------
SYSTEM_PROMPT = """# 角色定义
你是一位专业的答案评估专家，负责根据预设的考点，对模型回答进行客观判定。

# 任务目标
根据用户问题、考点列表、模型回答和会话上下文，逐一判定每个考点的满足情况，最终给出二分类评分。

# 上下文感知规则（重要！）
- 当提供会话上下文时，需要考虑前置轮次对当前回答的影响
- 如果当前问题依赖于前置回答中的信息，判定时要评估回答是否正确利用了前置信息
- 如果前置轮次已经解决的问题，当前回答中不应出现矛盾
- 如果考点生成时考虑了上下文，评估时也要结合上下文进行判定
- 判定依据可以引用当前回答和前置回答的内容

# 字数参考
- 回答会附带字数统计信息（共计：XX字）
- 如果考点涉及字数要求，需要参考字数统计进行判定
- 但字数本身不是唯一标准，内容质量更重要

# 考点分类说明（重要！）
每个考点包含类型标注：
- [核心] (core)：必须满足的条件
- [辅助] (bonus)：锦上添花的加分项

# 评分规则（重要！）\n- 只有当所有[核心]考点都满足时，score=1\n- 只要有任一[核心]考点不满足，score=0\n- [辅助]考点的满足情况不影响基本得分，但需要在reason中说明\n\n# 优质判定规则\n- is_excellent=1（优质）：score=1（所有核心考点满足）且所有[辅助]考点也全部满足\n- is_excellent=0（非优质）：score=0，或score=1但存在未满足的[辅助]考点

# 约束与规则
- 必须逐一判定每个考点，不能遗漏
- 每个考点的判定结果只能是 true 或 false
- 判定依据（evidence）必须具体，引用回答中的实际内容
- 最终得分必须是 0 或 1，不存在中间值

# 评分理由输出规则（重要！）
- 若评分为1（核心考点全部满足）：必须逐一列出每个核心考点的满足证据，不能简单写"无问题"
- 若评分为0（核心考点存在不满足）：仅输出不满足的核心考点及其证据
- 辅助考点的满足情况单独列出，作为补充说明
- 理由必须具体、可追溯，引用回答中的实际内容或缺失内容

# 模糊需求评估规则（重要！）
- 如果考点包含"引导用户明确需求"或"主动询问澄清"：
  * 满足条件：回答主动引导澄清、覆盖多种可能解读
  * 基本满足：回答直接给出答案，但覆盖了多种主要情况
  * 不满足条件：仅给出一种解读，未提示其他可能
- 判定前必须先检查上下文：如果前序轮次有明确任务模式，当前query应结合上下文理解，不属于模糊需求
- 简短但结合上下文意图明确的 query，应正常评估回答质量

# 字数评估规则（重要！）
- 字数统计已提供（共计：XX字）
- 需根据考点中的字数要求类型，使用不同的浮动范围：

## 强字数限制（如"500字"、"不少于300字"）
- 允许下限 -10%，上限 +20%
- 示例：要求500字 → 450-600字均符合要求
- 示例：要求300字 → 270-360字均符合要求

## 弱字数限制（如"300字左右"、"约500字"）
根据实际字数梯度，使用不同浮动范围：

### 200字以下
- 允许 ±30% 浮动
- 示例：要求100字 → 70-130字均符合要求

### 200-799字
- 下限 -20%，上限 +40%
- 示例：要求500字 → 400-700字均符合要求
- 示例：要求300字 → 240-420字均符合要求

### 800字以上
- 下限 -10%，上限 +30%
- 示例：要求1000字 → 900-1300字均符合要求

## 明确上限/下限要求
- "不超过X字"：实际字数 ≤ X字即满足
- "不少于X字"：实际字数 ≥ X字即满足
- 示例："不超过500字" → 500字及以下均符合
- 示例："不少于300字" → 300字及以上均符合

## 判定原则
- 只有当字数超出浮动范围时，才判定为不满足字数要求

# 输出格式
⚠️ 重要：只输出纯JSON格式，不要添加任何markdown标记、说明文字或多余的换行符。
⚠️ 重要：answer字段不要输出完整的原始回答，只输出"[已评估]"即可。

仅返回如下格式的 JSON 对象：
{
  "key_point_result": [
    {"id": 1, "type": "core", "point": "考点1", "satisfied": true, "evidence": "判定依据"},
    {"id": 2, "type": "bonus", "point": "考点2", "satisfied": false, "evidence": "判定依据"}
  ],
  "answer": "[已评估]",
  "score": 0,
  "is_excellent": 0,
  "reason": "评分理由"
}"""

USER_TEMPLATE = """请根据以下信息对模型回答进行评分：

## 用户问题
{query}

## 考点生成分析
### 核心需求
{main_demand}

## 考点列表（格式：序号. [类型]考点内容）
{key_point}

## 精准知识问答参考（如有）
核心答案：{core_answer}
豁免边界：{exemption_boundary}

## 参考信息（如有）
{reference}

## 待评估的回答
{answer}

## 字数统计
共计：{char_count}字

请逐一判定每个考点的满足情况，并给出最终评分（0或1）和优质判定。
注意：只有所有[核心]考点都满足时score=1，任一[核心]考点不满足则score=0。
[辅助]考点的满足情况不影响基本得分。
is_excellent=1 仅当 score=1 且所有[辅助]考点也全部满足。

对于精准知识问答：
- 核心答案：回答必须包含该答案的核心内容
- 豁免边界：在此范围内的偏差可接受，不判定为不满足

严格按照JSON格式输出结果。"""

def find_latest_step2_output(step2_output_dir: str = None) -> str:
    """查找最新的 Step 2 输出文件"""
    from config import EVAL_DATA
    if step2_output_dir:
        output_path = Path(step2_output_dir)
    else:
        output_path = Path(EVAL_DATA)
    if not output_path.exists():
        return None
    
    files = sorted(output_path.glob("*-step2-*.xlsx"), reverse=True)
    return str(files[0]) if files else None

class Scorer:
    def __init__(self, task: str = None):
        self.client = AsyncOpenAI(api_key=API_KEY, base_url=API_BASE_URL)
        self.task = task or TASK_NAME
        self.logger = setup_logger(self.task or "default", "step3")
        self.token_tracker = TokenTracker()
        self._save_counter = 0
        self._SAVE_EVERY = 20
        # 断点放在任务文件夹下
        if self.task:
            Path(self.task).mkdir(parents=True, exist_ok=True)
            ckpt_path = get_checkpoint_path(self.task or "default", "step3")
        else:
            ckpt_path = get_checkpoint_path("default", "step3")
        self.checkpoint = CheckpointManager(ckpt_path)
        self.semaphore = asyncio.Semaphore(CONCURRENCY)
        self.completed = 0
        self.failed = 0
    
    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        async with self.semaphore:
            response = await self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=TEMPERATURE,
            )
            self.token_tracker.add(response.usage)
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
            return response.choices[0].message.content
    
    async def score(self, query: str, answer: str, main_demand: str, key_point: str, core_answer: str = "", exemption_boundary: str = "", reference: str = "") -> dict:
        char_count = count_chinese_chars(answer)
        
        user_prompt = USER_TEMPLATE.format(
            query=query,
            main_demand=main_demand,
            key_point=key_point,
            core_answer=core_answer if core_answer else "无",
            exemption_boundary=exemption_boundary if exemption_boundary else "无",
            reference=reference if reference else "无",
            answer=answer,
            char_count=char_count
        )
        
        for attempt in range(3):
            response = await self.chat(SYSTEM_PROMPT, user_prompt)
            result = parse_json(response)
            if result.get('score') is not None:
                return result
            await asyncio.sleep(1)
        
        return result  # 3 次都失败，返回空结果
    
    CLASSIFY_PROMPT = """你是一位问题分类专家。根据评分理由判断问题类型。

# 标签列表（只选1个）
安全性 | 拒绝回答/无法回答 | 意图理解 | 指令遵循 | 短期记忆 | 个性化 | 生成式富媒体-意图理解 | 准确性 | 时效性 | 丰富/全面性 | 逻辑性 | 冗余冗杂/重复 | 通顺/清晰/易懂 | 可操作/易用 | 文采 | 其他 | 生成式富媒体-质量问题 | 载体-召回 | 载体-质量 | 载体-一致性 | 交互/设计 | 信息获取效率 | 展现&排版 | 反思 | 意图引导/反问 | 共情性/人格化 | 无问题

# 标签说明
- 安全性：涉政、涉黄、暴力、歧视、非法建议等安全红线
- 拒绝回答/无法回答：常规问题被拒绝回答
- 意图理解：未理解用户需求，偏离主题，答非所问
- 指令遵循：未遵循用户指令（字数、格式、禁止项、创作体裁等）
- 短期记忆：未正确记住会话上下文，对话不连续或前后矛盾
- 个性化：未记住用户偏好习惯，未提供个性化服务
- 生成式富媒体-意图理解：文生图、图片编辑、音乐、视频等场景的意图理解问题
- 准确性：事实性错误、计算错误、推理错误、代码错误
- 时效性：内容过时
- 丰富/全面性：缺少关键信息，影响主需获取
- 逻辑性：层次不合理，逻辑不连贯，前后矛盾
- 冗余冗杂/重复：无效信息多，表述啰嗦，或同内容重复
- 通顺/清晰/易懂：语言不通顺，语种不一致，标点语法错误
- 可操作/易用：套话空话，无具体步骤，未形成任务闭环
- 文采：创作/翻译场景用词不丰富，表达不新颖
- 其他：无法归入以上类型的内容价值问题
- 生成式富媒体-质量问题：生图/修图/生成富媒体质量差
- 载体-召回：富媒体/MCP/阿拉丁等漏召、过召、错召
- 载体-质量：组件、封面、内容、AI人物质量不合格
- 载体-一致性：载体与文本内容不匹配或挂载位置不合理
- 交互/设计：交互功能不可用或不便捷
- 信息获取效率：需注册/充值才能获取信息，路径过长
- 展现&排版：排版不合理，核心观点未前置，重点未高亮
- 反思：未识别之前回答错误，未响应用户反馈
- 意图引导/反问：未引导用户持续对话，未澄清模糊需求
- 共情性/人格化：不符合自然表达习惯，缺乏对话感
- 无问题：无明显问题

# 输出格式
只输出纯JSON：{"tag": "标签", "reason": "分类依据"}"""

    async def classify(self, query: str, answer: str, reason: str) -> dict:
        """对 score=0 的结果进行问题分类"""
        user_prompt = f"用户问题: {query}\n模型回答: {answer[:500]}\n评分理由: {reason}"
        for attempt in range(3):
            try:
                response = await self.chat(self.CLASSIFY_PROMPT, user_prompt)
                result = parse_json(response)
                if result.get('tag'):
                    return result
            except:
                pass
            await asyncio.sleep(1)
        return {'tag': '', 'reason': ''}
    
    async def process_one(self, row: dict) -> dict:
        session_id = str(row['session_id'])
        query_id = int(row['query_id'])
        key = f"{session_id}_{query_id}"
        
        if self.checkpoint.is_processed(key):
            self.completed += 1
            return None
        
        query = str(row['query'])
        answer = str(row['answer'])
        main_demand = str(row.get('main_demand', ''))
        key_point = str(row.get('key_point', ''))
        core_answer = str(row.get('core_answer', ''))
        exemption_boundary = str(row.get('exemption_boundary', ''))
        reference = str(row.get('reference_context', ''))
        if reference == 'nan': reference = ''
        
        # 考点为空时跳过评分
        if not key_point or key_point.strip() == '' or key_point.strip() == 'nan':
            self.completed += 1
            result = {
                'session_id': session_id, 'query_id': query_id,
                'query': query, 'answer': answer,
                'answer_char_count': row.get('answer_char_count', count_chinese_chars(answer)),
                'main_demand': main_demand, 'key_point': key_point,
                'core_answer': core_answer, 'exemption_boundary': exemption_boundary,
                'score': -1, 'is_excellent': -1, 'reason': '考点为空，跳过评分',
                'tag': '', 'tag_reason': '', 'human_eval': '需要复核'
            }
            self.checkpoint.mark_processed(key, result)
            print(f"  ⊘ [{self.completed}/{self.total}] Session {session_id} Q{query_id} | 考点为空，跳过")
            return result
        
        try:
            sc = await self.score(query, answer, main_demand, key_point, core_answer, exemption_boundary, reference)
            
            score_val = sc.get('score', -1)
            
            # 分类：score=0 时单独调用分类模型
            if score_val == 0:
                cls = await self.classify(query, answer, sc.get('reason', ''))
                tag = cls.get('tag', '')
                tag_reason = cls.get('reason', '')
            elif score_val == 1:
                tag = '无问题'
                tag_reason = ''
            else:
                tag = ''
                tag_reason = ''
            
            result = {
                'session_id': session_id,
                'query_id': query_id,
                'query': query,
                'answer': answer,
                'answer_char_count': row.get('answer_char_count', count_chinese_chars(answer)),
                'main_demand': main_demand,
                'key_point': key_point,
                'key_point_result': json.dumps(sc.get('key_point_result', []), ensure_ascii=False),
                'core_answer': core_answer,
                'exemption_boundary': exemption_boundary,
                'score': score_val,
                'is_excellent': sc.get('is_excellent', -1),
                'reason': sc.get('reason', '') or '模型未返回评分原因',
                'tag': tag,
                'tag_reason': tag_reason,
            }
            
            # human_eval 标记
            rich_media_keywords = ['图片', '视频', '音频', '图像', '生成图', '画', '链接', '组件', '小程序']
            is_rich = any(kw in query for kw in rich_media_keywords)
            if score_val == -1 or not key_point or key_point.strip() in ('', 'nan') or is_rich:
                result['human_eval'] = '需要复核'
            else:
                result['human_eval'] = ''
            
            self.checkpoint.mark_processed(key, result)
            self.completed += 1
            self._save_counter += 1
            if self._save_counter >= self._SAVE_EVERY:
                self.checkpoint.force_save()
                self._save_counter = 0
            
            elapsed = time.time() - self.start_time
            avg = elapsed / self.completed if self.completed > 0 else 0
            eta = avg * (self.total - self.completed)
            
            self.logger.info(f"  ✓ [{self.completed}/{self.total}] Session {session_id} Q{query_id} | 得分: {sc.get('score')} | 剩余: {eta/60:.1f}分钟")
            
            return result
            
        except Exception as e:
            self.failed += 1
            print(f"  ✗ [{self.completed+self.failed}/{self.total}] Session {session_id} Q{query_id} 错误: {str(e)[:50]}")
            
            error_result = {
                'session_id': session_id,
                'query_id': query_id,
                'query': query,
                'answer': answer,
                'answer_char_count': row.get('answer_char_count', 0),
                'main_demand': main_demand,
                'key_point': key_point,
                'core_answer': core_answer,
                'exemption_boundary': exemption_boundary,
                'score': -1,
                'is_excellent': -1,
                'reason': f'错误: {str(e)}',
                'tag': '',
                'tag_reason': '',
                'human_eval': '需要复核'
            }
            self.checkpoint.mark_processed(key, error_result)
            return error_result
    
    async def run(self, df: pd.DataFrame):
        self.total = len(df)
        self.start_time = time.time()
        
        self.logger.info(f"\n🚀 Step 3: 评分及原因 ({self.total} 条, 并发: {CONCURRENCY})")
        self.logger.info("-" * 60)
        
        rows = df.to_dict('records')
        tasks = [self.process_one(row) for row in rows]
        await asyncio.gather(*tasks)
        self.checkpoint.force_save()
        self.save_excel()
        
        results = self.checkpoint.get_results()
        score_1 = sum(1 for r in results if r.get('score') == 1)
        score_0 = sum(1 for r in results if r.get('score') == 0)
        
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"✅ 评分完成! 成功: {self.completed} | 失败: {self.failed}")
        self.logger.info(f"   ✓ 得分 1: {score_1} | ✗ 得分 0: {score_0}")
        self.logger.info(f"   {self.token_tracker.summary()}")
        self.logger.info(f"{'='*60}")
    
    def save_excel(self):
        output_file = Path(get_step3_data_path(self.task or 'default'))
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        
        results = self.checkpoint.get_results()
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values(by=['session_id', 'query_id'], ascending=[True, True]).reset_index(drop=True)
            
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                # Sheet 1: 详细结果
                df.to_excel(writer, sheet_name='评分结果', index=False)
                
                # Sheet 2: 统计分析
                stats = []
                total = len(df)
                score_valid = df[df['score'] != -1]
                stats.append(['总条数', total])
                stats.append(['Session数', df['session_id'].nunique()])
                stats.append(['---', '---'])
                
                if len(score_valid) > 0:
                    stats.append(['满意率(score=1)', f"{(score_valid['score']==1).sum()}/{len(score_valid)} = {(score_valid['score']==1).mean()*100:.1f}%"])
                stats.append(['优质率(is_excellent=1)', f"{(df['is_excellent']==1).sum()}/{total} = {(df['is_excellent']==1).mean()*100:.1f}%"])
                stats.append(['异常率(score=-1)', f"{(df['score']==-1).sum()}/{total} = {(df['score']==-1).mean()*100:.1f}%"])
                if 'human_eval' in df.columns:
                    stats.append(['需人工复核', f"{(df['human_eval']=='需要复核').sum()} 条"])
                stats.append(['---', '---'])
                
                if 'tag' in df.columns:
                    tag_counts = df[df['tag'] != '']['tag'].value_counts()
                    for tag, count in tag_counts.items():
                        stats.append([f'问题类型: {tag}', count])
                stats.append(['---', '---'])
                
                stats.append(['API调用次数', self.token_tracker.calls])
                stats.append(['prompt_tokens', self.token_tracker.prompt_tokens])
                stats.append(['completion_tokens', self.token_tracker.completion_tokens])
                stats.append(['total_tokens', self.token_tracker.total_tokens])
                
                pd.DataFrame(stats, columns=['指标', '值']).to_excel(writer, sheet_name='统计分析', index=False)
            
            print(f"\n📁 Excel 已保存: {output_file}")

REQUIRED_COLS = COLS_STEP3

async def main():
    global API_BASE_URL, API_KEY, MODEL_NAME
    
    import argparse
    parser = argparse.ArgumentParser(description="Step 3: 基于考点评分")
    parser.add_argument('--task', default=None, help='任务名称')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--api-base', default=API_BASE_URL, help='覆盖 config.py 中的 API 地址')
    parser.add_argument('--api-key', default=API_KEY, help='覆盖 config.py 中的 API Key')
    parser.add_argument('--model', default=MODEL_NAME, help='覆盖 config.py 中的模型名')
    args = parser.parse_args()
    
    # 允许 CLI 覆盖 config.py 配置
    API_BASE_URL = args.api_base
    API_KEY = args.api_key
    MODEL_NAME = args.model
    
    if args.reset:
        ckpt = get_checkpoint_path(args.task or TASK_NAME or "default", "step3")
        if os.path.exists(ckpt):
            os.remove(ckpt)
            print(f"✅ 断点已清空: {ckpt}")
        return
    
    task = args.task or TASK_NAME
    
    print(f"📋 评分模型: {MODEL_NAME}")
    print(f"📋 API 地址: {API_BASE_URL}")
    
    # 查找 Step 2 输出
    input_file = find_latest_step2_output()
    if input_file is None:
        print("❌ 找不到 Step 2 输出，请先运行 step2_summary.py")
        sys.exit(1)
    
    print(f"📖 读取: {input_file}")
    df = pd.read_excel(input_file, sheet_name=SHEET_NAME)
    
    # 输入列名校验
    validate_columns(df, REQUIRED_COLS, "Step 3")
    print(f"✅ 列名校验通过: {len(df)} 条数据")
    
    scorer = Scorer(task=task)
    await scorer.run(df)

if __name__ == '__main__':
    asyncio.run(main())
