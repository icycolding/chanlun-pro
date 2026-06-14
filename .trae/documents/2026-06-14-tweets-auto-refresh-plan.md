# Tweets 更新后网页自动更新计划

## Summary

目标是在 `aleabitoreddit_tweets.json` 文件更新后，让相关网页在不手动刷新整页的情况下自动反映最新 Tweets 数据。

这里的“数据更新”明确包含两类：

- tweet 主体内容变化，例如新增 tweet、删除 tweet、提及数变化、最近提及时间变化
- 翻译字段变化，例如 `text_zh`、`quotedTweet.text_zh` 的新增、补齐或修正

本次范围覆盖两个页面：

- `a_share_matches.html` 中每个股票卡片上的 Serenity Tweets 摘要
- 单股票 Tweets 详情页 `a_share_match_tweets.html`

- 采用方案为前端定时轮询。后端继续使用当前“按文件 `mtime` 自动失效缓存”的能力，并补充轻量版本信息与结构化 JSON 接口，前端按固定间隔请求，只有检测到数据版本变化时才更新页面内容。

本次轮询频率固定为：每小时一次。

由于版本基于整个 `aleabitoreddit_tweets.json` 文件的修改时间，只要翻译字段被写入或更新，前端也会在下一轮轮询中感知并刷新。

## Current State Analysis

### 已确认的现状

