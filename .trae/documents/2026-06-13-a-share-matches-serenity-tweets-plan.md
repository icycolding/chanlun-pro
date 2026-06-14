# A-Share Matches Serenity Tweets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `a_share_matches.html` 中的项目股票建立 Serenity `aleabitoreddit_tweets.json` 相关 tweet 聚合能力，并在股票卡片上提供按钮跳转到独立详情页查看全部相关 tweets。

**Architecture:** 后端新增一个专门的 tweet 检索/归并模块，启动时按 `ticker + 公司名` 规则从 `serenity-aleabitoreddit-main/data/aleabitoreddit_tweets.json` 建立可复用索引；`a_share_matches` 页面在现有异步行情链路之外，再请求“股票相关 tweets 摘要”，只在卡片上显示计数与入口按钮；点击后跳转到新的股票 tweets 详情页，由后端返回该股票的全部相关 tweets 与元信息。这样可以把检索逻辑集中在 Python 侧，避免前端直接处理 5k+ tweet 原始档案。

**Tech Stack:** Flask、Jinja 模板、原生 JavaScript、现有 `cl_app` 路由模式、`aleabitoreddit_tweets.json` 本地 JSON 数据源、`pytest`

---

## Summary

- 数据源来自 [aleabitoreddit_tweets.json](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/data/aleabitoreddit_tweets.json)，每条记录包含 `text`、`quotedTweet`、`createdAtLocal`、`metrics`、`urls`、`media` 等字段，可满足“提及整理 + 详情展示”需求。
- 目标页面是 [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html)，当前已有项目股票卡片和异步加载逻辑，但没有任何与 tweets 相关的后端接口或前端容器。
- 用户已确认两项关键产品决策：
  - 匹配规则：`Ticker + 公司名`
  - 展示方式：股票卡片按钮跳转到“新详情页”

## Current State Analysis

### 已存在文件与职责

- [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html)
  - 已包含 `.stock-card` 项目股票卡片结构
  - 已在前端做项目股票行情 `/a_share_matches/project_ticks` 请求
  - 当前卡片数据可读取 `stock-symbol`、公司全称、交易所、市场
- [__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py)
  - 已注册 `/a_share_matches`
  - 已注册 `/a_share_matches/project_ticks`
  - 适合继续承载新的页面路由和 JSON 接口
- [test_a_share_matches_quotes.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_quotes.py)
  - 已建立 `a_share_matches` 相关 helper 测试习惯
  - 适合作为新增 tweet 匹配逻辑测试的邻近用例
- [ticker_stats.txt](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/data/ticker_stats.txt)
  - 能用于快速验证 ticker 是否频繁出现，如 `SIVE`、`LITE`、`AAOI`、`AXTI`、`TSM` 等

### 数据形态结论

- tweet 原始文本在 `text` 字段，引用推文正文在 `quotedTweet.text`
- 数据源中 ticker 呈现形式不完全统一，已知至少包含：
  - `$SIVE`、`SIVE`
  - `$IQE.L`
  - `$XFAB`
  - 可能存在仅公司名提及
- 因为用户选择 `Ticker + 公司名`，所以不能只依赖 `$TICKER` 精确匹配；但为了避免误匹配，仍应采用分层匹配策略

## Assumptions & Decisions

- **匹配决策**
  - 一级匹配：ticker 及其已知别名，按大小写不敏感匹配
  - 二级匹配：公司全称/规范简称，按大小写不敏感匹配
  - 引用推文 `quotedTweet.text` 也纳入检索范围
  - 同一条 tweet 若同时命中 ticker 和公司名，只计一次
- **别名策略**
  - 不做通用模糊 NLP 识别，先采用“明确规则 + 少量人工别名”的可控方案
  - 已知需要支持的例子：
    - `SIVE` 同时兼容 `SIVEF`
    - `IQE` 兼容 `IQE.L`
    - 如后续页面股票存在类似 `TSM/TSMC`、`SOI/SOITEC`，在 helper 中显式维护
- **页面策略**
  - 卡片上新增“相关 Tweets”按钮和提及数摘要
  - 不在主页直接展开全部 tweets，避免页面过长
  - 跳转到新详情页后展示该股票的完整相关 tweets 列表
- **详情页策略**
  - 详情页路径采用 `/a_share_matches/tweets/<symbol>`
  - 页面展示：股票基础信息、总提及数、匹配依据摘要、tweets 列表
  - 每条 tweet 展示：时间、正文、引用正文、互动数据、原始链接
