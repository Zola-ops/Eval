#!/usr/bin/env python3
"""
========================================
公共工具函数
========================================
所有 step 脚本共享的解析、归一化、过滤、格式化、检查点管理等函数。
========================================
"""

import json
import re
from pathlib import Path


# ========== JSON 解析 ==========

def parse_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON，支持 markdown 包裹"""
    try:
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            json_str = text.split("```")[1].split("```")[0]
        else:
            json_str = text
        return json.loads(json_str.strip())
    except json.JSONDecodeError:
        return {}


# ========== 考点归一化 ==========

def normalize_keypoint(kp: dict) -> dict:
    """归一化考点结构，统一 key_point 格式，支持 weight 字段"""
    result = {
        "main_demand": kp.get("main_demand", "").strip(),
        "key_point": kp.get("key_point", []),
        "core_answer": kp.get("core_answer", "").strip() if kp.get("core_answer") else "",
        "exemption_boundary": kp.get("exemption_boundary", "").strip() if kp.get("exemption_boundary") else ""
    }
    if isinstance(result["key_point"], list):
        normalized = []
        for i, p in enumerate(result["key_point"]):
            if isinstance(p, dict):
                weight = p.get("weight", 100)
                if isinstance(weight, str):
                    try:
                        weight = int(weight.replace('%', '').strip())
                    except ValueError:
                        weight = 100
                normalized.append({
                    "id": p.get("id", i + 1),
                    "type": p.get("type", "core"),
                    "point": p.get("point", "").strip(),
                    "weight": weight
                })
            elif isinstance(p, str):
                normalized.append({"id": i + 1, "type": "core", "point": p.strip(), "weight": 100})
        result["key_point"] = [p for p in normalized if p["point"]]
    elif isinstance(result["key_point"], str):
        result["key_point"] = [{"id": 1, "type": "core", "point": result["key_point"].strip(), "weight": 100}]
    return result


def normalize_keypoint_lite(kp: dict) -> dict:
    """轻量归一化（不含 weight），用于 step4 等不需要权重的场景"""
    result = {
        "main_demand": kp.get("main_demand", "").strip(),
        "key_point": kp.get("key_point", []),
        "core_answer": kp.get("core_answer", "").strip() if kp.get("core_answer") else "",
        "exemption_boundary": kp.get("exemption_boundary", "").strip() if kp.get("exemption_boundary") else ""
    }
    if isinstance(result["key_point"], list):
        normalized = []
        for i, p in enumerate(result["key_point"]):
            if isinstance(p, dict):
                normalized.append({
                    "id": p.get("id", i + 1),
                    "type": p.get("type", "core"),
                    "point": p.get("point", "").strip()
                })
            elif isinstance(p, str):
                normalized.append({"id": i + 1, "type": "core", "point": p.strip()})
        result["key_point"] = [p for p in normalized if p["point"]]
    elif isinstance(result["key_point"], str):
        result["key_point"] = [{"id": 1, "type": "core", "point": result["key_point"].strip()}]
    return result


# ========== 考点过滤 ==========

def filter_keypoints(kp: dict) -> dict:
    """过滤考点：丢弃 weight<70 的，限制核心≤2、辅助≤3、总数≤4（旧逻辑，保留兼容）"""
    points = kp.get("key_point", [])
    if not points:
        return kp

    # 1. 按 weight 降序排列
    core = sorted([p for p in points if p.get("type") == "core"],
                  key=lambda x: x.get("weight", 0), reverse=True)
    bonus = sorted([p for p in points if p.get("type") == "bonus"],
                   key=lambda x: x.get("weight", 0), reverse=True)

    # 2. 丢弃 weight < 70 的考点
    core = [p for p in core if p.get("weight", 100) >= 70]
    bonus = [p for p in bonus if p.get("weight", 100) >= 70]

    # 3. 限制数量：核心≤2，辅助≤3，总数≤4
    core = core[:2]
    bonus = bonus[:min(3, 4 - len(core))]

    # 4. 重新编号
    filtered = []
    for i, p in enumerate(core + bonus):
        p["id"] = i + 1
        filtered.append(p)

    kp["key_point"] = filtered
    return kp


# ========== 置信度计算与过滤 ==========

# 置信度权重
CONFIDENCE_WEIGHTS = {
    "explicitness": 0.50,   # 显性程度
    "necessity": 0.25,      # 必要程度
    "consensus": 0.25,      # 多模型一致性
}

# 置信度阈值
TIER_HARD_CORE = 90     # ≥90 硬核心
TIER_SOFT_CORE = 80     # 80~89 软核心
TIER_BONUS = 70         # 70~79 加分项
# <70 丢弃


def compute_consensus(source_count: int, total_models: int = 3) -> float:
    """根据覆盖模型数计算一致性得分"""
    return (source_count / total_models) * 100


def estimate_source_count(point_text: str, model_outputs: list, threshold: float = 0.2) -> int:
    """估算某个考点被多少模型覆盖（基于 3-gram 关键词重叠 + 停用词过滤）"""
    STOPWORDS = set("的了是在和等包含需要是否可以进行以及或与对为中上下有被将从到也而但如所其这一不个把被让给对向")

    def clean(text):
        text = text.replace('[核心]', '').replace('[辅助]', '').replace('[硬核心]', '').replace('[软核心]', '').replace('[加分项]', '')
        return ''.join(c for c in text if '\u4e00' <= c <= '\u9fff')

    def get_ngrams(text, n=3):
        cleaned = clean(text)
        tokens = [c for c in cleaned if c not in STOPWORDS]
        return set(''.join(tokens[i:i+n]) for i in range(len(tokens) - n + 1))

    if not point_text or not model_outputs:
        return 1

    point_ngrams = get_ngrams(point_text)
    if not point_ngrams:
        return 1

    count = 0
    for model_text in model_outputs:
        if not model_text or model_text == 'nan':
            continue
        model_ngrams = get_ngrams(model_text)
        if not model_ngrams:
            continue
        overlap = len(point_ngrams & model_ngrams) / len(point_ngrams)
        if overlap >= threshold:
            count += 1

    return max(count, 1)


def compute_confidence(explicitness: float, necessity: float, source_count: int) -> float:
    """计算考点置信度

    Args:
        explicitness: 显性程度 (0-100)
        necessity: 必要程度 (0-100)
        source_count: 识别该考点的模型数 (1-3)

    Returns:
        置信度 (0-100)
    """
    consensus = compute_consensus(source_count)
    return (
        explicitness * CONFIDENCE_WEIGHTS["explicitness"] +
        necessity * CONFIDENCE_WEIGHTS["necessity"] +
        consensus * CONFIDENCE_WEIGHTS["consensus"]
    )


def assign_tier(confidence: float) -> tuple:
    """根据置信度分配层级

    Returns:
        (tier_name, type) — tier名称 和 core/bonus 类型
    """
    if confidence >= TIER_HARD_CORE:
        return ("硬核心", "core")
    elif confidence >= TIER_SOFT_CORE:
        return ("软核心", "core")
    elif confidence >= TIER_BONUS:
        return ("加分项", "bonus")
    else:
        return ("丢弃", None)


def filter_by_confidence(kp: dict) -> dict:
    """基于置信度过滤考点，限制核心≤2、加分项≤2、总数≤4

    要求 key_point 中每个考点包含 confidence 字段。
    安全保障：至少保留 1 个考点，且至少有 1 个核心考点。
    """
    points = kp.get("key_point", [])
    if not points:
        return kp

    # 按置信度降序排列
    points.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    # 分配层级和类型
    for p in points:
        tier_name, tier_type = assign_tier(p["confidence"])
        p["tier"] = tier_name
        p["type"] = tier_type

    # 丢弃 <70 的
    valid = [p for p in points if p.get("confidence", 0) >= TIER_BONUS]

    # 安全保障：如果全部被丢弃，保留置信度最高的 1 个作为硬核心
    if not valid:
        best = points[0]
        best["tier"] = "硬核心"
        best["type"] = "core"
        best["confidence"] = max(best.get("confidence", 0), 70)  # 兜底到70
        valid = [best]

    # 安全保障：如果没有核心考点，把置信度最高的提升为软核心
    cores = [p for p in valid if p["type"] == "core"]
    if not cores:
        best = valid[0]
        best["tier"] = "软核心"
        best["type"] = "core"
        best["confidence"] = max(best.get("confidence", 0), 80)  # 兜底到80

    # 限制数量：core≤2, bonus≤2, total≤4
    cores = [p for p in valid if p["type"] == "core"]
    bonuses = [p for p in valid if p["type"] == "bonus"]
    cores = cores[:2]
    bonuses = bonuses[:min(2, 4 - len(cores))]

    # 重新编号
    filtered = []
    for i, p in enumerate(cores + bonuses):
        p["id"] = i + 1
        filtered.append(p)

    kp["key_point"] = filtered
    return kp


# ========== 考点格式化 ==========

def format_keypoint(kp: dict) -> str:
    """格式化考点为可读字符串（含权重）"""
    points = kp.get('key_point', [])
    if not points:
        return ''
    formatted = []
    for p in points:
        if isinstance(p, dict):
            prefix = '[核心]' if p.get('type') == 'core' else '[辅助]'
            weight = p.get('weight', '')
            weight_str = f'({weight}%)' if weight else ''
            formatted.append(f"{p.get('id', '')}. {prefix}{p.get('point', '')}{weight_str}")
        else:
            formatted.append(str(p))
    return ' | '.join(formatted)


def format_keypoint_lite(kp: dict) -> str:
    """格式化考点（不含权重），用于 step4 等场景"""
    points = kp.get('key_point', [])
    if not points:
        return ''
    formatted = []
    for p in points:
        if isinstance(p, dict):
            prefix = '[核心]' if p.get('type') == 'core' else '[辅助]'
            formatted.append(f"{p.get('id', '')}. {prefix}{p.get('point', '')}")
        else:
            formatted.append(str(p))
    return ' | '.join(formatted)


def format_keypoint_confidence(kp: dict) -> str:
    """格式化置信度考点：1.[硬核心]考点内容(96.3)"""
    points = kp.get('key_point', [])
    if not points:
        return ''
    formatted = []
    for p in points:
        if isinstance(p, dict):
            tier = p.get('tier', '')
            conf = p.get('confidence', '')
            tier_str = f'[{tier}]' if tier else ''
            conf_str = f'({conf})' if conf else ''
            formatted.append(f"{p.get('id', '')}.{tier_str}{p.get('point', '')}{conf_str}")
        else:
            formatted.append(str(p))
    return ' | '.join(formatted)


# ========== 文本工具 ==========

def count_chinese_chars(text: str) -> int:
    """统计中文字符数"""
    if not text:
        return 0
    return len(re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]').findall(text))


# ========== 断点续传 ==========

class CheckpointManager:
    """断点续传管理器"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"processed": {}, "results": []}

    def save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, default=str)

    def is_processed(self, key: str) -> bool:
        return key in self.data["processed"]

    def mark_processed(self, key: str, result: dict):
        self.data["processed"][key] = True
        self.data["results"].append(result)

    def force_save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, default=str)

    def get_results(self) -> list:
        return self.data["results"]


