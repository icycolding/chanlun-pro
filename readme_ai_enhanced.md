# 缠论AI分析增强版使用指南

## 概述

增强版AI分析功能通过集成本地知识库，为缠论技术分析提供更专业、更准确的AI分析结果。系统会根据当前的缠论数据自动搜索相关理论知识，并将这些知识融入到AI分析提示词中，从而获得更有针对性的分析建议。

## 核心功能

### 1. 知识库管理
- **自动初始化**: 首次使用时自动创建包含基础缠论理论的知识库
- **分类管理**: 按照买卖点、技术指标、中枢理论等分类组织知识
- **智能搜索**: 使用TF-IDF和余弦相似度进行语义搜索
- **持久化存储**: 知识库数据自动保存到本地文件

### 2. 增强分析
- **智能关键词提取**: 根据当前缠论数据自动提取搜索关键词
- **知识融合**: 将相关理论知识融入AI分析提示词
- **分类过滤**: 可以限制搜索特定分类的知识
- **数量控制**: 可以控制引用的知识文档数量

## 安装和配置

### 1. 安装依赖
```bash
# 激活conda环境
conda activate quant

# 安装中文分词库
pip install jieba
```

### 2. 文件结构
```
src/chanlun/tools/
├── ai_analyse_enhanced.py    # 增强版AI分析类
├── knowledge_base.py         # 知识库管理类
└── ai_analyse.py            # 原始AI分析类
```

### 3. 知识库存储位置
知识库文件存储在用户数据目录下：
```
~/.chanlun_pro/knowledge_base/
├── {kb_name}/
│   ├── documents.json        # 文档数据
│   ├── vectors.pkl          # 向量数据
│   └── vectorizer.pkl       # 向量化器
```

## 使用方法

### 1. 基础使用

```python
from chanlun.tools.ai_analyse_enhanced import AIAnalyseEnhanced

# 创建增强版AI分析器
ai = AIAnalyseEnhanced("a")  # "a"表示A股市场

# 进行增强分析
result = ai.analyse_with_knowledge(
    code='000001',      # 股票代码
    frequency='30m',    # 时间周期
    use_knowledge=True  # 启用知识库增强
)

# 检查结果
if result['ok']:
    print("AI分析结果:", result['msg'])
else:
    print("分析失败:", result['msg'])
```

### 2. 高级配置

```python
# 限制知识库搜索分类
result = ai.analyse_with_knowledge(
    code='000001',
    frequency='30m',
    use_knowledge=True,
    knowledge_categories=['买卖点实战', '技术指标实战'],  # 只搜索这些分类
    max_knowledge_docs=3  # 最多引用3个知识文档
)

# 不使用知识库增强（等同于原始分析）
result = ai.analyse_with_knowledge(
    code='000001',
    frequency='30m',
    use_knowledge=False
)
```

### 3. 知识库管理

```python
# 查看知识库统计信息
stats = ai.get_knowledge_stats()
print(f"总文档数: {stats['total_documents']}")
print(f"分类: {stats['categories']}")

# 添加自定义知识
success = ai.add_knowledge(
    title="自定义买点策略",
    content="这是我的个人交易经验...",
    category="个人经验"
)

# 搜索知识库
results = ai.search_knowledge(
    query="一买点操作",
    top_k=5,
    category="买卖点实战"  # 可选：限制搜索分类
)

for result in results:
    print(f"标题: {result['title']}")
    print(f"相似度: {result['similarity']:.3f}")
    print(f"内容: {result['content'][:100]}...")
```

## 知识库分类说明

### 默认分类
- **缠论理论**: 基础理论概念和定义
- **买卖点理论**: 各类买卖点的理论说明
- **背驰理论**: 背驰相关的理论知识
- **中枢理论**: 中枢相关的理论知识

### 实战分类
- **买卖点实战**: 买卖点的实际操作技巧
- **技术指标实战**: MACD、RSI等指标的实战应用
- **中枢实战**: 中枢震荡和突破的实战策略
- **背驰实战**: 背驰信号的实战确认方法
- **线段实战**: 线段划分的实战技巧
- **风险管理**: 资金管理和风险控制
- **综合分析**: 多周期、多指标综合分析

## 工作原理

### 1. 知识增强流程
```
1. 获取缠论数据 → 2. 提取关键词 → 3. 搜索知识库 → 4. 构建增强提示词 → 5. 调用AI模型
```

### 2. 关键词提取逻辑
系统会根据当前缠论数据自动提取搜索关键词：
- **买卖点**: 根据检测到的买卖点类型（一买、二买、三买等）
- **背驰**: 根据检测到的背驰类型（笔背驰、线段背驰等）
- **中枢**: 根据中枢状态（上涨趋势、下跌趋势、中枢扩展）
- **线段**: 根据线段方向和状态

### 3. 知识融合策略
- **相似度排序**: 按照语义相似度对搜索结果排序
- **去重处理**: 避免重复引用相同的知识文档
- **数量限制**: 控制引用的知识文档数量，避免提示词过长
- **分类过滤**: 可以限制搜索特定分类的知识

## 配置选项

### AI模型配置
在 `src/chanlun/config.py` 中配置AI模型：

```python
# OpenRouter配置
OPENROUTER_AI_KEYS = "your_openrouter_api_key"
OPENROUTER_AI_MODEL = "google/gemini-2.5-pro-preview"

# SiliconFlow配置
AI_TOKEN = "your_siliconflow_token"
AI_MODEL = "your_model_name"
```

### 知识库配置
```python
# 创建自定义知识库
ai = AIAnalyseEnhanced("a", kb_name="my_custom_kb")

# 知识库会自动保存到:
# ~/.chanlun_pro/knowledge_base/my_custom_kb/
```

## 最佳实践

### 1. 知识库维护
- **定期更新**: 根据市场变化和交易经验更新知识库
- **分类管理**: 合理使用分类，便于后续搜索和管理
- **质量控制**: 确保添加的知识准确、实用

### 2. 分析参数调优
- **分类选择**: 根据当前市场情况选择相关分类
- **文档数量**: 平衡知识丰富度和提示词长度
- **相似度阈值**: 通过观察搜索结果调整相似度要求

### 3. 实战应用
- **多周期验证**: 结合不同时间周期的分析结果
- **风险控制**: 始终关注风险管理相关的知识
- **经验积累**: 将成功的交易经验添加到知识库

## 故障排除

### 常见问题

1. **知识库为空**
   - 检查是否正确初始化知识库
   - 确认知识库文件路径是否正确

2. **搜索结果不准确**
   - 调整搜索关键词
   - 检查知识库内容质量
   - 尝试不同的分类过滤

3. **AI分析失败**
   - 检查AI模型配置
   - 确认API密钥有效性
   - 检查网络连接

### 调试方法

```python
# 启用调试信息
result = ai.analyse_with_knowledge(
    code='000001',
    frequency='30m',
    use_knowledge=True
)

# 检查知识库状态
stats = ai.get_knowledge_stats()
print(f"知识库状态: {stats}")

# 测试知识搜索
results = ai.search_knowledge("测试查询")
print(f"搜索结果: {len(results)} 个")
```

## 示例代码

完整的使用示例请参考：
- `test_enhanced_ai.py`: 基础功能测试
- `example_enhanced_analysis.py`: 完整使用演示

## 更新日志

### v1.0.0
- 初始版本发布
- 支持知识库管理和增强分析
- 包含默认缠论理论知识库
- 支持自定义知识添加和搜索

---

**注意**: 使用增强版AI分析功能需要配置有效的AI模型API密钥。建议在实际交易中结合多种分析方法，不要完全依赖AI分析结果。