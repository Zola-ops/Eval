#!/usr/bin/env python3
"""
Step 4: 异常修复工作流
  1. 读取 step3 最终结果，找出异常行（空考点 / score=-1）
  2. 对异常 session 的所有 query 重新评估（3模型考点→总结→评分）
  3. 重试直到考点非空且分数≠-1（最多5轮）
  4. 与 step3 正常结果合并，输出修复后的完整结果

用法：python3 step4_retry.py [--max-retries 5]
"""

import json, pandas as pd, sys, time, os, asyncio, re, argparse, glob
from datetime import datetime
from openai import AsyncOpenAI

# 强制刷新输出，避免 macOS 缓冲
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import GENERATION_MODELS, SUMMARY_MODEL, SCORE_MODEL, CONCURRENCY, TEMPERATURE, TASK_NAME, INPUT_FILE, setup_logger, TokenTracker, get_step3_data_path, EVAL_DATA
from common import parse_json, normalize_keypoint_lite as normalize, format_keypoint_lite as fmt_keypoint

# ========== 模型配置（从 config.py 导入）==========
GEN_MODELS = GENERATION_MODELS
SUM_MODEL = SUMMARY_MODEL
# SCORE_MODEL 直接使用 config.py 中的

# ========== 提示词（简版，与 step1a/step1b/step2 一致） ==========

GEN_SYSTEM = """# 角色定义
你是一位专业的教育评估专家，擅长分析用户问题并生成标准化、可判定的考点。

# 任务目标
根据用户的问题，分析用户的真实需求，提炼出准确的、既定的、可用的考点。

# 约束与规则
- main_demand 和 key_point 为必填字段
- 每个考点必须能通过"是/否"直接判定
- 考点数量建议控制在 3-6 个
- 考点类型：core（核心满足项）、bonus（辅助增益）

# 输出格式
只输出纯JSON，不输出 thinking：
{
  "main_demand": "用户的核心需求（必填）",
  "key_point": [
    {"id": 1, "type": "core", "point": "考点内容"},
    {"id": 2, "type": "bonus", "point": "考点内容"}
  ],
  "core_answer": "",
  "exemption_boundary": ""
}"""

GEN_USER = """请根据以下用户问题生成考点列表：

## 用户问题
{query}

{main_demand_hint}

请输出JSON。"""

SUM_SYSTEM = """你是一位资深的教育评估专家，负责综合三个模型生成的考点，产出最终标准化考点。

# 总结原则
1. 取长补短，去重合并
2. 核心考点在前，辅助在后
3. 保持可判定性
4. 如果提供了参考 main_demand，应优先采纳

# 输出格式
只输出纯JSON：
{
  "main_demand": "最终核心需求",
  "key_point": [
    {"id": 1, "type": "core", "point": "考点内容"}
  ],
  "core_answer": "",
  "exemption_boundary": ""
}"""

SUM_USER = """综合以下三个模型的考点，总结最终考点。

## 用户问题
{query}

{main_demand_ref}

## 模型1: {m1}
{m1_out}

## 模型2: {m2}
{m2_out}

## 模型3: {m3}
{m3_out}

输出JSON。"""

SCORE_SYSTEM = """你是一位严格的评分专家，根据考点列表对回答进行"是/否"判定。

# 评分规则
- 核心考点（core）：必须全部满足，任一不满足则 score=0
- 辅助考点（bonus）：加分项，不影响 score
- 只有所有核心考点都满足时 score=1

# 优质判定
- is_excellent=1：score=1 且所有辅助考点也全部满足
- is_excellent=0：score=0 或存在未满足的辅助考点

# 问题类型标签（score=0 时必须输出）
标签列表：意图理解 | 拒绝回答/无法回答 | 准确性 | 时效性 | 权威性 | 内容价值-丰富性 | 内容价值-特异性 | 内容价值-文采/创意 | 内容价值-缺失 | 内容价值-重复 | 内容价值-其他 | 逻辑性 | 冗余冗杂 | 通顺性 | 无问题
- score=1 时 tag="无问题"
- score=0 时输出最主要的问题类型（只1个）

# 输出格式
只输出纯JSON：
{
  "score": 0,
  "is_excellent": 0,
  "reason": "评分理由",
  "tag": "问题类型标签",
  "tag_reason": "分类依据"
}"""

