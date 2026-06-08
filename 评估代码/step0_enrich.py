#!/usr/bin/env python3
"""
========================================
Step 0: 查询预处理 — 搜索增强
========================================
读取输入 Excel，判断哪些 query 需要外部信息（事实/时效），
调用 Bing MCP 搜索获取参考信息，输出带 reference_context 的 Excel。

用法：
  python3 step0_enrich.py                         # 使用 config.py 的 INPUT_FILE
  python3 step0_enrich.py --dry-run               # 仅分类，不搜索
  python3 step0_enrich.py --batch 50              # 每批处理 50 条（默认全部）
========================================
"""

import json
import pandas as pd
import sys
import time
import os
import asyncio
import argparse
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import INPUT_FILE, TASK_NAME, setup_logger, get_step0_data_path

# ========== Bing MCP 配置 ==========
BING_MCP_URL = "YOUR_MCP_URL"
BING_MCP_TOKEN = "YOUR_MCP_TOKEN"

# ========== 查询分类提示词 ==========
CLASSIFY_PROMPT = """你是一位查询分析专家。判断以下用户查询是否需要外部信息才能准确评估。

# 查询类型
- factual：需要精确事实（距离、人数、数据、定义等），模型可能不知道或记忆不准确
- time_sensitive：需要时效信息（汇率、天气、新闻、股价、最新事件等）
- normal：常规查询（创作、解释、建议、对话等），模型自带知识足够

# 输出格式
只输出纯JSON，不要markdown：
{"type": "factual/time_sensitive/normal", "reason": "简要原因"}

# 示例
- "北京到上海多少公里" → factual
- "今天美元汇率" → time_sensitive
- "帮我写一首诗" → normal
- "Python怎么读取Excel" → normal
- "2024年诺贝尔物理学奖得主" → factual
- "今天的天气" → time_sensitive"""


