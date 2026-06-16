# A股个股分析卡片增强（Workspace 落地 + 统一详情页）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `/a_share_matches` 的项目股票卡和 A 股映射卡新增“财务分析 + 最新新闻”摘要，并提供统一的个股分析详情页；数据以 Refinitiv Workspace 为主来源，先落本地再读取，失败时回退仓库现有新闻/财务数据。

**Architecture:** 页面首屏继续走现有静态 catalog + 批量异步补充模式。新增一个统一的个股分析服务模块，负责读取 Workspace 落地后的本地数据、生成卡片摘要、拼装详情页 payload，并在 Workspace 数据缺失时回退到现有 `news` / `company_financials` / 智能新闻搜索链路。同步层新增一个最小可用的 Workspace 入库入口，将新闻和财务数据写入现有本地存储结构，避免页面直接依赖桌面端或 SDK 实时调用。

**Tech Stack:** Flask、Jinja2、SQLAlchemy/`chanlun.db`、现有 Refinitiv/Eikon 原型、pytest

---

## Summary

- 在 [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html) 的两类卡片中新增两个信息区块：
  - `财务分析`：卡片展示规则化摘要。
  - `最新新闻`：卡片展示最近 3 条新闻标题 + 时间。
- 新增统一详情页 `个股分析详情`，同时支持：
  - 项目股票卡跳转。
  - A 股映射卡跳转。
- 详情页展示完整信息：
  - 基础信息与图表入口。
  - 规则化财务摘要。
  - AI 财务解读。
  - 最近 10 条新闻。
  - 数据来源与回退标记。
- 新增 Workspace 同步入口：
  - 接收 Workspace 导出的新闻/财务 payload。
  - 新闻写入现有 `news` 存储链路。
  - 财务数据写入现有 `company_financials` 表。
- 页面读取时优先消费 Workspace 落地数据；若无或失败，则回退现有本地新闻库/财务库。

## Current State Analysis

### 页面与卡片现状

