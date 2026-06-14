# 项目股票 Serenity 推荐理由与 Tweets 时间线静态化计划

## Summary

本次目标是在现有 `a_share_matches` 页面基础上，为“项目股票”补上更明确的 Serenity 推荐理由，并增强 Tweets 详情页的研究价值，但**不引入新的 AI 在线生成能力**。实现方式改为：

- 由当前代码库内的结构化静态数据承载项目股票的 `Serenity 推荐理由`
- 在卡片上显示一段静态摘要，并提供按钮进入详情
- 在 Tweets 详情页中新增“意思汇总”和“按时间线分阶段展示”的静态汇总结构
- 相关内容由我基于当前主题和已命中的 tweets 做静态分析后写入代码文件
- 保留现有 tweets 匹配、双语显示、自动刷新和行情功能

## Current State Analysis

### 当前项目股票卡片

- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 当前每只项目股票已有：
  - `symbol`
  - `display_name`
  - `company_name`
  - `exchange`
  - `market`
  - `theme_chip`
  - `research_summary`
  - `main_matches`
  - `candidate_matches`
- 当前 `research_summary` 更像“研究视角判断”，不是显式的“Serenity 为什么推荐这只股票”
- 当前卡片没有单独的“推荐理由摘要”字段，也没有进入“推荐脉络详情”的专门按钮

### 当前 Tweets 数据与详情页

- 文件：`web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- 当前已有能力：
  - 从 `aleabitoreddit_tweets.json` 中匹配项目股票相关 tweets
  - 生成摘要 `build_tweet_summary_for_stock()`
  - 生成详情 `build_tweet_detail_payload()`
  - 支持 `text_zh` / `quoted_text_zh`
  - 支持基于 tweets 文件修改时间的自动失效缓存
- 但当前详情 payload 只有：
  - `mention_count`
  - `latest_mention_at`
  - `tweets`
  - `data_version`
- 尚未包含：
  - Serenity 推荐理由总结
  - 阶段性观点归纳
  - 时间线分段说明

- 文件：`web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`
- 当前详情页主要是：
  - 顶部摘要信息
  - 原始 tweet 列表
  - 双语正文和引用正文
- 尚未有：
  - 顶部“Serenity 观点总览”
  - 按阶段组织的时间线卡片
  - “为什么推荐 / 观点如何演化 / 催化与风险”这类研究层内容

### 当前接口形态

- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 当前路由：
  - `/a_share_matches`
  - `/a_share_matches/tweet_summaries`
  - `/a_share_matches/tweets/<symbol>`
  - `/a_share_matches/tweets/<symbol>/data`
- 页面已经支持 tweets 更新后自动刷新
- 因为本次明确不加 AI，新能力应尽量落在静态数据层和已有 payload 扩展上，而不是新建 AI 生成接口

## Assumptions & Decisions

### 已确认决策

- 不新增 AI 能力
- 改为由我基于现有主题分析与已命中的 tweets，生成**静态文件/静态结构化数据**
- 项目股票卡片上的推荐理由展示为：`摘要 + 按钮`
- Tweets 详情页展示方式为：`先总览后时间线`
- 汇总粒度为：`按阶段分段`
- tweets 文件更新后，详情页仍应自动反映新的原始 tweets 数据

### 关键设计决定

- “Serenity 推荐理由”不从运行时自动生成，而是新增静态字段写入 `a_share_matches_catalog.py`
- “Tweets 的意思汇总 / 阶段时间线”不依赖 AI，改由我为现有项目股票生成静态 timeline 分析数据，并写入新的静态结构中
- 详情页继续保留原始 tweet 列表，作为研究证据层
- 当原始 tweets 更新后：
  - 原始 tweet 列表继续自动更新
  - 静态总结部分不会自动重写内容，除非后续再次人工更新静态文件
- 页面上需要明确区分：
  - `静态研究总结`
  - `动态原始 tweets`

### 不在本次范围

- 不接入在线 LLM 摘要
- 不改动 tweets 匹配算法
- 不引入数据库或持久化缓存层
- 不新增新的外部依赖或异步任务

## Proposed Changes

### 1. 扩展项目股票静态结构，增加 Serenity 推荐理由

#### 文件

- 修改 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

#### 改动内容

- 为每只项目股票新增用于卡片展示的静态字段，例如：
  - `serenity_reason_summary`
  - `serenity_reason_highlights`
  - `tweet_detail_label`
- 其中：
  - `serenity_reason_summary` 用于卡片上一段 2-4 句的推荐理由摘要
  - `serenity_reason_highlights` 可选，用于后续页面上补 2-3 条关键点
  - `tweet_detail_label` 用于按钮文案，如“查看推荐脉络 / 查看 Tweets 详情”

#### 内容生成原则

- 不是重复 `research_summary`
- 要直接回答“Serenity 为什么会看这只股票”
- 摘要优先聚焦：
  - 它在 Serenity 框架中的链条位置
  - 市场忽视点 / choke point
  - 关键催化或验证方向
  - 为什么不是普通同赛道映射

### 2. 新增静态 Tweets 研究汇总数据层

#### 文件

- 新增 `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`

#### 改动内容

- 为项目股票维护静态研究汇总数据，按 `symbol` 组织
- 每只股票可包含：
  - `overview_title`
  - `overview_summary`
  - `why_serenity_likes_it`
  - `timeline_sections`
- `timeline_sections` 按阶段组织，例如：
  - `最初关注`
  - `观点强化`
  - `催化验证`
  - `风险/分歧变化`
- 每个阶段包含：
  - `title`
  - `summary`
  - `focus_points`
  - 可选 `tweet_ids`

#### 设计目的

- 让详情页不只是原始 tweet dump，而是可读的研究线索页
- 保持与原始 tweets 解耦，便于手工持续优化

### 3. 扩展 Tweets 详情 payload

#### 文件

- 修改 `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- 修改 `web/chanlun_chart/cl_app/__init__.py`

