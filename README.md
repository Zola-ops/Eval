# EVAL.V2 — AI 搜索质量评估流水线

自动化评估 AI 搜索回答质量的多步骤流水线。

## 流程

```
step0_enrich.py     → 搜索增强（Bing MCP + query改写）
step1_gen.py        → 考点生成（3模型并行）
step2_summary.py    → 置信度评估（显性×0.5 + 必要×0.25 + 一致性×0.25）
step3_score.py      → 评分 + 分类（两轮调用）
step4_retry.py      → 异常修复（重试 + 重新分类）
```

## 使用

```bash
# 运行完整流水线
bash run_eval.sh 评估-pc百度

# 单独运行某步骤
python3 step0_enrich.py ~/Desktop/评估-pc百度.xlsx --task 评估-pc百度
python3 step3_score.py --task 评估-pc百度

# 重置断点
python3 step1_gen.py --config models/xxx.py --task 评估-pc百度 --reset

# 启用 LLM 查询分类
USE_LLM_CLASSIFY=1 bash run_eval.sh 评估-pc百度
```

## 目录结构

```
EVAL.V2/
├── 评估代码/        ← 所有脚本
├── 评估断点/        ← 断点续传文件（自动生成）
├── 评估日志/        ← 运行日志（自动生成）
└── 评估数据/        ← 输入输出数据（自动生成）
```

## 文件命名

```
{任务名}-{步骤}[-{模型}]-{类型}.{ext}
示例：评估-pc百度-step1-DeepSeek-V4-Flash-断点.json
```

## 配置

编辑 `评估代码/config.py`：
- API 密钥和模型配置
- 并发数、温度等运行参数
- 目录路径

## 模型

- DeepSeek-V4-Flash
- Kimi-K2.5
- MiniMax-M2.7