SCORE_USER = """根据考点评分：

## 用户问题
{query}

## 核心需求
{main_demand}

## 考点列表
{key_point}

## 模型回答（字数: {char_count}）
{answer}

输出JSON。"""

# ========== 工具函数 ==========
def is_abnormal(row):
    """判断一行是否异常"""
    kp = str(row.get('key_point', '')).strip()
    score = row.get('score', -1)
    is_excellent = row.get('is_excellent', -1)
    if not kp or kp == '' or kp == 'nan':
        return True
    if score == -1 or pd.isna(score):
        return True
    if is_excellent == -1 or pd.isna(is_excellent):
        return True
    return False

def chinese_chars(t):
    return len(re.compile(r'[\u4e00-\u9fff]').findall(t or ""))

# ========== 重试评估器 ==========
class RetryEvaluator:
    def __init__(self, max_retries=5, task=None):
        self.max_retries = max_retries
        self.task = task or TASK_NAME
        self.logger = setup_logger(self.task or "default", "step4")
        self.token_tracker = TokenTracker()
        self.gen_clients = [AsyncOpenAI(api_key=c["api_key"], base_url=c["base_url"]) for c in GEN_MODELS]
        self.gen_names = [c["name"] for c in GEN_MODELS]
        self.sum_client = AsyncOpenAI(api_key=SUM_MODEL["api_key"], base_url=SUM_MODEL["base_url"])
        self.score_client = AsyncOpenAI(api_key=SCORE_MODEL["api_key"], base_url=SCORE_MODEL["base_url"])
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.fixed = 0
        self.skipped = 0

    async def chat(self, client, model, sys_p, usr_p):
        async with self.sem:
            for attempt in range(3):
                try:
                    resp = await client.chat.completions.create(
                        model=model, messages=[{"role": "system", "content": sys_p},
                                                {"role": "user", "content": usr_p}],
                        temperature=TEMPERATURE)
                    self.token_tracker.add(resp.usage)
                    await asyncio.sleep(0.5)
                    return resp.choices[0].message.content
                except Exception as e:
                    err = str(e)
                    if "sensitive" in err.lower() or "1027" in err:
                        raise RuntimeError("SENSITIVE_SKIP")
                    if attempt < 2:
                        await asyncio.sleep(2)
                    else:
                        raise

    async def gen_keypoints(self, query, known_demand):
        """3模型并行生成考点 → 总结"""
        hint = f"\n- 已知用户需求: {known_demand}" if known_demand else ""
        up = GEN_USER.format(query=query, main_demand_hint=hint)

        async def call(i):
            try:
                r = await self.chat(self.gen_clients[i], GEN_MODELS[i]["model"], GEN_SYSTEM, up)
                return (self.gen_names[i], normalize(parse_json(r)))
            except:
                return (self.gen_names[i], {"main_demand": "", "key_point": [], "core_answer": "", "exemption_boundary": ""})

        results = list(await asyncio.gather(*[call(i) for i in range(3)]))

        m1, k1 = results[0]; m2, k2 = results[1]; m3, k3 = results[2]
        ref = f"## 用户提供的需求参考\n{known_demand}" if known_demand else ""
        sup = SUM_USER.format(query=query, main_demand_ref=ref,
                              m1=m1, m1_out=json.dumps(k1, ensure_ascii=False, indent=2),
                              m2=m2, m2_out=json.dumps(k2, ensure_ascii=False, indent=2),
                              m3=m3, m3_out=json.dumps(k3, ensure_ascii=False, indent=2))
        try:
            r = await self.chat(self.sum_client, SUM_MODEL["model"], SUM_SYSTEM, sup)
            final = normalize(parse_json(r))
        except:
            final = k1

        if known_demand and final.get("main_demand", "").strip() != known_demand:
            final["main_demand"] = known_demand

        return final

    async def score_answer(self, query, answer, main_demand, key_point_str):
        """评分（含分类）"""
        cc = chinese_chars(answer)
        up = SCORE_USER.format(query=query, main_demand=main_demand, key_point=key_point_str,
                               answer=answer[:3000], char_count=cc)
        try:
            r = await self.chat(self.score_client, SCORE_MODEL["model"], SCORE_SYSTEM, up)
            sc = parse_json(r)
            tag = sc.get("tag", "")
            if sc.get("score") == 1:
                tag = "无问题"
            return (sc.get("score", -1), sc.get("is_excellent", -1), sc.get("reason", "") or "模型未返回评分原因",
                    tag, sc.get("tag_reason", ""))
        except:
            return -1, -1, "评分API调用失败", "", ""

    async def fix_one(self, row, known_demand=""):
        """修复一条异常记录，重试直到成功"""
        sid = row['session_id']
        qid = row['query_id']
        query = str(row['query'])
        answer = str(row['answer'])

        for attempt in range(1, self.max_retries + 1):
            try:
                # Step 1+2: 生成考点
                kp = await self.gen_keypoints(query, known_demand)
                kp_str = fmt_keypoint(kp)

                if not kp_str:
                    self.logger.info(f"    [S{sid} Q{qid}] 第{attempt}次考点为空，重试...")
                    await asyncio.sleep(2)
                    continue

                # Step 3: 评分（含分类）
                score, is_excellent, reason, tag, tag_reason = await self.score_answer(query, answer, kp.get("main_demand", ""), kp_str)

                if score == -1:
                    self.logger.info(f"    [S{sid} Q{qid}] 第{attempt}次评分-1，重试...")
                    await asyncio.sleep(2)
                    continue

                # 成功
                result = {
                    "session_id": sid, "query_id": qid, "query": query, "answer": answer,
                    "answer_char_count": chinese_chars(answer),
                    "main_demand": kp.get("main_demand", ""),
                    "key_point": kp_str,
                    "key_point_json": json.dumps(kp, ensure_ascii=False),
                    "score": score,
                    "is_excellent": is_excellent,
                    "reason": reason,
                    "key_point_result": "[]",
                    "tag": tag,
                    "tag_reason": tag_reason,
                    "retry_attempt": attempt,
                }
                self.fixed += 1
                self.logger.info(f"  ✓ [S{sid} Q{qid}] 第{attempt}次修复成功 score={score}")
                return result

            except RuntimeError as e:
                if "SENSITIVE_SKIP" in str(e):
                    self.logger.info(f"  ⊘ [S{sid} Q{qid}] 敏感内容，跳过")
                    self.skipped += 1
                    return {
                        "session_id": sid, "query_id": qid, "query": query, "answer": answer,
                        "answer_char_count": chinese_chars(answer),
                        "main_demand": known_demand, "key_point": "", "score": -1, "is_excellent": -1,
                        "reason": "敏感内容被API拦截", "tag": row.get("tag", ""),
                        "tag_reason": row.get("tag_reason", ""), "retry_attempt": 0,
                    }
            except Exception as e:
                self.logger.info(f"    [S{sid} Q{qid}] 第{attempt}次异常: {str(e)[:80]}")
                await asyncio.sleep(2)

        # 超出最大重试
        self.skipped += 1
        print(f"  ✗ [S{sid} Q{qid}] 超过{self.max_retries}次重试，放弃")
        return {
            "session_id": sid, "query_id": qid, "query": query, "answer": answer,
            "answer_char_count": chinese_chars(answer),
            "main_demand": known_demand, "key_point": "", "score": -1, "is_excellent": -1,
            "reason": f"超过{self.max_retries}次重试仍失败",
            "tag": row.get("tag", ""), "tag_reason": row.get("tag_reason", ""),
            "retry_attempt": self.max_retries,
        }

    async def run(self, abnormal_rows, source_df):
        """并行修复所有异常行"""
        total = len(abnormal_rows)
        self.logger.info(f"\n  Step 4: 异常修复 ({total} 条, 最大重试: {self.max_retries})")
        self.logger.info(f"  {'='*50}")

        tasks = []
        for _, row in abnormal_rows.iterrows():
            sid = row['session_id']
            qid = row['query_id']
            # 从原始数据获取 main_demand
            known = ""
            match = source_df[(source_df['session_id'].astype(str) == str(sid)) &
                              (source_df['query_id'].astype(int) == int(qid))]
            if len(match) > 0:
                known = str(match.iloc[0].get('main_demand', '')).strip()
                if known == 'nan':
                    known = ""

            tasks.append(self.fix_one(row, known))

        results = await asyncio.gather(*tasks)
        return results


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-retries", type=int, default=5)
    ap.add_argument("--task", default=None, help="任务名称（默认从 config 自动提取）")
    ap.add_argument("--step3-dir", default=None, help="step3 输出目录（默认从评估数据/自动查找）")
    ap.add_argument("--step2-dir", default=None, help="step2 输出目录（默认 output_step2）")
    ap.add_argument("--source", default=INPUT_FILE, help="原始数据（用于获取 main_demand）")
    args = ap.parse_args()

    task = args.task or TASK_NAME
    step3_dir = args.step3_dir or EVAL_DATA

    # 1. 找到最新的 step3 输出文件
    files = sorted(glob.glob(f"{step3_dir}/*-step3-*.xlsx"), reverse=True)
    if not files:
        print(f"找不到 step3 输出文件（{step3_dir}/*-step3-*.xlsx）")
        sys.exit(1)
    step3_file = files[0]
    print(f"📂 step3 文件: {step3_file}")

    # 2. 读取
    df_step3 = pd.read_excel(step3_file)
    print(f"   总计: {len(df_step3)} 条")

    # 3. 找异常
    abnormal_mask = df_step3.apply(is_abnormal, axis=1)
    abnormal = df_step3[abnormal_mask]
    normal = df_step3[~abnormal_mask]

    # 对 step3 输入做基本的列名校验
    required = ["session_id", "query_id", "query", "answer", "key_point", "score"]
    missing_cols = [c for c in required if c not in df_step3.columns]
    if missing_cols:
        print(f"❌ step3 输出缺少必需列: {missing_cols}")
        print(f"   当前列: {list(df_step3.columns)}")
        sys.exit(1)

    print(f"   正常: {len(normal)} 条")
    print(f"   异常: {len(abnormal)} 条 (空考点: {(abnormal['key_point'].isna()|(abnormal['key_point'].astype(str).str.strip().eq(''))).sum()}, -1分: {(abnormal['score']==-1).sum()})")

    if len(abnormal) == 0:
        print("\n✅ 无异常，无需修复")
        return

    # 4. 读取原始数据
    if not os.path.exists(args.source):
        print(f"找不到原始数据: {args.source}")
        sys.exit(1)
    df_src = pd.read_excel(args.source)
    print(f"📂 原始数据: {args.source} ({len(df_src)} 条)")

    # 5. 修复
    evaluator = RetryEvaluator(max_retries=args.max_retries, task=task)
    fixed_results = await evaluator.run(abnormal, df_src)

    # 6. 合并
    df_fixed = pd.DataFrame(fixed_results)
    df_final = pd.concat([normal, df_fixed], ignore_index=True)
    df_final = df_final.sort_values(['session_id', 'query_id']).reset_index(drop=True)

    # 7. 输出
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = get_step3_data_path(task or "default", "修复")
    df_final.to_excel(out, index=False)

    print(f"\n{'='*50}")
    print(f"✅ Step 4 完成!")
    print(f"   修复成功: {evaluator.fixed} | 跳过: {evaluator.skipped}")
    print(f"   输出: {out}")
    print(f"   {evaluator.token_tracker.summary()}")

    # 统计
    abnormal_after = len(df_final[df_final.apply(is_abnormal, axis=1)])
    print(f"   修复后剩余异常: {abnormal_after} 条")


if __name__ == "__main__":
    asyncio.run(main())