#### 改动内容

- 在 `build_tweet_detail_payload()` 中加入静态研究汇总数据：
  - `serenity_reason_summary`
  - `overview_summary`
  - `timeline_sections`
- 路由 `/a_share_matches/tweets/<symbol>` 和 `/a_share_matches/tweets/<symbol>/data` 都返回这些字段
- 保持现有动态字段不变：
  - `mention_count`
  - `latest_mention_at`
  - `tweets`
  - `data_version`

#### 行为约束

- 静态汇总字段按 symbol 直接查
- 如果某只股票还没有静态汇总：
  - 页面显示空态或占位提示
  - 不影响原始 tweet 列表显示

### 4. 修改主页面卡片展示

#### 文件

- 修改 `web/chanlun_chart/cl_app/templates/a_share_matches.html`

#### 改动内容

- 在每个项目股票卡片中新增 “Serenity 推荐理由” 区块
- 展示内容：
  - 一段静态摘要 `serenity_reason_summary`
  - 一个进入详情页的按钮
- 详情按钮沿用当前 symbol / company / exchange / market / display_name 参数体系，保证跳转与 tweets 匹配上下文一致

#### 目标效果

- 用户在主页面直接看到：
  - Serenity 为什么看这个项目股票
  - 不需要先点进 tweets 才知道推荐逻辑

### 5. 修改 Tweets 详情页为“总览 + 时间线 + 原始 tweets”

#### 文件

- 修改 `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`

#### 改动内容

- 在顶部 hero 或 summary 下新增：
  - `Serenity 推荐理由`
  - `观点总览`
- 在 tweet 列表前新增 `时间线` 区块：
  - 按阶段显示 `timeline_sections`
  - 每个阶段展示简短说明和关键点
- 原始 tweet 列表继续保留在页面下方，作为证据层

#### 页面顺序

1. 股票信息摘要
2. Serenity 推荐理由
3. 观点总览
4. 时间线阶段卡片
5. 原始 tweets 列表

### 6. 为静态内容和详情 payload 增加测试

#### 文件

- 修改 `test/test_a_share_matches_catalog.py`
- 修改 `test/test_a_share_matches_tweets.py`

#### 测试内容

- catalog 中每只项目股票都有：
  - `serenity_reason_summary`
- tweet notes 静态数据结构完整：
  - 有 `overview_summary`
  - 有 `timeline_sections`
- `build_tweet_detail_payload()` 返回：
  - 静态推荐理由
  - 总览摘要
  - 时间线 sections
  - 原有 tweets 列表
- 模板渲染断言：
  - 主页面出现“Serenity 推荐理由”
  - 详情页出现“观点总览”与“时间线”

## Verification Steps

### 主页面验证

- 打开 `/a_share_matches`
- 检查每个项目股票卡片是否出现：
  - `Serenity 推荐理由` 区块
  - 推荐理由摘要
  - 进入详情按钮

### 详情页验证

- 打开某个项目股票的 tweets 详情页，例如 `SIVE`
- 检查是否出现：
  - 推荐理由摘要
  - 观点总览
  - 时间线阶段卡片
  - 原始 tweets 列表

### 回归验证

- 确认原始 tweets 双语显示仍正常
- 确认 tweets 文件更新后的动态 tweet 列表仍自动刷新
- 确认主页面项目股票行情、A 股行情、tweets 摘要不受影响

### 测试与诊断

- 运行：
  - `test/test_a_share_matches_catalog.py`
  - `test/test_a_share_matches_tweets.py`
  - 必要时附带 `test/test_a_share_matches_quotes.py`
- 对修改过的 Python / 模板文件运行诊断，确保无新错误

## Implementation Order

1. 扩展 `a_share_matches_catalog.py`，补项目股票推荐理由静态字段
2. 新增 `a_share_matches_tweet_notes.py`，整理各项目股票的静态总览与时间线数据
3. 扩展 `a_share_matches_tweets.py` 的 detail payload
4. 修改 `a_share_matches.html`，在卡片上显示推荐理由和详情按钮
5. 修改 `a_share_match_tweets.html`，加入总览与时间线区块
6. 补测试并做回归验证