- `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
  - `load_serenity_tweets()` 已按 `aleabitoreddit_tweets.json` 的 `st_mtime_ns` 自动失效缓存。
  - 这意味着后端后续请求已经能读取到文件最新内容，不需要重启服务。
- `web/chanlun_chart/cl_app/__init__.py`
  - 已有 `POST /a_share_matches/tweet_summaries`，用于返回股票卡片摘要。
  - 已有 `GET /a_share_matches/tweets/<symbol>`，但这是直接服务端渲染 HTML 页面，不是可供前端局部刷新的 JSON 接口。
- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - `loadProjectTweetSummaries()` 只在 `DOMContentLoaded` 时执行一次。
  - 页面打开后即使 JSON 文件更新，摘要卡片也不会重新请求，因此不会自动更新。
- `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`
  - 当前为纯服务端渲染的详情页，页面内没有任何自动轮询逻辑。
  - 即使数据源更新，已打开的详情页也不会自动刷新。
  - 虽然详情页现在已经支持中英文双语展示，但翻译字段更新后，已打开页面仍然看不到新翻译，必须手动刷新。

### 当前问题的真实断点

- 不是后端缓存问题，后端已能感知文件变更。
- 真正缺口在于前端没有“持续拉取 + 版本比较 + 局部重绘”机制。
- 详情页还缺少可供轮询的 JSON 数据接口。

## Proposed Changes

### 1. `web/chanlun_chart/cl_app/a_share_matches_tweets.py`

新增轻量版本和详情载荷构建能力，作为前端轮询的统一数据基础。

计划修改：

- 新增一个返回 Tweets 数据版本的方法，例如基于：
  - `_TWEETS_JSON_PATH.stat().st_mtime_ns`
  - 或在此基础上封装统一的 `get_tweets_data_version()`
- 新增一个结构化详情数据构建方法，例如：
  - `build_tweet_detail_payload(...)`
- 该 payload 至少包含：
  - `symbol`
  - `mention_count`
  - `latest_mention_at`
  - `tweets`
  - `data_version`

原因：

- 摘要页和详情页都需要一个稳定的“数据版本”来判断是否需要更新 DOM。
- 详情页当前只有 HTML 模板，没有 JSON 形态的数据接口，前端无法轮询后局部刷新。

实现要点：

- 版本值直接绑定文件修改时间，避免额外状态管理。
- 详情 payload 复用现有 `find_related_tweets_for_stock()` 结果，避免重复匹配逻辑。
- payload 必须继续包含双语字段：
  - `text`
  - `text_zh`
  - `quoted_text`
  - `quoted_text_zh`

### 2. `web/chanlun_chart/cl_app/__init__.py`

补充前端轮询所需的 JSON 接口，并让现有摘要接口返回版本字段。

计划修改：

- 扩展 `POST /a_share_matches/tweet_summaries`
  - 在现有 `summaries` 外，增加顶层 `data_version`
- 新增详情 JSON 接口，例如：
  - `GET /a_share_matches/tweets/<symbol>/data`
- 该接口接收与 HTML 页面相同的查询参数：
  - `company_name`
  - `exchange`
  - `market`
  - `display_name`
- 返回结构化 JSON：
  - `symbol`
  - `company_name`
  - `exchange`
  - `market`
  - `display_name`
  - `mention_count`
  - `latest_mention_at`
  - `tweets`
  - `data_version`

原因：

- 摘要页需要知道“现在的数据版本”和“最新摘要内容”。
- 详情页需要独立的数据接口来支持局部刷新，不适合通过重新拉整页 HTML 再解析。
- 翻译字段更新通常不会改变 `mention_count`，因此不能只根据摘要业务字段判断是否刷新，必须依赖统一的文件版本。

实现要点：

- HTML 路由 `GET /a_share_matches/tweets/<symbol>` 保持不变。
- JSON 接口与 HTML 页面共用同一套匹配逻辑，避免两套数据口径不一致。

### 3. `web/chanlun_chart/cl_app/templates/a_share_matches.html`

为股票卡片摘要增加定时轮询与“仅在数据变化时更新”逻辑。

计划修改：

- 为当前的 `loadProjectTweetSummaries()` 增加版本感知：
  - 首次加载时保存最近一次 `data_version`
  - 后续按固定间隔轮询
- 新增轮询调度逻辑：
  - 页面加载后启动 `setInterval`
  - 固定间隔为 `1 小时`
- 只有当新返回的 `data_version` 与当前页面记录不同，才执行摘要 DOM 重绘
- 页面隐藏时可跳过刷新，页面回到可见时立即补一次请求

原因：

- 摘要页数据量较小，轮询成本可控。
- 版本比较可以避免每次轮询都重绘全部卡片，减少闪烁。

实现要点：

- 将 `symbol -> summary` 的映射逻辑保留，继续按卡片更新。
- 无数据、加载失败、空摘要状态保持现有文案风格。
- 若轮询失败，不清空现有 DOM，只保留旧数据并在下一轮继续尝试。
- 摘要页虽然不展示正文翻译，但仍要在版本变化时刷新摘要，因为翻译更新与 tweet 新增可能由同一次 JSON 写入产生。

### 4. `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`

为详情页增加轮询刷新，使打开的页面在 JSON 文件更新后自动看到新 Tweets。

计划修改：

- 在服务端模板中注入当前股票上下文参数：
  - `symbol`
  - `company_name`
  - `exchange`
  - `market`
  - `display_name`
  - 初始 `data_version`
- 页面增加前端脚本：
  - 固定间隔请求 `/a_share_matches/tweets/<symbol>/data`
  - 若 `data_version` 未变化，不更新
  - 若变化，则同步更新：
    - 提及数量
    - 最近提及时间
    - tweet 列表
    - 空态文案
- tweet 卡片的 DOM 重建需要保留现有双语结构：
  - 原文
  - 中文翻译
  - 引用原文
  - 引用中文翻译

原因：

- 详情页当前是一次性 SSR 页面，必须补前端 JSON 刷新链路才能做到“打开后自动更新”。

实现要点：

- 详情页初始首屏仍使用服务端渲染，保证直接打开时可读。
- 自动更新只做增量重绘，不触发整页刷新。
- 渲染函数需统一处理：
  - 有翻译 / 无翻译
  - 有引用 / 无引用
  - 有 tweet / 无 tweet
- 当仅翻译字段变化、tweet 数量不变时，也必须触发详情列表重绘，确保用户看到最新中文翻译。

### 5. `test/test_a_share_matches_tweets.py`

补充后端数据接口与版本信息的单元测试，确保刷新判断可靠。

计划修改：

- 新增版本相关测试，验证：
  - 文件变更后 `data_version` 变化
  - 不变时版本稳定
- 新增详情 payload 测试，验证：
  - `mention_count`
  - `latest_mention_at`
  - `tweets`
  - `data_version`
  - 双语字段仍存在

原因：

- 轮询逻辑是否刷新，直接依赖版本字段是否正确。
- 详情页自动更新依赖 JSON payload 结构稳定。

### 6. 可选验证路径：浏览器联调

如实现阶段需要人工验证，再使用本地页面进行联调：

- 打开 `a_share_matches.html`
- 打开某个股票的 Tweets 详情页
- 修改 `serenity-aleabitoreddit-main/data/aleabitoreddit_tweets.json`
- 等待一个轮询周期，确认两个页面自动刷新

## Assumptions & Decisions

### 已锁定决策

- 刷新范围：摘要页 + 详情页
- 刷新方式：定时轮询
- 不做 SSE / WebSocket
- 不要求“实时到秒级”，优先稳妥、简单、可维护
- 自动更新范围明确包含 tweet 内容与翻译字段更新

### 关键实现决策

- 以后端返回的 `data_version` 作为刷新判断依据，而不是在前端自行推断内容差异。
- 详情页新增 JSON 接口，而不是让前端重复请求 HTML 页面并解析。
- 轮询失败时保留旧内容，不做降级清空。
- 首屏继续 SSR，自动更新只负责首屏之后的数据同步。

### 已锁定轮询策略

- 轮询间隔：1 小时
- 摘要页与详情页统一使用同一频率
- 每轮都先取最新 `data_version`，仅在版本变化时更新 DOM
- 若某轮失败，则保留现有内容，等待下一小时重试

## Verification Steps

### 自动化验证

执行：

```bash
python -m pytest /Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_tweets.py -q
```

检查点：

- 版本字段测试通过
- 详情 payload 测试通过
- 既有 tweets 匹配与双语字段测试不回归

### 诊断检查

对以下文件执行诊断检查：

- `web/chanlun_chart/cl_app/a_share_matches_tweets.py`
- `web/chanlun_chart/cl_app/__init__.py`
- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
- `web/chanlun_chart/cl_app/templates/a_share_match_tweets.html`
- `test/test_a_share_matches_tweets.py`

### 手工验收

验收步骤：

1. 打开 `a_share_matches.html`
2. 观察任一股票卡片当前 Tweets 提及数与最近提及时间
3. 打开同一股票的详情页
4. 修改 `aleabitoreddit_tweets.json` 中该股票相关 tweet，或新增一条命中 tweet
5. 在不手动刷新页面的前提下，等待一个轮询周期
6. 确认：
   - 摘要页提及数 / 最近提及时间自动变化
   - 详情页列表自动变化
   - 双语字段正常展示
   - 只修改 `text_zh` 或 `quotedTweet.text_zh` 时，详情页也会在下一轮自动更新
   - 无闪屏、无整页跳转、无控制台报错

## 执行顺序

建议按以下顺序实现：

1. 在 `a_share_matches_tweets.py` 增加 `data_version` 与详情 payload helper
2. 在 `__init__.py` 扩展摘要接口并新增详情 JSON 接口
3. 先改 `a_share_match_tweets.html` 的详情页轮询逻辑
4. 再改 `a_share_matches.html` 的摘要轮询逻辑
5. 补测试并完成诊断与联调