- **性能策略**
  - 不在前端加载原始 JSON
  - 后端首次使用时读取本地 JSON，并构建内存索引/缓存
  - 卡片摘要接口只返回轻量统计，不返回全部 tweet 正文
- **测试策略**
  - 重点测 helper：ticker 匹配、公司名匹配、quoted tweet 匹配、去重、别名匹配
  - 路由测试只做轻量功能校验，不做真实浏览器自动化

## Proposed Changes

### 1. 新增 tweet 检索 helper

**Files:**
- Create: `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- Test: `test/test_a_share_matches_tweets.py`

**Why**

- 将 tweets 数据加载、标准化、匹配、去重、摘要封装集中在一个独立模块，避免把复杂字符串匹配逻辑塞进 [__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py)

**How**

- 在新文件中实现以下职责：
  - `load_serenity_tweets()`：读取 `serenity-aleabitoreddit-main/data/aleabitoreddit_tweets.json`
  - `build_project_tweet_query(symbol, company_name, exchange, market)`：为股票生成匹配词集合
  - `match_tweet_to_project_stock(tweet, query)`：判断单条 tweet 是否命中
  - `find_related_tweets_for_stock(symbol, company_name, exchange, market)`：返回去重后的完整 tweet 列表
  - `build_tweet_summary_for_stock(...)`：返回卡片摘要，例如 `mention_count`、`latest_mention_at`
- 规范化规则至少包含：
  - ticker 大写化
  - ticker 别名表
  - 公司名大小写无关匹配
  - `text` 与 `quotedTweet.text` 双字段匹配
  - 同 id 去重
- 详情页使用的 tweet item 结构固定为：
  - `id`
  - `text`
  - `quoted_text`
  - `created_at_local`
  - `url`
  - `likes`
  - `retweets`
  - `replies`
  - `quotes`
  - `views`
  - `match_reasons`

### 2. 扩展后端路由

**Files:**
- Modify: `web/chanlun_chart/cl_app/__init__.py`

**Why**

- 需要为首页卡片提供 tweet 摘要接口，并新增详情页路由

**How**

- 在 `a_share_matches` 路由附近新增：
  - `POST /a_share_matches/tweet_summaries`
    - 输入：项目股票列表，字段沿用前端卡片已有数据 `symbol / company_name / exchange / market`
    - 输出：按 `symbol` 返回 `mention_count`、`latest_mention_at`、`detail_url`
  - `GET /a_share_matches/tweets/<symbol>`
    - 输入：symbol 以及必要的 query 参数，如 `company_name / exchange / market`
    - 输出：渲染新的详情页模板
- 如果需要避免 query 参数过长，可在摘要接口中直接返回后端生成的详情链接
- 后端详情页上下文至少包含：
  - `symbol`
  - `company_name`
  - `exchange`
  - `market`
  - `mention_count`
  - `latest_mention_at`
  - `tweets`

### 3. 扩展首页卡片 UI

**Files:**
- Modify: `web/chanlun_chart/cl_app/templates/a_share_matches.html`

**Why**

- 需要在每个项目股票卡片上显示 tweet 摘要，并提供跳转入口

**How**

- 在现有项目股票行情块附近新增一个 “Serenity Tweets” 区块
- 区块内容包括：
  - 提及数量，例如 `Serenity 提及 573 次`
  - 最近提及时间
  - 一个按钮：`查看相关 Tweets`
- 前端新增 `loadProjectTweetSummaries()`，在 `DOMContentLoaded` 时与行情请求并行加载
- 前端请求 `/a_share_matches/tweet_summaries`，只更新卡片摘要，不拉全量 tweet
- 当某只股票没有匹配 tweet 时，展示明确空状态，如 `未检索到相关 Tweets`

### 4. 新增 tweets 详情页模板

**Files:**
- Create: `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`

**Why**

- 用户明确要求“点击按钮后进入新详情页查看全部相关 tweets”

**How**

- 页面结构：
  - 顶部返回入口，回到 `/a_share_matches`
  - 股票基本信息卡片
  - 提及统计摘要
  - tweets 列表
- 每条 tweet 卡片展示：
  - 时间
  - 正文
  - 引用正文（如存在）
  - 点赞/转推/回复/引用/浏览数
  - “打开原帖”按钮
  - 匹配依据标签，如 `Ticker`、`公司名`、`Quoted Tweet`
- 如无匹配结果，展示空状态页而非报错

### 5. 增加回归测试

**Files:**
- Create: `test/test_a_share_matches_tweets.py`

**Why**

- tweet 匹配逻辑最容易因字符串边界、别名和引用正文出错，必须有单测兜底

**How**

- 覆盖以下场景：
  - 通过 ticker 命中，如 `SIVE`
  - 通过别名命中，如 `SIVEF` 归并到 `SIVE`
  - 通过公司名命中，如 `Sivers Semiconductors AB`
  - 通过 `quotedTweet.text` 命中
  - 单条 tweet 多重命中仍只保留一次
  - 无关 ticker/company 不应误命中
  - 详情页结构字段完整

## Implementation Steps

### Task 1: 建立 tweets helper 与测试骨架

**Files:**
- Create: `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- Create: `test/test_a_share_matches_tweets.py`

