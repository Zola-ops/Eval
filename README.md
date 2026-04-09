# 评估器工具包 (Evaluator Package)

基于大语言模型的自动化评估工具，支持生成考点、评分和问题类型分类。

## 功能特性

- **考点生成**: 根据用户问题自动生成1分/0分判定考点
- **智能评分**: 基于Checklist的二分类评分（0分/1分）
- **问题分类**: 自动识别回答存在的问题类型
- **批量处理**: 支持Excel文件批量评估
- **多模型支持**: 支持豆包、智谱等多种API

## 评分标准

### 0分判定（任一命中即0分）

1. 需求未对齐或明显偏离
2. 任务未完成或未提供核心结果
3. 未满足关键约束
4. 内容无效或无价值
5. 存在明显错误或误导

### 1分判定（Checklist - 需全部满足）

1. 需求对齐
2. 核心结果完整
3. 核心结论正确
4. 整体准确率达标（50%以上）
5. 内容可用性
6. 实际价值（解决80%以上问题）

## 快速开始

### 1. 安装依赖

```bash
pip install openpyxl requests jinja2
```

### 2. 配置API

创建配置文件（参考`豆包评估配置.json`）:

```json
{
  "config": {
    "model": "your-model",
    "temperature": 0.01,
    "max_completion_tokens": 29000
  },
  "api_url": "your-api-url",
  "api_token": "your-api-token"
}
```

### 3. 运行评估

```bash
# 单条评估
python 豆包评估.py --query "问题" --answer "回答"

# 批量评估
python 豆包评估.py --excel input.xlsx --output result.xlsx
```

## 输出字段

| 字段 | 说明 |
|------|------|
| kp_thinking | 考点生成思考过程 |
| kp_key_point_1 | 1分考点列表 |
| kp_key_point_0 | 0分考点列表 |
| scorer_key_point | 合并的评分考点 |
| keypoint_results | 考点判定结果 |
| score | 最终评分（0或1） |
| question_type | 问题类型 |

## 文件结构

```
.
├── 豆包评估.py              # 豆包API评估脚本
├── 智谱评估.py              # 智谱API评估脚本
├── 豆包评估配置.json        # 豆包API配置
├── 评估配置.json           # 智谱API配置
├── run_batch_eval.py       # 批量评估脚本（带进度保存）
├── convert_format.py       # 输出格式转换脚本
└── tests/                  # 测试文件
```

## License

MIT
