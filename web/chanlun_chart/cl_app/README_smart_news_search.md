# 智能新闻搜索系统

## 📖 概述

智能新闻搜索系统是一个强大的自动化新闻检索工具，能够根据股票代码（如 `R:2015.HK`、`2015.HK`、`2015`）或公司名称（如 `理想汽车`）精确找到相关新闻。系统支持多种输入格式的智能匹配，包括股票代码到公司名称的映射，以及基于语义搜索的新闻检索功能。

## ✨ 核心功能

### 🎯 智能识别
- **多格式股票代码支持**: `R:2015.HK`、`2015.HK`、`02015`、`2015` 等
- **公司名称识别**: 支持中英文公司名称，如 `理想汽车`、`Apple Inc.`
- **别名匹配**: 自动匹配公司的各种别名和简称
- **交易所识别**: 支持港股(HK)、美股(US)、A股(CN)等多个市场

### 🔍 智能搜索
- **语义搜索**: 基于向量数据库的语义相似度搜索
- **混合搜索**: 结合关键词匹配和语义搜索
- **时间过滤**: 支持指定时间范围内的新闻搜索
- **相关性排序**: 智能评分和结果排序

### 🌐 API接口
- **RESTful API**: 完整的Web API接口
- **批量处理**: 支持批量股票新闻搜索
- **健康检查**: 系统状态监控
- **统计信息**: 搜索结果统计和分析

## 📁 文件结构

```
cl_app/
├── smart_news_search.py          # 核心搜索模块
├── stock_mappings.json           # 股票代码映射配置
├── smart_news_api.py             # Web API接口
├── test_smart_news_search.py     # 核心功能测试
├── test_smart_news_api.py        # API接口测试
├── smart_news_usage_examples.py  # 使用示例
└── README_smart_news_search.md   # 本文档
```

## 🚀 快速开始

### 1. 直接使用Python模块

```python
from smart_news_search import SmartNewsSearcher, StockCodeMapper
from news_vector_db import NewsVectorDB

# 初始化组件
vector_db = NewsVectorDB()
searcher = SmartNewsSearcher(vector_db)

# 搜索新闻
result = searcher.search_news_by_stock(
    stock_input="R:2015.HK",  # 或 "理想汽车"
    n_results=20,
    days_back=30
)

if result['success']:
    print(f"找到 {result['total_found']} 条相关新闻")
    print(f"公司: {result['stock_info'].name}")
    for news in result['results'][:5]:
        print(f"- {news['title']}")
```

### 2. 使用API接口

#### 启动API服务
```bash
python smart_news_api.py
```

#### API调用示例
```python
import requests

# 智能搜索
response = requests.post('http://localhost:5001/api/smart_news/search', json={
    "stock_input": "理想汽车",
    "n_results": 20,
    "days_back": 30,
    "include_related": True
})

result = response.json()
if result['success']:
    print(f"找到 {result['data']['total_found']} 条新闻")
```

## 🔧 API接口文档

### 基础URL
```
http://localhost:5001/api/smart_news
```

### 接口列表

#### 1. 智能新闻搜索
- **URL**: `POST /search`
- **功能**: 根据股票代码或公司名称搜索相关新闻
- **请求体**:
```json
{
    "stock_input": "R:2015.HK",
    "n_results": 20,
    "days_back": 30,
    "include_related": true
}
```

#### 2. 股票代码解析
- **URL**: `POST /parse_stock`
- **功能**: 解析和识别股票代码或公司名称
- **请求体**:
```json
{
    "stock_input": "R:2015.HK"
}
```

#### 3. 快速搜索
- **URL**: `GET /quick_search/<stock_input>`
- **功能**: 快速搜索接口（GET请求）
- **查询参数**: `n_results`, `days_back`

#### 4. 系统统计
- **URL**: `GET /stats`
- **功能**: 获取系统统计信息

#### 5. 健康检查
- **URL**: `GET /health`
- **功能**: 检查系统健康状态

## 🧪 测试

### 运行核心功能测试
```bash
python test_smart_news_search.py
```

### 运行API接口测试
```bash
# 先启动API服务
python smart_news_api.py

# 在另一个终端运行测试
python test_smart_news_api.py
```