- [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html#L868-L1068) 当前只为：
  - 项目股票卡展示 `Serenity 视角`、`推荐理由`、阶段/市值快照、缠论图、推荐脉络入口。
  - A 股映射卡展示供应链位置、映射路径、一句话判断、主要风险、缠论图。
- `a_share_matches` 页面已经有批量异步数据加载模式：
  - `/a_share_matches/project_ticks`
  - `/a_share_matches/tweet_summaries`
- 这意味着新增“财务分析 + 最新新闻”最稳妥的接入方式不是首屏全量同步计算，而是延续批量异步补充。

### 后端与数据现状

- [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L182-L206) 的 `_match(...)` 目前没有分析详情入口，也没有新闻/财务字段。
- [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L563-L605) 的 `_stock(...)` 目前也没有财务/新闻摘要字段。
- [__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py#L469-L645) 已经集中注册了 `a_share_matches` 相关页面路由与 API，是新增分析摘要 API、详情页路由的正确落点。
- 财务本地存储已存在：
  - [db.py](file:///Users/jiming/Documents/trae/chanlun-pro/src/chanlun/db.py#L41-L60) 定义 `company_financials` 表。
  - [db.py](file:///Users/jiming/Documents/trae/chanlun-pro/src/chanlun/db.py#L2267-L2336) 提供 `company_financials_insert()` / `company_financials_query()`。
- 新闻本地存储与检索已存在：
  - [db.py](file:///Users/jiming/Documents/trae/chanlun-pro/src/chanlun/db.py#L1597-L1660) 提供 `news_search()`。
  - [smart_news_search.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/smart_news_search.py#L320-L458) 提供 `search_news_by_stock()`，适合在普通关键词查询不足时回退。
- AI 财务分析链路已存在但封装在大文件中：
  - [news_vector_api.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/news_vector_api.py#L13280-L13395) 提供财务数据格式化 + AI 生成逻辑，可复用其 prompt 思路。
- Workspace / Eikon 原型已存在：
  - [newpost_ekion.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/newpost_ekion.py#L151-L289) 能从 Eikon/Refinitiv 获取新闻并转为本系统可消费格式。
  - [economic_data_receiver.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/economic_data_receiver.py#L470-L517) 已有财务数据落库模式。

### 测试现状

- [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py) 已覆盖 catalog 结构和主模板渲染。
- [test_a_share_matches_tweets.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_tweets.py) 已覆盖详情 URL、payload 和模板渲染的测试写法，可直接借鉴。
- 当前没有“个股分析统一服务 / 统一详情页 / Workspace 同步入口”的专项测试。

## Proposed Changes

### 1. 新增统一个股分析服务模块

**Create:** `web/chanlun_chart/cl_app/a_share_stock_analysis.py`

**职责**

- 统一描述两类分析对象：
  - `project`：项目股票卡，主键为 `symbol`。
  - `match`：A 股映射卡，主键为 `code`。
- 提供 URL helper：
  - `build_stock_analysis_detail_url(...)`
- 提供卡片批量摘要 builder：
  - `build_stock_analysis_summaries(items)`
- 提供详情页 payload builder：
  - `build_stock_analysis_detail_payload(...)`
- 提供 Workspace 落地数据读取与回退逻辑：
  - 财务优先读 `company_financials` 中由 Workspace 导入的最新数据。
  - 新闻优先读由 Workspace 导入的 `news` 数据。
  - 若命中不足，则回退到本地 `news_search()` / `search_news_by_stock()`。
- 负责生成两层财务内容：
  - 卡片：规则化摘要。
  - 详情：规则摘要 + AI 财务解读。

**实现决策**

- 卡片规则摘要不调用 AI，避免 `/a_share_matches` 首屏批量请求过重。
- 详情页 AI 解读按单只股票生成，失败时回退为“规则摘要扩展版 + 提示 AI 不可用”。
- 新闻卡片只展示最近 `3` 条；详情页展示最近 `10` 条。
- 统一返回数据来源标签：
  - `workspace`
  - `local_fallback`
  - `mixed`
  - `unavailable`

**建议输出 schema**

```python
{
    "entity_type": "project" | "match",
    "identifier": "SIVE" | "688498",
    "display_name": "...",
    "company_name": "...",
    "exchange": "...",
    "market": "...",
    "chart_url": "...",
    "financial_summary": "...",
    "financial_summary_short": "...",
    "financial_ai_analysis": "...",
    "financial_source": "workspace" | "local_fallback" | "unavailable",
    "news_source": "workspace" | "local_fallback" | "unavailable",
    "latest_news": [
        {"title": "...", "published_at": "...", "source": "..."}
    ],
    "detail_url": "...",
    "fallback_used": True | False,
}
```

**关键实现点**

- 项目股票使用 `symbol + company_name + display_name` 查询新闻。
- A 股映射卡使用 `code + name/display_name` 查询新闻。
- 财务查询：
  - `project` 对象优先用 `symbol`，必要时兼容 `company_name`。
  - `match` 对象直接用 A 股 `code`。
- AI 财务分析不要直接从模板里调用；统一封装在服务模块内，避免 Jinja 渲染时做重计算。
- 从 [news_vector_api.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/news_vector_api.py#L13280-L13395) 提炼可复用逻辑时，优先复制最小必需代码到新模块，避免让 `a_share_matches` 页面依赖整个超大文件。

### 2. 新增 Workspace 同步入口

**Create:** `web/chanlun_chart/cl_app/a_share_stock_analysis_workspace.py`

**Modify:** `web/chanlun_chart/cl_app/__init__.py`

**职责**

- 新增一个最小可用同步入口，接收 Workspace 导出的标准化 payload。
- 将新闻落入现有 `news` 存储。
- 将财务数据落入现有 `company_financials` 表。
- 不做桌面端自动化，不直接依赖“Mac 上已打开的 Workspace 应用窗口”；本次的“接入”定义为：
  - Workspace 是一级数据源。
  - 数据先通过导出/脚本/SDK 抓取后落本地。
  - 页面统一读本地存储。

**建议接口**

- `POST /api/workspace/stock-analysis/sync`

**建议入参**

```json
{
  "news_items": [
    {
      "entity_type": "project",
      "identifier": "SIVE",
      "display_name": "Sivers Semiconductors",
      "company_name": "Sivers Semiconductors AB",
      "title": "...",
      "body": "...",
      "source": "Refinitiv Workspace",
      "published_at": "2026-06-15T10:30:00+08:00",
      "story_id": "..."
    }
  ],
  "financial_reports": [
    {
      "entity_type": "match",
      "identifier": "688498",
      "company_name": "源杰科技",
      "report_date": "2026-03-31",
      "statement_type": "Income Statement",
      "financials": [
        {"item_name": "Revenue", "item_value": 123456789.0},
        {"item_name": "Net Income", "item_value": 12345678.0}
      ]
    }
  ]
}
```

**实现决策**

- 入口只负责“校验 + 正规化 + 入库”，不负责页面拼装。
- 新闻入库优先复用现有 `news` 存储 schema，避免新增表。
- 财务入库直接复用 `company_financials_insert()`。
- 若后续要接 SDK 自动拉取，可在这个模块内部追加 provider，不影响页面和服务层。

### 3. 扩展 catalog 数据结构与详情页链接

**Modify:** `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

**需要新增的字段**

- 项目股票 `_stock(...)`
  - `analysis_detail_url`
  - `analysis_detail_label`
  - `financial_summary_short`
  - `latest_news_preview`
  - `analysis_source_label`
- A 股映射 `_match(...)`
  - `analysis_detail_url`
  - `analysis_detail_label`
  - `financial_summary_short`
  - `latest_news_preview`
  - `analysis_source_label`

**实现决策**

- catalog 默认只提供占位字段，不在 `get_a_share_match_catalog()` 阶段直接查询 Workspace/本地数据库。
- 真正数据由批量摘要 API 动态补齐，避免页面首屏构建阶段过慢。
- `analysis_detail_url` 在 catalog 构建时即可生成，确保按钮首屏可点击。

### 4. 新增卡片摘要 API 与详情页路由

**Modify:** `web/chanlun_chart/cl_app/__init__.py`

**新增 API**

- `POST /a_share_matches/stock_analysis_summaries`
  - 入参：卡片列表，每项带 `entity_type`、`identifier`、`display_name`、`company_name`、`exchange`、`market`。
  - 出参：批量摘要结果。

**新增详情页路由**

- `GET /a_share_matches/stock-analysis/<entity_type>/<identifier>`

**可选新增 JSON 数据路由**

- `GET /a_share_matches/stock-analysis/<entity_type>/<identifier>/data`

**实现决策**

- `/a_share_matches` 首屏仅调用批量摘要 API。
- 统一详情页服务端渲染时调用 `build_stock_analysis_detail_payload(...)`。
- 保留现有 `/a_share_matches/tweets/<symbol>` 路由，不删除、不重定向。
- 主页面 CTA 改为“查看个股分析”，旧的“查看推荐脉络”不再占主卡主按钮位；若仍需保留，可作为新详情页内的次级链接展示。

### 5. 改造主页面模板与前端加载逻辑

**Modify:** `web/chanlun_chart/cl_app/templates/a_share_matches.html`

**项目股票卡改动**

- 在 `Serenity 推荐理由` 区块下新增：
  - `财务分析` 摘要区。
  - `最新新闻` 列表区。
  - `查看个股分析` 按钮。

**A 股映射卡改动**

- 在现有 `match-field-grid` 下新增：
  - `财务分析` 摘要区。
  - `最新新闻` 列表区。
  - `查看个股分析` 按钮。

**前端逻辑**

- 参考现有价格和 tweet 摘要加载方式，新增一个批量加载函数：
  - 收集项目股票卡和 A 股映射卡的分析查询对象。
  - 调用 `/a_share_matches/stock_analysis_summaries`。
  - 将结果回填到对应卡片 DOM。
- 增加三种前端状态：
  - 加载中 skeleton。
  - 空态提示。
  - 回退来源标记。

**实现决策**

- 卡片摘要区域默认占位，不阻塞页面其他内容显示。
- 新闻标题超长时截断为单行或双行，避免卡片高度失控。
- 两类卡片统一按钮文案，降低认知成本。

### 6. 新增统一个股分析详情页模板

**Create:** `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`

**页面内容**

- 头部：
  - 股票名称 / 代码
  - 类型标签（项目股票 / A 股映射）
  - 数据来源标签
  - 缠论图入口
- 财务分析区：
  - 规则化摘要
  - AI 财务解读
  - 关键报告期 / 关键指标摘要
- 最新新闻区：
  - 最近 10 条新闻
  - 来源 / 发布时间
- 附加入口：
  - 若是项目股票且有 `tweet_detail_url`，提供“查看推荐脉络”次级入口。

**实现决策**

- 详情页以统一模板承载，不复用 [a_share_match_tweets.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_match_tweets.html)，避免继续把推文语义和个股综合分析耦合。
- 详情页内明确展示“Workspace / 本地回退”来源，便于诊断同步状态。

### 7. 测试补齐

**Create:** `test/test_a_share_stock_analysis.py`

**Modify:** `test/test_a_share_matches_catalog.py`

**新增测试点**

- `build_stock_analysis_detail_url()`：
  - `project` / `match` 两类 URL 生成正确。
- `build_stock_analysis_summaries()`：
  - Workspace 命中时优先返回 Workspace 数据。
  - Workspace 数据不足时回退本地新闻/财务查询。
  - 卡片新闻只返回 3 条。
  - 卡片财务摘要为规则化文本，不触发 AI。
- `build_stock_analysis_detail_payload()`：
  - 返回完整 detail payload。
  - AI 成功时包含 `financial_ai_analysis`。
  - AI 失败时返回可展示的 fallback 文案。
- `a_share_matches.html` 模板：
  - 同时渲染“财务分析”“最新新闻”“查看个股分析”。
  - A 股映射卡也存在详情入口占位。
- `a_share_match_stock_analysis.html` 模板：
  - 渲染基础信息、财务区、新闻区、数据来源标记。

**不做的测试**

- 不在本次为真实 Workspace SDK 调用写集成测试。
- 不在测试中依赖真实数据库内容，统一使用 monkeypatch / fake records。

## Assumptions & Decisions

- 这次范围只覆盖：
  - `/a_share_matches` 页面中的项目股票卡。
  - `/a_share_matches` 页面中的 A 股映射卡。
- 不覆盖：
  - 主题扩展股票卡。
  - 现有 tweet 详情页的重构。
- Workspace 是一级来源，但本次不做桌面 UI 自动化。
- “先落本地再读取”被定义为：
  - 先通过同步入口将 Workspace 数据写入本地。
  - 页面和详情页只读取本地数据。
- 回退策略：
  - 财务：`company_financials` 本地数据继续可用。
  - 新闻：`news_search()` + `search_news_by_stock()` 作为 fallback。
- 财务分析策略：
  - 卡片：规则摘要。
  - 详情：规则摘要 + AI 解读。
- 主页面主 CTA 统一切换为“查看个股分析”。
- 现有“查看推荐脉络”不删除，迁移到新详情页中作为项目股票的次级入口。

## Verification Steps

### 自动化验证

- 运行：

```bash
pytest test/test_a_share_matches_catalog.py test/test_a_share_stock_analysis.py -q
```

- 补充运行：

```bash
pytest test/test_a_share_matches_tweets.py test/test_a_share_matches_quotes.py -q
```

### 手工验证

- 先调用 Workspace 同步入口写入一组项目股票和一组 A 股映射股票的数据。
- 打开 `/a_share_matches`：
  - 项目股票卡出现“财务分析”“最新新闻”“查看个股分析”。
  - A 股映射卡出现同样的新增区域和详情入口。
- 点击项目股票和 A 股映射卡详情入口：
  - 都进入统一详情页。
  - 详情页展示规则摘要、AI 解读、新闻列表、来源标签。
- 人工模拟 Workspace 数据缺失：
  - 确认卡片和详情页仍能用本地数据回退显示。
  - 来源标签明确标记为回退。

### 交付检查

- 不影响现有：
  - `查看缠论图`
  - 价格异步加载
  - tweets 详情页路由
- 新增模板与服务模块均有对应测试覆盖。
