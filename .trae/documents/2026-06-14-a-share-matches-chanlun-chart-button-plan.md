# 增加卡片查看缠论图功能计划

## Summary

在 `a_share_matches` 页面为全部卡片增加“查看缠论图”按钮，点击后使用页内弹窗打开现有 `/chart` 页面，默认周期为 `日线`。本次改动覆盖三类卡片：

- 项目股票卡片
- 主映射 / 候选池 A 股卡片
- `Serenity 主题扩展股票` 卡片

实现原则：

- 复用现有 `/chart?market=...&code=...&frequency=...` 路由，不新增图表后端
- 不影响现有行情、tweets 详情、推荐脉络、主题扩展详情等功能
- 对于无法稳定映射到现有图表市场参数的股票，仍保留按钮；点击后在弹窗内给出明确的“不支持当前市场缠论图”提示，而不是静默隐藏

## Current State Analysis

### 已确认的现有能力

- `a_share_matches` 主页面模板在 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 现有卡片结构已经分为三类：
  - 项目股票卡片：带 `symbol / exchange / market / company_name / display_name`
  - A 股映射卡片：带 `data-a-share-code`
  - 主题扩展股票卡片：带 `code / detail_url`
- 现有图表路由已经存在于 `web/chanlun_chart/cl_app/__init__.py` 的 `/chart`
- `/chart` 使用参数：
  - `market`
  - `code`
  - `frequency`
- `/chart` 当前直接返回图表 HTML，适合嵌入 iframe 弹窗

### 已确认的相关现状

- `a_share_matches.html` 当前没有现成弹窗库或 modal 实现，需要在页面内新增原生弹窗结构和脚本
- 现有项目股票并不全是标准 `a/hk/us` 市场；已看到的 `market` 文本包含 `US/Canada`、`France`、`Taiwan`、`Israel`、`Japan`、`Canada`
- 现有 `a_share_matches_quotes.py` 里已有 `infer_project_quote_target()`，可用于推断部分项目股票的标准市场归属，适合作为图表目标推断的基础参考
- `test/test_a_share_matches_catalog.py` 已具备渲染 `a_share_matches.html` 的测试入口，可直接扩展模板断言

## Assumptions & Decisions

### 用户已确认的产品决策

- 按钮范围：全部卡片
- 打开方式：页内弹窗
- 默认周期：`日线`
- 不支持市场处理：按钮仍显示，但点击后要给出明确反馈

### 实现层决策

- 继续复用现有 `/chart`，不新增新的 chart 页面或 API
- 页面内新增一个通用图表弹窗：
  - 正常时以 iframe 加载 `/chart?...`
  - 失败或不支持时显示错误说明面板
- 为不同卡片统一生成 `chart_url` 或 `chart_unavailable_reason`
- 不修改现有项目股票 `tweet_detail_url`、扩展股票 `detail_url`、A 股行情加载逻辑

## Proposed Changes

### 1. `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

#### 变更内容

- 新增用于生成图表链接的 helper，至少包括：
  - A 股代码到 `/chart` 参数的构造
  - 主题扩展股票详情卡片附带 `chart_url`
- 为以下数据结构增加图表字段：
  - `theme_related_stocks`
  - `main_matches`
  - `candidate_matches`
- 视需要新增一个专门的图表目标推断函数，避免把图表逻辑散落到模板中

#### 目的

- 让 A 股类卡片在服务端就拿到稳定的 `chart_url`
- 保持模板渲染简单，不在模板里做复杂 market 推断

#### 具体做法

- A 股映射卡片与主题扩展股票卡片统一使用：
  - `market=a`
  - `code=<6位A股代码>`
  - `frequency=d`
- 为这些卡片新增：
  - `chart_url`
  - `chart_frequency_label`

### 2. `web/chanlun_chart/cl_app/a_share_matches_quotes.py`

#### 变更内容

- 新增或扩展一个“项目股票图表目标推断” helper，优先复用当前 `infer_project_quote_target()` 的市场推断思路

#### 目的

- 项目股票卡片使用的 `symbol / exchange / market` 并不直接等于 `/chart` 所需参数，需要统一转换层

#### 具体做法

- 为项目股票增加图表目标推断规则：
  - A 股项目股票：`market=a`，`code=标准A股代码`
  - 港股项目股票：`market=hk`，`code=标准港股代码`
  - 美股项目股票：`market=us`，`code=<symbol>`
  - 别名场景沿用现有规则，例如 `SIVE -> SIVEF`
- 对不能稳定推断为 `/chart` 可接受市场的项目股票，返回：
  - `chart_url=None`
  - `chart_unavailable_reason=<友好提示>`

### 3. `web/chanlun_chart/cl_app/__init__.py`

#### 变更内容

- 在 `a_share_matches()` 路由中，为项目股票注入图表相关字段
- 保持其他现有路由不变，不新增新的图表后端

#### 目的

- 项目股票卡片数据当前是在路由里补充 `tweet_detail_url`
- 图表字段也应在同一位置完成注入，避免模板直接推断

#### 具体做法

- 在遍历 `catalog["themes"] -> project_stocks` 时，为每只项目股票补：
  - `chart_url`
  - `chart_unavailable_reason`
  - `chart_frequency_label`

### 4. `web/chanlun_chart/cl_app/templates/a_share_matches.html`

#### 变更内容