- [ ] 写 helper 单元测试，先覆盖 ticker、公司名、quoted tweet、别名、去重
- [ ] 实现 tweets JSON 加载与缓存
- [ ] 实现 query 生成与 tweet 匹配函数
- [ ] 跑 `pytest /Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_tweets.py -q`

### Task 2: 增加摘要接口与详情页路由

**Files:**
- Modify: `web/chanlun_chart/cl_app/__init__.py`
- Modify: `web/chanlun_chart/cl_app/a_share_matches_tweets.py`

- [ ] 新增 `/a_share_matches/tweet_summaries`
- [ ] 新增 `/a_share_matches/tweets/<symbol>`
- [ ] 将详情页上下文与摘要返回结构定型
- [ ] 补充或更新路由层测试/最小调用验证

### Task 3: 首页卡片接入 tweet 摘要

**Files:**
- Modify: `web/chanlun_chart/cl_app/templates/a_share_matches.html`

- [ ] 在股票卡片新增 tweets 摘要区和按钮
- [ ] 新增前端异步加载函数并与现有行情加载并行执行
- [ ] 处理空状态、加载中、接口失败提示

### Task 4: 实现 tweets 详情页

**Files:**
- Create: `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`

- [ ] 编写详情页模板
- [ ] 展示股票基本信息、总提及数、最近提及时间、tweet 列表
- [ ] 为每条 tweet 增加原帖跳转与匹配标签

### Task 5: 回归验证

**Files:**
- Modify: `test/test_a_share_matches_tweets.py`
- Verify: `web/chanlun_chart/cl_app/templates/a_share_matches.html`
- Verify: `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`

- [ ] 运行 `pytest /Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_tweets.py -q`
- [ ] 如有必要，补跑与 `a_share_matches` 相关的已有测试
- [ ] 对改动文件执行诊断检查
- [ ] 手工验证路径：
  - 打开 `/a_share_matches`
  - 确认卡片出现 tweets 提及数与按钮
  - 点击 `SIVE`、`LITE`、`AAOI` 等已知高频标的按钮
  - 进入详情页后看到完整 tweet 列表与原帖链接

## Verification Steps

- 数据层验证
  - `SIVE` 应命中大量 tweets，并兼容 `SIVEF`
  - `IQE` 应兼容 `IQE.L`
  - `XFAB`、`LPK` 等页面内股票若在 tweet 文本中出现，应能被检出
- 接口层验证
  - `POST /a_share_matches/tweet_summaries` 对页面股票返回稳定结构
  - `GET /a_share_matches/tweets/<symbol>` 能渲染详情页且在无结果时优雅降级
- 页面层验证
  - 首页卡片不会因 tweets 接口失败而影响现有行情展示
  - “查看相关 Tweets” 按钮点击后进入正确股票详情页
  - 详情页中的 tweet 时间、正文、互动数据和原帖链接可读

## Risks

- 公司名匹配存在误匹配风险，尤其是短名称或通用词
  - 应优先使用 ticker 命中；公司名命中要加词边界/显式别名限制
- tweet 数据量继续增长后，逐卡实时全量扫描可能变慢
  - 首版采用内存缓存；必要时再引入预索引
- 某些股票存在多市场 ticker
  - 首版通过人工 alias 表处理页面已知股票，不做无限扩展

## Out Of Scope

- 不做 tweet 情绪分析
- 不做全文搜索页
- 不做用户自定义筛选器
- 不把 tweets 直接嵌入首页完整展开

## Execution Handoff

计划已保存到 `.trae/documents/2026-06-13-a-share-matches-serenity-tweets-plan.md`。

执行方式建议：

1. `Inline Execution`
   - 直接在当前会话里按计划实现，适合这个单页面 + 单数据源改动
2. `Subagent-Driven`
   - 将 helper、路由、模板拆分子任务执行，适合你想更强隔离审阅
