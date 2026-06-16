## Summary
- 目标：让 `a_share_matches` 顶部的每个“主题加权指数”支持查看多日历史价格图。
- 交互：点击顶部主题指数卡后，打开弹窗查看历史走势。
- 图表方案：不直接复用现有股票缠论页的数据入口，而是沿用当前弹窗交互样式，在弹窗内渲染“主题指数专用历史图”。
- 历史范围：优先支持多日历史，默认展示近 `20` 个交易日，并预留切换 `5日 / 20日 / 60日` 的能力。

## Current State Analysis
- 当前主题指数只存在于 `a_share_matches` 首页顶部，是基于 A 股实时涨跌幅即时合成的页面内指标，没有持久化历史序列。
  - 指数成分和权重生成位于 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 关键函数：
    - `_theme_related_bucket_weight(...)`
    - `_build_theme_a_share_index(...)`
    - `_theme(...)`
- 当前页面顶部指数卡只渲染当前值和涨跌幅，不支持点击查看历史图。
  - 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 当前仅有：
    - `data-theme-index-card`
    - `data-theme-index-codes`
    - `data-theme-index-weights`
    - `data-theme-index-base`
  - 当前指数刷新逻辑是 `updateThemeIndexCards(tickMap)`，仅使用 `/ticks` 返回的实时快照更新卡片。
- 现有“缠论图”弹窗可用于股票/标的图表，但底层依赖真实 `market + code`，不支持主题指数这种合成序列。
  - 页面弹窗位于：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 行情接口位于：`web/chanlun_chart/cl_app/__init__.py`
    - `/ticks`
    - `/a_share_matches/project_ticks`
  - 当前 chart URL 生成方式依赖 `build_chart_url("a", code)` 或项目股的真实市场代码，不适用于主题指数。
- 已有页面测试覆盖了：
  - 主题指数卡存在
  - 顶部结构渲染
  - 现有行情刷新 hooks
  - 但尚未覆盖“历史图弹窗”和“主题指数历史数据接口”。

## Proposed Changes
### 1. 在 catalog 中补齐主题指数的稳定标识与展示元数据
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 为每个 `theme["a_share_index"]` 增加稳定字段：
    - `slug`：主题指数唯一标识，建议复用主题 `slug`
    - `chart_title`
    - `default_lookback_days`
  - 保持现有 `codes_csv / weights_csv / base_value` 不变，避免破坏当前顶部卡片刷新逻辑。
- 原因：
  - 前端点击卡片和后端历史接口都需要稳定、可序列化的主题指数 ID。

### 2. 新增主题指数历史数据构建函数
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 新增内容：
  - 一个只读的辅助函数，用于按 `theme_slug` 返回主题指数定义：
    - 成分股列表
    - 权重
    - 基点
    - 标题
  - 一个历史序列构建函数，职责是：
    - 拉取主题成分股的多日 K 线
    - 以统一交易日对齐
    - 计算每只成分股相对起点的收益率
    - 按权重合成主题指数的历史点位
    - 输出前端可直接绘图的 OHLC/close 序列
- 计算规则：
  - 以 `base_value = 1000` 作为指数起点
  - 以每只成分股历史收盘价相对区间首日收盘价的收益率作为贡献
  - 主题指数当日值 = `1000 * (1 + sum(weighted_returns))`
  - 若个别成分股缺少部分历史数据：
    - 允许跳过缺失标的
    - 返回实际参与样本数
    - 在元信息中标记 `coverage`
- 原因：
  - 当前只有实时涨跌幅快照，不足以生成多日历史图。

### 3. 新增主题指数历史接口
- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 新增路由建议：
  - `POST /a_share_matches/theme_index_history`
- 输入：
  - `theme_slug`
  - `lookback_days`
- 输出：
  - `theme_slug`
  - `title`
  - `base_value`
  - `coverage`
  - `series`
    - 每个点包含：`date`, `open`, `high`, `low`, `close`
  - `constituents`
    - 成分、权重、实际参与情况
