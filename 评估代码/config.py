"""
========================================
评估流水线配置文件 v5
========================================
所有脚本统一从本文件读取 API 配置和路径配置。

流程：
  0. 搜索增强（step0_enrich.py）
  1. 3 个不同模型各生成 1 次考点（step1_gen.py ×3）
  2. 置信度评估，合成最终考点（step2_summary.py）
  3. 评分+分类（step3_score.py）
  4. 异常修复（step4_retry.py）

目录结构：
  EVAL.V2/
  ├── 评估代码/        ← 所有脚本
  ├── 评估断点/        ← 断点续传文件
  ├── 评估日志/        ← 运行日志
  └── 评估数据/        ← 输入输出数据
========================================
"""

import os as _os
from pathlib import Path as _Path
from datetime import datetime as _datetime

# ========== 生成模型（Step 1 — 各自独立生成考点） ==========
GENERATION_MODELS = [
    {"name": "DeepSeek-V4-Flash", "base_url": "YOUR_API_BASE_URL",
     "api_key": "YOUR_API_KEY", "model": "DeepSeek-V4-Flash"},
    {"name": "Kimi-K2.5", "base_url": "YOUR_API_BASE_URL",
     "api_key": "YOUR_API_KEY", "model": "Kimi-K2.5"},
    {"name": "MiniMax-M2.7", "base_url": "YOUR_API_BASE_URL",
     "api_key": "YOUR_API_KEY", "model": "MiniMax-M2.7"},
]

# ========== 总结模型（Step 2 — 合成最终考点） ==========
SUMMARY_MODEL = {
    "name": "DeepSeek-V4-Flash",
    "base_url": "YOUR_API_BASE_URL",
    "api_key": "YOUR_API_KEY",
    "model": "DeepSeek-V4-Flash",
}

# ========== 评分模型（Step 3 — 考点逐条判定） ==========
SCORE_MODEL = {
    "name": "DeepSeek-V4-Flash",
    "base_url": "YOUR_API_BASE_URL",
    "api_key": "YOUR_API_KEY",
    "model": "DeepSeek-V4-Flash",
}

# ========== 分类模型（Step 4 — 问题类型标记） ==========
CLASSIFY_MODEL = {
    "name": "DeepSeek-V4-Flash",
    "base_url": "YOUR_API_BASE_URL",
    "api_key": "YOUR_API_KEY",
    "model": "DeepSeek-V4-Flash",
}

# ========== 文件配置 ==========

# 输入文件（留空，由命令行参数指定）
INPUT_FILE = ""


def get_input_file(task: str) -> str:
    """根据任务名获取输入文件路径"""
    path = _os.path.expanduser(f"~/Desktop/{task}.xlsx")
    if _os.path.exists(path):
        return path
    if INPUT_FILE and _os.path.exists(INPUT_FILE):
        return INPUT_FILE
    return path

# 任务名称（从输入文件名自动提取）
TASK_NAME = _os.path.splitext(_os.path.basename(INPUT_FILE))[0] if INPUT_FILE else "default"

# ========== 目录结构 ==========
EVAL_BASE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # EVAL.V2/
EVAL_DATA = _os.path.join(EVAL_BASE, "评估数据")
EVAL_CHECKPOINTS = _os.path.join(EVAL_BASE, "评估断点")
EVAL_LOGS = _os.path.join(EVAL_BASE, "评估日志")


def get_data_path(task: str, step: str, model: str = "") -> str:
    """生成评估数据路径: EVAL.V2/评估数据/{task}-{step}[-{model}]-{timestamp}.xlsx"""
    _Path(EVAL_DATA).mkdir(parents=True, exist_ok=True)
    name = f"{task}-{step}"
    if model:
        name += f"-{model}"
    ts = _datetime.now().strftime('%Y%m%d_%H%M%S')
    return _os.path.join(EVAL_DATA, f"{name}-{ts}.xlsx")


def get_step0_data_path(task: str) -> str:
    """step0 搜索增强输出路径"""
    return get_data_path(task, "step0")


def get_step1_data_path(task: str, model: str) -> str:
    """step1 考点生成输出路径"""
    return get_data_path(task, "step1", model)


def get_step2_data_path(task: str) -> str:
    """step2 置信度评估输出路径"""
    return get_data_path(task, "step2")


def get_step3_data_path(task: str, suffix: str = "") -> str:
    """step3 评分结果路径"""
    name = f"{task}-step3"
    if suffix:
        name += f"-{suffix}"
    ts = _datetime.now().strftime('%Y%m%d_%H%M%S')
    _Path(EVAL_DATA).mkdir(parents=True, exist_ok=True)
    return _os.path.join(EVAL_DATA, f"{name}-{ts}.xlsx")


