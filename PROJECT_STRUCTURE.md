# 项目结构说明

## 项目概述

缠论市场 WEB 分析工具 (chanlun-pro) - 基于新闻向量与大语言模型的量化分析平台，专注于外汇市场的量化分析平台，包含深度历史回测、实时信号监控、前瞻性情景分析功能。

## 目录结构

```
chanlun-pro/
├── README.md                    # 项目说明文档
├── LICENSE                      # Apache 2.0 开源协议
├── .gitignore                   # Git忽略文件配置
├── requirements.txt             # Python依赖包列表
├── pyproject.toml              # 项目配置文件
├── setup.py                    # 安装配置脚本
├── MANIFEST.in                 # 打包配置文件
├── check_env.py                # 环境检查脚本
├── .readthedocs.yaml           # 文档构建配置
│
├── src/                        # 核心源代码目录
│   ├── chanlun/               # 缠论分析核心模块
│   │   ├── __init__.py
│   │   ├── cl.py              # 缠论核心算法
│   │   ├── cl_interface.py    # 缠论接口模块
│   │   ├── cl_analyse.py      # 缠论分析模块
│   │   ├── cl_utils.py        # 缠论工具函数
│   │   ├── db.py              # 数据库操作模块
│   │   ├── file_db.py         # 文件数据库模块
│   │   ├── kcharts.py         # K线图表模块
│   │   ├── monitor.py         # 监控模块
│   │   ├── config.py.demo     # 配置文件模板
│   │   ├── databases.sql      # 数据库结构
│   │   ├── exchange/          # 交易所接口
│   │   ├── strategy/          # 交易策略
│   │   ├── backtesting/       # 回测模块
│   │   ├── trader/            # 交易模块
│   │   ├── tools/             # 工具模块
│   │   └── others/            # 其他模块
│   │
│   ├── cl_vnpy/               # VN.PY集成模块
│   ├── cl_wtpy/               # WT.PY集成模块
│   └── cl_myquant/            # MyQuant集成模块
│
├── web/                       # Web应用目录
│   ├── chanlun_chart/         # 图表Web应用
│   │   ├── cl_app/           # Flask应用主体
│   │   ├── static/           # 静态资源
│   │   ├── templates/        # HTML模板
│   │   └── run.py            # 启动脚本
│   │
│   ├── chanlun_web/          # 主Web应用
│   └── chanlun_demo/         # 演示应用
│
├── script/                   # 脚本目录
│   ├── install/              # 安装脚本
│   ├── data/                 # 数据处理脚本
│   └── tools/                # 工具脚本
│
├── notebook/                 # Jupyter笔记本
│   ├── examples/             # 示例笔记本
│   └── tutorials/            # 教程笔记本
│
├── cookbook/                 # 文档和示例
│   ├── docs/                 # 文档源码
│   └── examples/             # 代码示例
│
├── joinquant/               # 聚宽平台集成
├── package/                 # 第三方包
├── docs/                    # 项目文档
└── data/                    # 数据目录（运行时创建）
```

## 核心功能模块

### 1. 缠论分析引擎 (src/chanlun/)
- **cl.py**: 缠论核心算法实现，包含笔、线段、中枢等核心概念
- **cl_interface.py**: 对外接口，提供统一的缠论分析入口
- **cl_analyse.py**: 高级分析功能，包含买卖点识别、趋势判断等
- **cl_utils.py**: 工具函数集合

### 2. 数据管理 (src/chanlun/)
- **db.py**: 数据库操作，支持MySQL、Redis等
- **file_db.py**: 文件数据库，用于本地数据存储
- **exchange/**: 各大交易所数据接口集成

### 3. Web界面 (web/)
- **chanlun_chart/**: 主要的图表分析界面
- **chanlun_web/**: 综合Web管理界面
- **chanlun_demo/**: 功能演示界面

### 4. 交易策略 (src/chanlun/strategy/)
- 基于缠论的各种交易策略实现
- 策略回测和优化工具

### 5. 回测系统 (src/chanlun/backtesting/)
- 历史数据回测引擎
- 性能指标计算和分析

## 技术栈

- **后端**: Python 3.11+, Flask, SQLAlchemy
- **前端**: HTML5, JavaScript, ECharts, Bootstrap
- **数据库**: MySQL, Redis
- **数据源**: 多个交易所API, 聚宽, 东财等
- **图表**: PyECharts, ECharts
- **机器学习**: 支持向量数据库和大语言模型集成

## 部署方式

1. **本地部署**: 直接运行Python脚本
2. **Docker部署**: 支持容器化部署
3. **云端部署**: 支持各大云平台部署

## 开发环境要求

- Python 3.11+
- MySQL 5.7+
- Redis 6.0+
- TA-Lib技术分析库

## 许可证

本项目采用 Apache License 2.0 开源协议。