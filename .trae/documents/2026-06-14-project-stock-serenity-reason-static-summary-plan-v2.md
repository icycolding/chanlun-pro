# 项目股票 Serenity 推荐理由与 Tweets 时间线静态化计划

## Summary

- 目标：在 `a_share_matches` 页面中，为每个项目股票卡片补充“为什么 Serenity 推荐这只股票”的静态总结；在 tweets 详情页中补充“观点总览 + 推荐理由 + 按阶段时间线总结 + 原始 tweets 证据”。
- 约束：不引入 AI 运行时生成；全部采用静态结构化文件；保留现有行情、tweets 匹配、中英双语展示、数据版本轮询刷新能力。
- 成功标准：
  - 主页面每个项目股票卡片都能看到 `Serenity 推荐理由` 区块。
  - 卡片内可以跳转到该股票的 tweets 详情页。
  - 详情页顶部能展示 `为什么 Serenity 看它`、`观点总览`、`时间线`。
  - 详情页下方继续保留原始 tweets 列表，且继续支持中英文展示。
  - 新增/更新测试覆盖目录结构、payload 字段和模板渲染。

## Current State Analysis

### 已确认的现状

- `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 已存在 `_PROJECT_STOCK_REASON_DATA`，并且 `_stock()` 已注入：
    - `serenity_reason_summary`
    - `serenity_reason_highlights`
    - `tweet_detail_label`
  - 当前目录数据已覆盖全部主题与项目股票结构，适合作为主页面卡片的数据源。

- `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
  - 已存在静态 notes 数据结构，字段为：
    - `overview_title`
    - `overview_summary`
    - `why_serenity_likes_it`
    - `timeline_sections`
  - `get_project_tweet_note(symbol)` 已提供 fallback，适合静态化详情页内容。

- `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
  - `build_tweet_detail_payload()` 已把静态 note 数据并入详情 payload。
  - 现有 tweets 匹配、去重、双语字段、`data_version` 刷新机制已经具备。

- `web/chanlun_chart/cl_app/__init__.py`
  - 已引入 `build_tweet_detail_url` / `build_tweet_detail_payload`。
  - `/a_share_matches` 路由已为项目股票注入 `tweet_detail_url`。
  - 详情页模板渲染入口与 `/a_share_matches/tweets/<symbol>/data` JSON 接口已存在。

- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 已存在卡片级 `Serenity 推荐理由` 区块。
  - 已存在“查看推荐脉络”按钮位。
  - 页面仍保留项目股票行情、A 股映射行情、tweet summary 和左侧主题导航。

- `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`
  - 已存在 `Serenity 推荐理由`、`观点总览`、`时间线` 三个区块。
  - 原始 tweets 列表、中英双语、详情页自动刷新 JS 都还在。

- `test/test_a_share_matches_catalog.py`
  - 已开始断言 `serenity_reason_summary` / `tweet_detail_label` 及模板中的新文案。

- `test/test_a_share_matches_tweets.py`
  - 已开始断言：
    - static note 返回值
    - detail payload 的新字段
    - 详情页模板的总览与时间线渲染

### 当前缺口

- 本轮功能看起来已经进入“晚期实现态”，但尚未完成最终回归验证。
- 现状最关键风险不是需求不清，而是：
  - 静态数据是否对全部项目股票覆盖完整；
  - 模板与 payload 字段是否完全对齐；
  - 新测试是否全部通过；
  - 新增模板/数据字段是否引入诊断问题。

## Assumptions & Decisions

- 使用静态数据，不接入新的 AI 总结流程。
- 推荐理由分两层展示：
  - 主页面卡片：短摘要 + highlights + 跳转按钮。
  - 详情页：更完整的“为什么看它 / 观点总览 / 分阶段时间线”。
- tweets 详情页的“时间线”不是逐条自动抽取 tweet 时间轴，而是基于现有主题分析整理成静态阶段总结；原始 tweet 证据继续完整保留在下方。
- 若某股票暂时没有静态 note，则：
  - 主页面仍展示 fallback 的 `research_summary`。
  - 详情页展示默认空态文案，而不阻断原始 tweets 列表。
- 保持现有自动刷新机制，仅在 `data_version` 变化时刷新详情/摘要内容，不额外引入新的轮询源。

## Proposed Changes

### 1. 完成并校准项目股票静态推荐理由

- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 变更内容：
  - 检查 `_PROJECT_STOCK_REASON_DATA` 是否覆盖目录中的全部项目股票 symbol。
  - 统一每个 symbol 的静态字段格式：
    - `serenity_reason_summary`
    - `serenity_reason_highlights`
    - `tweet_detail_label`
  - 确保 `_stock()` fallback 逻辑稳定：
    - `serenity_reason_summary` 回退到 `research_summary`
    - `serenity_reason_highlights` 回退空数组
    - `tweet_detail_label` 回退 `"查看推荐脉络"`
- 原因：
  - 主页面卡片的数据必须稳定、统一，避免部分主题出现空字段或 UI 不一致。

### 2. 完成并校准 tweets 静态总结/时间线数据

- 文件：`web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
- 变更内容：
  - 检查 `_NOTES` 是否覆盖全部项目股票 symbol。
  - 统一每个 note 的字段结构和文案粒度：
    - `overview_title`
    - `overview_summary`
    - `why_serenity_likes_it`
    - `timeline_sections`
  - 统一 `timeline_sections` 子项结构：
    - `title`
    - `summary`
    - `focus_points`
    - `tweet_ids` 可留作静态保留字段，不要求首版在模板渲染。
  - 保持 `get_project_tweet_note()` 的 fallback 输出不变。