- 为三类卡片都新增“查看缠论图”按钮
- 新增页面级通用弹窗结构、样式和脚本

#### 目的

- 统一交互，不让每种卡片各自实现一套打开逻辑
- 确保不打断当前页面阅读流程

#### 具体做法

- 项目股票卡片：
  - 在当前 `reason-actions` 区域增加“查看缠论图”按钮
  - 按钮使用服务端注入的 `chart_url`
- A 股主映射 / 候选池卡片：
  - 在卡片底部增加“查看缠论图”按钮
  - 使用 match 自带的 `chart_url`
- 主题扩展股票卡片：
  - 与“查看扩展详情”并列增加“查看缠论图”按钮
- 新增通用 modal：
  - 遮罩层
  - 标题栏
  - 关闭按钮
  - iframe 容器
  - 错误/不支持提示面板
- 新增前端脚本：
  - 绑定所有带图表数据的按钮
  - 若存在 `chart_url`，则打开 modal 并加载 iframe
  - 若没有 `chart_url`，则打开 modal 并显示 `chart_unavailable_reason`
  - modal 支持点击遮罩关闭、ESC 关闭

### 5. `web/chanlun_chart/cl_app/templates/a_share_match_theme_stock.html`

#### 变更内容

- 为主题扩展股票详情页增加“查看缠论图”按钮

#### 目的

- 让主题扩展股票在主页面和详情页都有一致入口
- 与新增主页面图表按钮保持一致体验

#### 具体做法

- 在现有 `actions` 区域增加按钮
- 若 `chart_url` 存在，则新标签页或弹窗二选一中的弹窗方案在此页复用简化版
- 为降低范围，本次优先采用：
  - 详情页按钮直接新标签页打开 `/chart`
  - 或者仅在计划执行时确认是否也复用同一 modal

执行时统一定为：

- **主页面使用页内 modal**
- **详情页先直接新标签页打开 `/chart`**

这样能控制本次改动范围，优先满足用户对“卡片按钮”的核心需求；如执行中发现详情页也必须一致，再复用 modal 结构

### 6. `test/test_a_share_matches_catalog.py`

#### 变更内容

- 扩展现有 catalog 和模板渲染测试

#### 目的

- 先锁定“新增图表按钮但不影响原有功能”的边界
- 防止按钮只加到部分卡片、或误伤现有按钮区块

#### 具体做法

- 新增断言：
  - 项目股票存在图表字段
  - A 股映射卡片存在图表字段
  - 主题扩展股票存在图表字段
  - 模板渲染后包含“查看缠论图”
  - 模板渲染后包含 modal 容器标识
  - 原有“查看推荐脉络”“查看扩展详情”仍然存在

### 7. 新增一个 focused test 文件或在现有测试中补 helper 测试

#### 候选文件

- 优先直接补到 `test/test_a_share_matches_catalog.py`
- 如果 helper 明显偏后端逻辑，也可新增：
  - `test/test_a_share_matches_quotes.py`

#### 变更内容

- 为项目股票图表目标推断补测试

#### 具体做法

- 覆盖至少以下场景：
  - A 股项目股票 -> `market=a`
  - 港股项目股票 -> `market=hk`
  - 美股项目股票 -> `market=us`
  - alias 场景，例如 `SIVE`
  - 无法推断市场时返回 `chart_unavailable_reason`

## Data Flow

### 项目股票卡片

1. `get_a_share_match_catalog()` 返回基础项目股票数据
2. `a_share_matches()` 路由为每只项目股票补充：
   - `tweet_detail_url`
   - `chart_url`
   - `chart_unavailable_reason`
3. `a_share_matches.html` 渲染图表按钮
4. 点击按钮：
   - 有 `chart_url` -> modal iframe 加载 `/chart?...`
   - 无 `chart_url` -> modal 显示不支持提示

### A 股映射 / 扩展股票卡片

1. catalog 构建阶段即生成 `chart_url`
2. 模板直接渲染图表按钮
3. 点击后进入同一个 modal 流程

## Edge Cases & Failure Modes

- `/chart` 返回 500：iframe 区域显示失败提示，并保留“在新标签页打开”备用链接
- 项目股票市场无法推断：modal 显示“不支持当前市场缠论图”
- 用户连续点击不同卡片：iframe `src` 覆盖更新，modal 内容同步切换
- 移动端：modal 需有安全的最大高度和滚动控制
- 不应影响原有：
  - A 股行情加载
  - tweet summaries 轮询
  - 主题导航高亮

## Verification Steps

### 自动化验证

- 运行：
  - `pytest test/test_a_share_matches_catalog.py -q`
  - 如 helper 测试拆分，则再运行对应测试文件

### 诊断检查

- 检查以下文件 diagnostics：
  - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
  - `web/chanlun_chart/cl_app/__init__.py`
  - `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 如改动详情页，则包括 `a_share_match_theme_stock.html`

### 页面行为核验

- 在 `a_share_matches` 页面确认：
  - 项目股票卡片显示“查看缠论图”
  - 主映射 / 候选池卡片显示“查看缠论图”
  - 主题扩展股票卡片显示“查看缠论图”
  - 点击可打开弹窗
  - 默认周期为日线
  - 原按钮仍存在且可正常点击
- 对至少一只不支持标准市场映射的项目股票确认：
  - 按钮仍显示
  - 点击后展示明确错误提示，而不是页面空白

