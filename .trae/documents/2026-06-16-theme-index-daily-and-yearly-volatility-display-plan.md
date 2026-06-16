## Summary
- 目标：在 `a_share_matches` 的主题指数界面中，为指数值补充“当日 + 当年”的两类指标，并且同时显示：
  - 涨跌幅
  - 波动幅度
- 展示范围已明确：
  - 顶部主题指数卡
  - 主题指数历史弹窗
- 口径已明确：
  - “两者都要”表示同时展示收益类指标与波动类指标
  - 不仅看当日，还要看当年（年初至今 / 年内区间）

## Current State Analysis
- 顶部主题指数卡模板位于 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 当前卡片已有：
    - `theme-index-value`
    - `theme-index-change`
    - `theme-index-meta`
    - `theme-index-definition`
  - 现状是：
    - 只展示指数值与一个实时变化字段
    - 没有独立展示“当日涨跌幅 / 当日振幅 / 当年涨跌幅 / 当年振幅”
- 历史弹窗模板也在 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 当前已有区间统计：
    - `区间涨跌`
    - `最大回撤`
    - `波动区间`
  - 现状是：
    - 这些指标是基于当前已加载区间计算
    - 不是固定的“当日 + 当年”口径
- 主题指数历史与实时快照的核心后端逻辑位于 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 历史序列：
    - `build_theme_index_history_series(...)`
    - `build_theme_index_history(...)`
  - 实时指数：
    - `build_theme_index_live_snapshot(...)`
    - `build_theme_index_live(...)`
  - 参考日状态：
    - `build_theme_index_reference_closes(...)`
    - `_load_theme_index_reference_state(...)`
- 当前后端返回的实时快照核心字段只有：
  - `index_value`
  - `change_pct`
  - `used_constituents`
  - `reference_date`
  - 不包含“当日振幅”或“当年指标”
- 当前历史结果里虽然有完整 `series`，理论上可以从序列中计算：
  - 年初至今涨跌幅
  - 年内最大最小区间振幅
  - 但后端还没有封装这些指标为稳定字段
- 当前测试覆盖：
  - 主题指数历史序列
  - 固定基准日
  - DB 缓存与增量补齐
  - 模板中存在主题指数卡与历史弹窗元素
  - 但没有覆盖“当日/当年指标展示”

## Proposed Changes
### 1. 明确并固化指标口径
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 口径定义：
  - 当日涨跌幅：
    - 继续沿用当前实时指数 `change_pct`
  - 当日振幅：
    - 用实时主题指数当日高低区间计算
    - 建议口径：`(当日 high - 当日 low) / 当日 open * 100`
    - 原因：当前合成后的主题指数快照与历史序列都已有 `open/high/low/close` 语义，易于统一
  - 当年涨跌幅：
    - 以当年首个可用交易日的 `close` 为基准
    - 计算 `latest_close / year_start_close - 1`
  - 当年振幅：
    - 以当前自然年内的历史点为范围
    - 计算 `(year_high - year_low) / year_start_close * 100`
- 原因：
  - 用户要求“涨跌幅 + 振幅都要”，需要避免前端临时拼算法导致口径不一致

### 2. 给主题指数后端增加统一指标摘要
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 新增一个主题指数指标摘要 helper，建议形态：
    - 输入：完整主题指数历史 `series`、实时 `live_index`
    - 输出：
      - `daily_change_pct`
      - `daily_amplitude_pct`
      - `ytd_change_pct`
      - `ytd_amplitude_pct`
      - `year_start_date`
      - `year_high`
      - `year_low`
  - `build_theme_index_history(...)` 返回中附带该摘要
  - `build_theme_index_live(...)` 也返回同口径摘要，供顶部卡片直接使用
- 实现方式：
  - 历史序列已是统一指数值，可直接从 `series` 中筛出“当前年份”的点计算
  - 若当前年内数据不足：
    - 返回空值或 `None`
    - 前端显示 `--`
- 原因：
  - 顶部卡片与历史弹窗都需要相同数据，不应让前端各自推导一份

### 3. 扩展顶部主题指数卡展示
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 在现有指数卡中新增 2 组指标展示：
    - 当日：
      - 涨跌幅
      - 振幅
    - 当年：
      - 涨跌幅
      - 振幅
  - 保持现有：
    - 指数值
    - 基准日 / 基点
  - 调整 `updateThemeIndexCards(...)`，从快照接口读取新摘要字段并渲染