def get_checkpoint_path(task: str, step: str, model: str = "") -> str:
    """生成断点路径: EVAL.V2/评估断点/{task}-{step}[-{model}]-断点.json"""
    _Path(EVAL_CHECKPOINTS).mkdir(parents=True, exist_ok=True)
    name = f"{task}-{step}"
    if model:
        name += f"-{model}"
    return _os.path.join(EVAL_CHECKPOINTS, f"{name}-断点.json")


def get_log_path(task: str, step: str, model: str = "") -> str:
    """生成日志路径: EVAL.V2/评估日志/{task}-{step}[-{model}]-日志.log"""
    _Path(EVAL_LOGS).mkdir(parents=True, exist_ok=True)
    name = f"{task}-{step}"
    if model:
        name += f"-{model}"
    return _os.path.join(EVAL_LOGS, f"{name}-日志.log")


# ========== 运行配置 ==========

# 考点生成并发数
CONCURRENCY = 10

# 评分类并发数（评分+分类请求多，可设高）
CONCURRENCY_SCORE = 10

# 温度
TEMPERATURE = 0.1

# API 请求间隔（秒）
DELAY_BETWEEN_REQUESTS = 0.3


# ========== 通用工具函数 ==========

import logging
import sys as _sys


def setup_logger(task_name: str, step_name: str) -> logging.Logger:
    """创建同时输出到控制台和文件的 logger"""
    logger = logging.getLogger(f"{task_name}.{step_name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    # 控制台
    ch = logging.StreamHandler(_sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    # 文件
    if task_name:
        log_file = get_log_path(task_name, step_name)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(fh)

    return logger


class TokenTracker:
    """累计统计 token 用量"""
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.calls = 0

    def add(self, usage):
        if usage:
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.total_tokens += getattr(usage, "total_tokens", 0) or 0
        self.calls += 1

    def summary(self) -> str:
        return (f"API调用: {self.calls}次 | "
                f"prompt: {self.prompt_tokens:,} | "
                f"completion: {self.completion_tokens:,} | "
                f"total: {self.total_tokens:,}")


def validate_columns(df, required_cols: list, step_name: str = ""):
    """校验 DataFrame 是否包含必需列，缺少则打印并退出"""
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        prefix = f"[{step_name}] " if step_name else ""
        print(f"❌ {prefix}缺少必需列: {missing}")
        print(f"   当前列: {list(df.columns)}")
        _sys.exit(1)


def check_input_data(df, logger=None) -> dict:
    """输入数据预检：空值、重复、超长，返回统计信息"""
    import pandas as _pd
    log = logger or (lambda msg: print(msg))
    issues = []
    stats = {
        "total": len(df),
        "sessions": df["session_id"].nunique() if "session_id" in df.columns else 0,
    }

    # 空 query
    if "query" in df.columns:
        empty_q = df["query"].isna() | (df["query"].astype(str).str.strip() == "")
        if empty_q.sum() > 0:
            issues.append(f"⚠️  空 query: {empty_q.sum()} 行")
            stats["empty_query"] = int(empty_q.sum())

    # 空 answer
    if "answer" in df.columns:
        empty_a = df["answer"].isna() | (df["answer"].astype(str).str.strip() == "")
        if empty_a.sum() > 0:
            issues.append(f"⚠️  空 answer: {empty_a.sum()} 行")
            stats["empty_answer"] = int(empty_a.sum())

    # session_id + query_id 重复
    if "session_id" in df.columns and "query_id" in df.columns:
        dup = df.duplicated(subset=["session_id", "query_id"], keep=False)
        if dup.sum() > 0:
            issues.append(f"⚠️  session_id+query_id 重复: {dup.sum()} 行")
            stats["duplicates"] = int(dup.sum())

    # answer 超长
    if "answer" in df.columns:
        ans_len = df["answer"].astype(str).str.len()
        long_threshold = 10000
        long_ans = ans_len > long_threshold
        if long_ans.sum() > 0:
            issues.append(f"⚠️  answer 超长(>{long_threshold}字): {long_ans.sum()} 行 (最长: {ans_len.max()})")
            stats["long_answer"] = int(long_ans.sum())
        stats["avg_answer_len"] = int(ans_len.mean())
        stats["median_answer_len"] = int(ans_len.median())

    # query 长度
    if "query" in df.columns:
        q_len = df["query"].astype(str).str.len()
        stats["avg_query_len"] = int(q_len.mean())

    for issue in issues:
        log(issue)

    log(f"📊 输入统计: {stats['total']}条 | {stats['sessions']}个session | "
        f"平均answer: {stats.get('avg_answer_len', 0)}字 | 平均query: {stats.get('avg_query_len', 0)}字")

    return stats


# 各步骤的必需列定义
COLS_STEP1 = ['session_id', 'query_id', 'query', 'answer']
COLS_STEP2 = ['session_id', 'query_id', 'query', 'answer']
COLS_STEP3 = ['session_id', 'query_id', 'query', 'answer', 'main_demand', 'key_point', 'key_point_json']