class BingMCPClient:
    """Bing MCP 搜索客户端"""

    def __init__(self):
        self.url = BING_MCP_URL
        self.headers = {
            "Authorization": f"Bearer {BING_MCP_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        self.session_id = None
        self._req_id = 0

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _post(self, body: dict) -> dict:
        import requests
        headers = dict(self.headers)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        r = requests.post(self.url, headers=headers, json=body, timeout=(5, 15))
        if "mcp-session-id" in r.headers:
            self.session_id = r.headers["mcp-session-id"]
        if not r.text.strip():
            return {}
        return r.json()

    def initialize(self):
        resp = self._post({
            "jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "step0-enrich", "version": "1.0"}}
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp

    def search(self, query: str, count: int = 3, max_retries: int = 3) -> list:
        import requests as req
        for attempt in range(max_retries):
            try:
                # 每次重试都重新初始化连接
                if attempt > 0:
                    time.sleep(3)
                    self.session_id = None
                    self._req_id = 0
                    self.initialize()

                resp = self._post({
                    "jsonrpc": "2.0", "id": self._next_id(), "method": "tools/call",
                    "params": {"name": "bing_search", "arguments": {"query": query, "count": count}}
                })
                results = []
                for item in resp.get("result", {}).get("content", []):
                    if item.get("type") == "text":
                        try:
                            data = json.loads(item["text"])
                            for r in data.get("results", []):
                                results.append({
                                    "title": r.get("title", ""),
                                    "snippet": r.get("snippet", ""),
                                    "url": r.get("url", "")
                                })
                        except json.JSONDecodeError:
                            pass
                return results
            except Exception as e:
                if attempt == max_retries - 1:
                    raise


def rewrite_search_query(query: str, query_time: str = "") -> str:
    """改写查询为更适合搜索的形式"""
    q = query.strip()
    date_str = ""
    if query_time and query_time != 'nan':
        date_str = query_time[:10]

    # 替换相对时间表达
    time_replacements = {
        "今天": date_str,
        "今日": date_str,
        "昨天": "",  # 需要计算，暂时去掉
        "最近": "",
        "目前": "",
        "当前": "",
        "现在": "",
    }
    for old, new in time_replacements.items():
        if old in q and new:
            q = q.replace(old, new)

    # 去掉敬语/礼貌用语（搜索不需要）
    polite_phrases = ["请问", "请帮我", "帮我", "你能告诉我", "你知道"]
    for phrase in polite_phrases:
        q = q.replace(phrase, "")

    # 清理多余空格
    q = " ".join(q.split())

    # 如果有日期且还没加进去，前置拼接
    if date_str and date_str not in q:
        q = f"{date_str} {q}"

    return q
def classify_query_type(query: str, client=None, model: str = "") -> str:
    """用规则判断查询类型（LLM 分类已禁用，API 不稳定时可开启）"""
    # 规则预筛
    time_keywords = ["今天", "今日", "最新", "现在", "当前", "目前", "最近", "今年", "本月",
                     "汇率", "股价", "天气", "温度", "新闻", "价格", "实时", "天气预报"]
    factual_keywords = ["多少公里", "多少人", "多少个", "距离", "面积", "人口",
                        "什么时候", "哪一年", "定义", "谁发明", "第一次", "多少米",
                        "什么是", "谁是", "哪个国家", "哪个城市", "多少岁", "多大"]

    for kw in time_keywords:
        if kw in query:
            return "time_sensitive"
    for kw in factual_keywords:
        if kw in query:
            return "factual"

    # LLM 分类（默认关闭，设置 USE_LLM_CLASSIFY=1 启用）
    import os
    if os.environ.get("USE_LLM_CLASSIFY") != "1":
        return "normal"

    try:
        import requests
        from config import SCORE_MODEL
        resp = requests.post(
            f"{SCORE_MODEL['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {SCORE_MODEL['api_key']}", "Content-Type": "application/json"},
            json={
                "model": SCORE_MODEL["model"],
                "messages": [
                    {"role": "system", "content": "你是查询分类专家。只输出一个词：factual、time_sensitive 或 normal。"},
                    {"role": "user", "content": f"请判断以下查询类型：\n{query}"}
                ],
                "temperature": 0.1,
                "max_tokens": 4096
            },
            timeout=15
        )
        result = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip().lower()
        if "factual" in result:
            return "factual"
        if "time" in result or "sensitive" in result:
            return "time_sensitive"
        return "normal"
    except:
        return "normal"


def format_reference(results: list) -> str:
    """将搜索结果格式化为参考文本"""
    if not results:
        return ""
    parts = []
    for i, r in enumerate(results[:5], 1):
        parts.append(f"[{i}] {r['title']}\n{r['snippet']}")
    return "\n\n".join(parts)


async def main():
    parser = argparse.ArgumentParser(description="Step 0: 查询预处理（搜索增强）")
    parser.add_argument("input_file", nargs="?", default=INPUT_FILE)
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--dry-run", action="store_true", help="仅分类，不搜索")
    parser.add_argument("--batch", type=int, default=0, help="处理前N条（0=全部）")
    parser.add_argument("--task", default=None)
    args = parser.parse_args()

    task = args.task or TASK_NAME
    logger = setup_logger(task or "default", "step0")

    if not os.path.exists(args.input_file):
        print(f"❌ 找不到文件: {args.input_file}")
        sys.exit(1)

    df = pd.read_excel(args.input_file, sheet_name=0)
    total = len(df)
    if args.batch > 0:
        df = df.head(args.batch)

    logger.info(f"\n{'='*60}")
    logger.info(f"🚀 Step 0: 查询预处理（搜索增强）")
    logger.info(f"   数据量: {len(df)} 条 (总 {total})")
    logger.info(f"{'='*60}\n")

    # 1. 分类
    logger.info("📋 Step 0.1: 查询分类...")
    query_types = []
    for _, row in df.iterrows():
        q = str(row['query'])
        qt = classify_query_type(q, None, "")
        query_types.append(qt)

    df['query_type'] = query_types
    type_counts = df['query_type'].value_counts()
    logger.info(f"   分类结果: {dict(type_counts)}")

    if args.dry_run:
        output_path = args.output or f"{task}/step0_dryrun_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)
        logger.info(f"\n📁 Dry-run 输出: {output_path}")
        return

    # 2. 搜索
    need_search = df[df['query_type'].isin(['factual', 'time_sensitive'])]
    logger.info(f"\n🔍 Step 0.2: 搜索增强 ({len(need_search)} 条需要搜索)...")

    bing = BingMCPClient()
    bing.initialize()

    reference_map = {}
    for i, (_, row) in enumerate(need_search.iterrows()):
        q = str(row['query'])
        sid = str(row['session_id'])
        qid = int(row['query_id'])
        key = f"{sid}_{qid}"

        try:
            # 改写搜索 query
            query_time = str(row.get('query_time', ''))
            search_query = rewrite_search_query(q, query_time)

            results = bing.search(search_query, count=3)
            ref = format_reference(results)
            reference_map[key] = ref
            logger.info(f"  ✓ [{i+1}/{len(need_search)}] S{sid} Q{qid} | {len(results)}条结果")
        except Exception as e:
            reference_map[key] = ""
            logger.info(f"  ✗ [{i+1}/{len(need_search)}] S{sid} Q{qid} | 搜索失败: {str(e)[:50]}")

        time.sleep(1.5)  # 限速，避免连接被断

    # 3. 合并
    df['reference_context'] = df.apply(
        lambda row: reference_map.get(f"{row['session_id']}_{row['query_id']}", ""), axis=1
    )

    # 4. 输出
    output_path = args.output or get_step0_data_path(task)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(output_path, index=False)

    searched = sum(1 for v in reference_map.values() if v)
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Step 0 完成!")
    logger.info(f"   总查询: {len(df)} | 需搜索: {len(need_search)} | 搜到结果: {searched}")
    logger.info(f"   输出: {output_path}")
    logger.info(f"{'='*60}")

    # 输出路径到 stdout（供 run_eval.sh 捕获）
    print(f"OUTPUT_PATH:{output_path}")


if __name__ == '__main__':
    asyncio.run(main())