- 实现约束：
  - 仅读取行情数据，不落库、不改现有交易逻辑
  - 优先复用仓内已有的 A 股 K 线获取能力
  - 若历史数据不足，返回空序列和可展示错误信息

### 4. 在首页顶部指数卡接入“点击看历史图”
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 为顶部指数卡补充数据属性：
    - `data-theme-index-slug`
    - `data-theme-index-title`
    - `data-theme-index-lookback`
  - 给指数卡增加点击态和可访问性属性：
    - `role="button"`
    - `tabindex="0"`
  - 在现有弹窗体系旁新增“主题指数历史图弹窗”，或者复用现有弹窗容器并区分模式：
    - 股票缠论图模式
    - 主题指数历史图模式
  - 增加前端逻辑：
    - 点击指数卡 -> 请求 `/a_share_matches/theme_index_history`
    - 渲染历史图
    - 支持切换 `5日 / 20日 / 60日`
    - 异常时展示“历史数据不足/加载失败”
- 原因：
  - 用户已确认希望从顶部卡片点击进入弹窗查看历史图。

### 5. 图表展示采用自绘，不强接缠论页
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 实现方式：
  - 复用当前弹窗交互风格和遮罩层体验
  - 在弹窗主体中增加一个主题指数专用图表容器
  - 前端使用轻量级 Canvas/SVG 方案绘制：
    - 默认先画 close 折线
    - 若现有样式允许，可进一步升级为简化 K 线
- 决策原因：
  - 现有缠论图依赖真实 `market + code`
  - 主题指数属于合成序列，不适合直接伪装成单一股票标的
  - 自绘方案可以最小侵入完成用户目标，并保留后续再接入缠论引擎的可能

### 6. 补充测试
- 文件：`test/test_a_share_matches_catalog.py`
- 新增测试：
  - `catalog` 中每个主题指数都包含：
    - `slug`
    - `chart_title`
    - `default_lookback_days`
  - 首页模板渲染出：
    - 主题指数卡的点击属性
    - 历史图弹窗容器
    - 历史图请求逻辑
    - lookback 切换按钮
- 文件：可新增 `test/test_a_share_matches_theme_index.py`
- 新增测试：
  - 历史序列构建函数在给定模拟 K 线时能正确输出指数序列
  - 缺失单个成分股历史时，仍能输出部分覆盖结果
  - 历史接口返回结构完整，空数据时错误信息可用

## Assumptions & Decisions
- 已确认决策：
  - 历史图类型：多日历史
  - 入口位置：顶部指数卡点击弹窗
  - 图表方案：同现有弹窗体验，但图表为主题指数专用自绘，不强接现有缠论引擎
- 本计划默认：
  - 历史数据来源为 A 股成分股日线或近似日线数据
  - 指数历史只覆盖 A 股成分，不包含项目股海外标的
  - 第一版以“可看、可比、稳定”为优先，不做复杂技术指标
- 不在本次范围：
  - 将主题指数纳入真实交易标的体系
  - 在现有缠论引擎中直接把主题指数当作真实 `market/code`
  - 持久化保存主题指数历史到数据库

## Verification Steps
1. 运行模板与 catalog 相关测试：
   - `python -m pytest test/test_a_share_matches_catalog.py -q`
2. 运行主题指数历史单测：
   - `python -m pytest test/test_a_share_matches_theme_index.py -q`
3. 手工验证首页：
   - 打开 `a_share_matches`
   - 点击任意顶部主题指数卡
   - 弹出历史图弹窗
   - 默认展示近 `20` 日历史
   - 切换 `5日 / 60日` 后图形更新
4. 异常验证：
   - 模拟历史数据不足时，弹窗显示可读提示，不出现空白或脚本报错
5. 回归验证：
   - 主题导航
   - 股票行情轮询
   - 个股分析详情入口
   - 现有股票缠论图弹窗