# ========== 一致性分析 ==========

def compute_consistency(kps: list) -> dict:
    """计算多个模型考点的一致性指标

    Args:
        kps: list of (model_name, kp_dict) tuples

    Returns:
        dict with:
          - core_count_spread: 各模型核心考点数的 (min, max)
          - bonus_count_spread: 各模型辅助考点数的 (min, max)
          - demand_similarity: main_demand 是否一致
          - disagreement_level: LOW / MEDIUM / HIGH
    """
    if not kps:
        return {"disagreement_level": "NO_DATA"}

    core_counts = []
    bonus_counts = []
    demands = []

    for name, kp in kps:
        pts = kp.get("key_point", [])
        core_counts.append(sum(1 for p in pts if p.get("type") == "core"))
        bonus_counts.append(sum(1 for p in pts if p.get("type") == "bonus"))
        demands.append(kp.get("main_demand", "").strip())

    core_range = max(core_counts) - min(core_counts)
    bonus_range = max(bonus_counts) - min(bonus_counts)

    # main_demand 一致性：去除空值后是否全相同
    non_empty_demands = [d for d in demands if d]
    demand_unique = len(set(non_empty_demands)) if non_empty_demands else 0

    # 分歧等级判定
    if core_range <= 1 and bonus_range <= 1 and demand_unique <= 1:
        level = "LOW"
    elif core_range >= 3 or bonus_range >= 3 or demand_unique >= 3:
        level = "HIGH"
    else:
        level = "MEDIUM"

    return {
        "core_count_spread": (min(core_counts), max(core_counts)),
        "bonus_count_spread": (min(bonus_counts), max(bonus_counts)),
        "demand_unique_count": demand_unique,
        "disagreement_level": level,
    }