- 原因：
  - 详情页是“总结层 + 证据层”结构，静态 note 是总结层唯一数据源，必须对齐所有 symbol。

### 3. 固化详情页 payload 接口契约

- 文件：`web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- 变更内容：
  - 保持 `build_tweet_detail_payload()` 返回以下字段并与模板完全对齐：
    - `symbol`
    - `company_name`
    - `exchange`
    - `market`
    - `display_name`
    - `mention_count`
    - `latest_mention_at`
    - `overview_title`
    - `overview_summary`
    - `why_serenity_likes_it`
    - `timeline_sections`
    - `tweets`
    - `data_version`
  - 若需要，补充对空 note/空 tweets 的稳定处理，确保前端 JS 刷新时不会因字段缺失报错。
- 原因：
  - 当前主模板渲染与前端自动刷新都依赖这个 payload，接口必须稳定。

### 4. 校准主页面卡片展示

- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 变更内容：
  - 保持 `/a_share_matches` 路由在渲染前，为每个项目股票注入 `tweet_detail_url`。
  - 若发现 symbol 为空或特殊值（如 `-`）导致 URL 构造异常，明确保持可渲染但不影响页面其余内容。
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 变更内容：
  - 保持并校准 `Serenity 推荐理由` 区块：
    - 摘要文案
    - highlights 标签
    - 跳转按钮
  - 确保该区块与现有 `Serenity 视角`、行情区块、tweet summary 区块层次不冲突。
  - 确认按钮文案与详情页定位一致，推荐统一使用 `"查看推荐脉络"`。
- 原因：
  - 用户最直接的需求是“在卡片上看到 Serenity 推荐这个股票的理由”。

### 5. 校准 tweets 详情页展示与刷新

- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 变更内容：
  - 确认 `/a_share_matches/tweets/<symbol>` 模板渲染和 `/a_share_matches/tweets/<symbol>/data` JSON 接口都传递新字段。

- 文件：`web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`
- 变更内容：
  - 保持并校准顶部两块总结内容：
    - `为什么 Serenity 看它`
    - `观点总览`
  - 保持并校准 `时间线` 区块：
    - 有数据时展示阶段卡片
    - 无数据时展示默认空态说明
  - 保持原始 tweets 区块在时间线之后展示，继续保留：
    - 原文
    - 中文翻译
    - 引用原文
    - 引用中文翻译
    - 互动指标
    - 原帖链接
  - 校准前端 JS 的 `renderTweetDetailPayload()`，确保自动刷新时同时更新：
    - `mention_count`
    - `latest_mention_at`
    - `why_serenity_likes_it`
    - `overview_title`
    - `overview_summary`
    - `timeline_sections`
    - `tweets`
- 原因：
  - 详情页是本轮功能的核心交付，既要能“看懂观点”，又要能“回看证据”。

### 6. 补齐测试与回归验证

- 文件：`test/test_a_share_matches_catalog.py`
- 验证重点：
  - 目录中每个项目股票都具备新的静态推荐理由字段。
  - 模板渲染中存在：
    - `Serenity 推荐理由`
    - `查看推荐脉络`
    - 主题导航和新结构未被破坏。

- 文件：`test/test_a_share_matches_tweets.py`
- 验证重点：
  - `get_project_tweet_note()` 返回完整静态结构。
  - `build_tweet_detail_payload()` 返回新字段且保留双语 tweet 字段。
  - `a_share_match_tweets.html` 渲染时可见：
    - `Serenity 推荐理由`
    - `为什么 Serenity 看它`
    - `时间线`
  - JSON 文件版本变化仍能触发 `data_version` 更新。

- 执行验证（计划批准后执行）：
  - `pytest test/test_a_share_matches_catalog.py test/test_a_share_matches_tweets.py`
  - 对新改动文件运行诊断检查：
    - `a_share_matches_catalog.py`
    - `a_share_matches_tweet_notes.py`
    - `a_share_matches_tweets.py`
    - `__init__.py`
    - `a_share_matches.html`
    - `a_share_match_tweets.html`
  - 如需页面级确认，再启动本地服务后手动验证：
    - 主页面卡片是否出现推荐理由与按钮
    - 详情页是否出现总览/时间线/原始 tweets
    - 若 `aleabitoreddit_tweets.json` 更新，详情页是否继续按 `data_version` 机制刷新

## Execution Order

1. 先校验 `a_share_matches_catalog.py` 和 `a_share_matches_tweet_notes.py` 的 symbol 覆盖与字段一致性。
2. 再对齐 `a_share_matches_tweets.py` 和 `__init__.py` 的 payload / 路由上下文。
3. 然后校准 `a_share_matches.html` 与 `a_share_match_tweets.html` 的展示和前端刷新逻辑。
4. 最后运行 pytest 与诊断，修正失败项，必要时做一次页面级手动核验。

## Verification Criteria

- 主页面中任一项目股票卡片都能直接读到 Serenity 推荐摘要。
- 卡片按钮能进入对应 symbol 的 tweets 详情页。
- 详情页在顶部可读到：
  - `为什么 Serenity 看它`
  - `观点总览`
  - `时间线`
- 原始 tweets 列表继续可见，并保留中英双语和原帖链接。
- `pytest test/test_a_share_matches_catalog.py test/test_a_share_matches_tweets.py` 通过。
- 诊断不引入新的可见错误；`__init__.py` 中已有的历史提示若仍存在，视为非本次新增问题。
