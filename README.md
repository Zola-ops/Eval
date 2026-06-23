# EVAL.V2 — AI 搜索质量评估流水线

> 自动化评估 AI 搜索回答质量的多步骤流水线，支持断点续传、多模型并行、异常自动修复。

GitHub: https://github.com/Zola-ops/Eval

## 核心特性

- **5 步流水线**：从搜索增强到最终评分，全自动完成
- **3 模型并行**：DeepSeek-V4-Flash、Kimi-K2.5、MiniMax-M2.7
- **断点续传**：任意步骤中断后可从断点恢复，避免重复计算
- **异常修复**：自动检测异常结果并触发重试和重新分类
- **Bing MCP 集成**：支持搜索增强和 query 改写

## 流水线流程

```
step0_enrich.py     → 搜索增强（Bing MCP + query改写）
step1_gen.py        → 考点生成（3模型并行）
step2_summary.py    → 置信度评估（显性×0.5 + 必要×0.25 + 一致性×0.25）
step3_score.py      → 评分 + 分类（两轮调用）
step4_retry.py      → 异常修复（重试 + 重新分类）
```

### 流程说明

| 步骤 | 脚本 | 功能 | 说明 |
|------|------|------|------|
| 0 | `step0_enrich.py` | 搜索增强 | 通过 Bing MCP 补充外部信息并改写 query |
| 1 | `step1_gen.py` | 考点生成 | 调用 3 个模型并行生成考点回答 |
| 2 | `step2_summary.py` | 置信度评估 | 多维度加权评分：显性(0.5) + 必要(0.25) + 一致性(0.25) |
| 3 | `step3_score.py` | 评分 + 分类 | 两轮 LLM 调用完成综合评分与分类 |
| 4 | `step4_retry.py` | 异常修复 | 对异常结果自动重试并重新分类 |

## 使用方法

### 运行完整流水线

```bash
bash run_eval.sh 评估-pc百度
```

### 单独运行某步骤

```bash
# 运行搜索增强
python3 step0_enrich.py ~/Desktop/评估-pc百度.xlsx --task 评估-pc百度

# 运行评分
python3 step3_score.py --task 评估-pc百度

# 运行考点生成
python3 step1_gen.py --config models/xxx.py --task 评估-pc百度
```

### 断点管理

```bash
# 重置断点，从头开始
python3 step1_gen.py --config models/xxx.py --task 评估-pc百度 --reset
```

### 高级选项

```bash
# 启用 LLM 查询分类
USE_LLM_CLASSIFY=1 bash run_eval.sh 评估-pc百度
```

## 目录结构

```
EVAL.V2/
├── 评估代码/        ← 所有脚本（enrich、gen、summary、score、retry）
├── 评估断点/        ← 断点续传文件（自动生成）
├── 评估日志/        ← 运行日志（自动生成）
└── 评估数据/        ← 输入输出数据（自动生成）
```

## 文件命名规范

```
{任务名}-{步骤}[-{模型}]-{类型}.{ext}

示例：
评估-pc百度-step1-DeepSeek-V4-Flash-断点.json
评估-pc百度-step2-置信度.json
评估-pc百度-step3-评分-分类.json
```

## 模型配置

| 模型 | 用途 |
|------|------|
| DeepSeek-V4-Flash | 考点生成 + 评分 |
| Kimi-K2.5 | 考点生成 + 评分 |
| MiniMax-M2.7 | 考点生成 + 评分 |

编辑 `评估代码/config.py` 配置以下参数：

- **API 密钥**：各模型的访问凭证
- **模型配置**：模型名称、endpoint、参数
- **运行参数**：并发数、温度等
- **目录路径**：输入输出目录

## 环境依赖

- Python 3.x
- Bing MCP（搜索增强）
- 各模型 API 访问权限

## 许可证

本项目为评估工具，详见仓库。