- UI 建议：
  - 采用紧凑的 2x2 指标网格
  - 避免把所有信息挤在 `theme-index-meta` 一行中
  - `theme-index-change` 可保留作为最显眼的“当日涨跌幅”
  - 其余三项放在补充指标区
- 原因：
  - 顶部卡片是用户看“界面指数值”的第一入口，必须直观看到四项指标

### 4. 扩展历史弹窗统计区
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 在弹窗已有统计区中加入固定口径的年度/当日指标
  - 建议保留现有区间指标，同时新增或替换为更明确的字段：
    - 当日涨跌幅
    - 当日振幅
    - 当年涨跌幅
    - 当年振幅
  - 弹窗中仍保留：
    - 区间涨跌
    - 最大回撤
    - 波动区间
  - 但需要在展示上区分：
    - “固定口径指标”
    - “当前视图区间指标”
- 原因：
  - 用户明确要求历史弹窗也要显示
  - 当前弹窗已有统计卡区，是最自然的承载位置

### 5. 处理默认基准日与自定义基准日的联动
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 关联文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 由于当前已支持自定义 `reference_date`
  - 新增的当日/当年指标必须基于“当前生效的参考日口径”对应的指数序列计算
  - 历史弹窗中如果用户改了 `reference_date`：
    - 指数值
    - 当日涨跌幅
    - 当日振幅
    - 当年涨跌幅
    - 当年振幅
    都必须同步变化
  - 顶部卡片则继续基于默认参考日快照，不跟随弹窗临时自定义状态
- 原因：
  - 当前产品行为里，首页卡片与弹窗的自定义状态不是全局共享
  - 计划必须保持这一边界，避免把临时查询状态错误同步到全局首页

### 6. 测试补齐
- 文件：`test/test_a_share_matches_theme_index.py`
- 新增测试：
  - 年内指标从历史序列正确计算
  - 自定义 `reference_date` 时，指标摘要也随之变化
  - 年内数据不足时返回空摘要或 `--` 对应值
  - 当日振幅计算使用合成指数当日 OHLC，而不是误用收盘涨跌
- 文件：`test/test_a_share_matches_catalog.py`
- 新增模板断言：
  - 顶部指数卡包含“当日涨跌幅 / 当日振幅 / 当年涨跌幅 / 当年振幅”相关文案或容器
  - 历史弹窗包含对应统计项
- 原因：
  - 这是展示型需求，既要测后端数值口径，也要测模板挂载点

## Assumptions & Decisions
- 已确认决策：
  - “波动幅度”不是只看涨跌幅，要和涨跌幅一起显示
  - 展示位置是“顶部指数卡 + 历史弹窗”
- 本轮不做：
  - 不把这些指标扩展到个股详情页
  - 不把自定义基准日状态同步到首页所有指数卡
  - 不新增数据库表，仅复用现有主题指数序列与快照计算链路
- 实现假设：
  - 主题指数历史序列中的 `open/high/low/close` 足以支持“当日振幅”计算
  - 年度指标只需按当前自然年筛选历史点，不需要财年口径
  - 顶部卡片快照接口可以接受新增字段而不破坏现有前端
- 风险与边界：
  - 某些主题如果当年历史样本不足，年内指标需要优雅降级
  - 若实时快照仅有 `price` 无高低开，顶部卡片的“当日振幅”可能需要依赖最新历史点或扩展快照数据源
  - 若当前年第一天不是交易日，应自动取“当年首个可用交易日”

## Verification Steps
1. 主题指数单测
   - `python -m pytest test/test_a_share_matches_theme_index.py -q`
   - 重点验证：
     - 当日振幅
     - 当年涨跌幅
     - 当年振幅
     - 自定义基准日下的联动
2. 模板回归
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_matches_catalog.py -q`
   - 重点验证：
     - 顶部指数卡新增字段存在
     - 历史弹窗新增字段存在
3. 详情链路回归
   - `python -m pytest test/test_a_share_stock_analysis.py -q`
   - 目的是确认模板脚本调整未误伤其他页面
4. 诊断检查
   - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
   - `web/chanlun_chart/cl_app/templates/a_share_matches.html`
   - `web/chanlun_chart/cl_app/__init__.py`
5. 手工验收
   - 首页主题指数卡能同时看到：
     - 指数值
     - 当日涨跌幅
     - 当日振幅
     - 当年涨跌幅
     - 当年振幅
   - 打开历史弹窗后，上述指标也可见
   - 弹窗切换自定义基准日时，四项指标同步重算
   - 首页卡片继续保持默认基准日口径，不被弹窗临时状态污染