### 查看使用示例
```bash
python smart_news_usage_examples.py
```

## 📊 支持的股票市场

| 市场 | 代码格式示例 | 交易所 |
|------|-------------|--------|
| 港股 | `0700.HK`, `00700`, `700` | HKEX |
| 美股 | `AAPL`, `TSLA` | NASDAQ/NYSE |
| A股 | `000001`, `600000` | SSE/SZSE |

## 🎯 使用场景

### 1. 金融分析师
- 快速获取特定股票的最新新闻
- 批量分析多个股票的新闻情况
- 监控市场热点和舆情变化

### 2. 投资者
- 了解持仓股票的最新动态
- 研究潜在投资标的的新闻背景
- 跟踪关注股票的重要消息

### 3. 系统集成
- 集成到现有的金融分析系统
- 为交易系统提供新闻数据支持
- 构建自动化的新闻监控服务

## ⚙️ 配置说明

### 股票映射配置 (`stock_mappings.json`)
```json
{
  "stock_mappings": {
    "02015": {
      "name": "理想汽车",
      "code": "02015",
      "exchange": "HKEX",
      "market_type": "HK",
      "aliases": ["理想汽车", "Li Auto", "LI"]
    }
  },
  "code_patterns": {
    "HK": "^(R:)?(\\d{4,5})(\\.HK)?$"
  },
  "exchange_info": {
    "HKEX": {
      "name": "香港交易所",
      "market_type": "HK"
    }
  }
}
```

## 🔍 搜索算法

### 智能匹配流程
1. **输入解析**: 识别输入是股票代码还是公司名称
2. **代码标准化**: 将各种格式的股票代码标准化
3. **映射查找**: 在预定义映射中查找匹配项
4. **别名匹配**: 搜索公司名称和别名
5. **语义搜索**: 使用向量数据库进行语义相似度搜索
6. **结果合并**: 智能合并和去重搜索结果
7. **相关性评分**: 根据匹配度和时间因素评分排序

### 搜索策略
- **精确匹配优先**: 优先返回精确匹配的结果
- **语义扩展**: 使用语义搜索扩展相关结果
- **时间权重**: 较新的新闻获得更高权重
- **相关性过滤**: 过滤低相关性的结果

## 📈 性能优化

### 缓存策略
- 股票映射信息缓存
- 搜索结果缓存（可选）
- 向量数据库连接池

### 批量处理
- 支持批量股票搜索
- 异步处理大量请求
- 结果分页和限制

## 🛠️ 扩展开发

### 添加新的股票映射
1. 编辑 `stock_mappings.json` 文件
2. 添加新的股票信息
3. 重启系统加载新配置

### 自定义搜索算法
1. 继承 `SmartNewsSearcher` 类
2. 重写 `_search_with_strategy` 方法
3. 实现自定义的搜索逻辑

### 集成到现有系统
```python
from smart_news_api import register_smart_news_api
from flask import Flask

app = Flask(__name__)
register_smart_news_api(app)  # 注册API路由
```

## 🐛 故障排除

### 常见问题

#### 1. 无法识别股票代码
- 检查 `stock_mappings.json` 中是否包含该股票
- 确认股票代码格式是否正确
- 查看日志中的解析过程

#### 2. 搜索结果为空
- 确认向量数据库中有相关新闻数据
- 检查时间范围设置是否合理
- 尝试使用不同的搜索关键词

#### 3. API服务无法启动
- 检查端口5001是否被占用
- 确认所有依赖模块已正确安装
- 查看错误日志获取详细信息

### 调试模式
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 启用详细日志
searcher = SmartNewsSearcher(vector_db, debug=True)
```

## 📝 更新日志

### v1.0.0 (2024-01-20)
- ✨ 初始版本发布
- 🎯 支持多格式股票代码识别
- 🔍 实现智能新闻搜索功能
- 🌐 提供完整的RESTful API
- 🧪 包含完整的测试套件
- 📚 提供详细的使用示例

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目！

## 📄 许可证

本项目采用MIT许可证。

---

**🎉 现在您可以轻松地根据股票代码或公司名称自动化精确找到相关新闻了！**