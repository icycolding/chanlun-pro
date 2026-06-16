## Summary
- 目标：把 `a_share_matches` 顶部主题指数历史图从当前 `5日 / 20日 / 60日` 的短区间，升级为支持“最长/全部历史”查看。
- 同时目标：优化主题指数历史图的视觉质量，解决当前“图形不好看”的问题。
- 用户偏好已确认：
  - 历史长度方案：`最长/全部`
  - 额外要求：`图形要优化`

## Current State Analysis
- 当前首页顶部主题指数历史图入口位于 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 现有区间按钮只有：
    - `5日`
    - `20日`
    - `60日`
  - 对应位置：`theme-index-history-range`
- 当前历史图数据接口位于 `web/chanlun_chart/cl_app/__init__.py`
  - 路由：`POST /a_share_matches/theme_index_history`
  - 当前将 `lookback_days` 限制为 `max(1, min(120, ...))`
  - 这意味着即使前端放更长，也会被后端截断到 `120天`
- 当前历史数据构建位于 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - `_load_theme_index_constituent_histories(...)`
  - `build_theme_index_history_series(...)`
  - `build_theme_index_history(...)`
- 当前历史图绘制方式位于 `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 是一个轻量 SVG close 折线图
  - 只有：
    - 坐标边线
    - 面积填充
    - 单条折线
  - 不包含更好的视觉辅助元素，例如：
    - 网格线
    - 最值/最新值标记
    - 区间标签
    - 更清晰的状态文案
    - 更适合手机的层次化信息
- 当前历史加载底层能力：
  - `a_share_matches_catalog.py` 使用 `get_exchange(Market.A).klines(..., "d", args={"pages": pages})`
  - 当前页数上限是 `12`
  - 说明底层并非只能取 `60日`，但目前 UI 和接口都人为限制了历史长度

## Proposed Changes
### 1. 放开历史长度为“最长/全部”
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 将历史区间按钮从当前固定短档位改为更符合用户意图的档位：
    - `20日`
    - `60日`
    - `250日`
    - `最长`
  - 其中“最长”不再向后端传一个小天数，而是传一个明确的 `max` 语义值，避免 UI 文案与真实返回不一致。
  - 顶部指数卡默认打开时的 `lookback` 改为更长区间，优先使用：
    - 若后端支持“最长”语义，则默认打开 `最长`
    - 若考虑首屏性能，则默认打开 `250日`，并保留“最长”按钮
- 计划决策：
  - 这次以“用户一打开就能看到长历史”为核心，优先把默认区间也升级，不再默认 `20日`

### 2. 后端接口改为支持“最长/全部历史”
- 文件：`web/chanlun_chart/cl_app/__init__.py`
- 修改内容：
  - 让 `/a_share_matches/theme_index_history` 接口支持两种请求方式：
    - 数字型 `lookback_days`
    - 特殊值 `max` 或 `all`
  - 对应响应中增加：
    - `lookback_label`
    - `is_max_range`
  - 当请求为“最长”时，不再使用当前 `120天` 上限，而是调用下层最大可得历史能力
- 原因：
  - 当前 `min(120, ...)` 是最直接的限制来源，必须解除

### 3. 历史数据抓取层改为“尽可能长”
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 修改内容：
  - 扩展 `_load_theme_index_constituent_histories(...)`：
    - 支持 `lookback_days=None` 或 `range_mode="max"` 之类的最长模式
    - 在最长模式下增大 `pages`，尽可能多取 A 股日线历史
  - 保持健壮性：
    - 个别成分股历史不足时允许部分覆盖
    - 继续使用共同日期交集，保证主题指数序列不失真
  - 响应中增加覆盖说明：
    - 实际使用样本数
    - 实际生成历史点数
    - 是否为“最长可得历史”
- 设计约束：
  - 不做数据库持久化
  - 继续走当前实时/历史读取框架
  - 不新增新的行情源

### 4. 优化图形视觉
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 保留现有弹窗交互，但升级主题指数图表的视觉层次：
    - 加入横向网格线
    - 加入最右侧最新值高亮点
    - 加入起点/终点标签
    - 加入涨跌颜色语义
    - 加入更清晰的走势图标题、副标题、覆盖信息
    - 在手机端优化高度和留白
  - 图形从“单条朴素折线”升级为“更接近金融走势图”的样式：
    - 更平滑的线条观感
    - 更自然的渐变填充
    - 更明确的涨跌方向提示
  - 若数据点足够多，增加稀疏日期标签，避免底部完全没有时间感
- 不做内容：
  - 本次不把它改成真正的 K 线缠论图
  - 本次不接入原股票图表页引擎

### 5. 文案与状态统一
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 修改内容：
  - 把状态文案从“`N日历史`”统一为更自然的表达：
    - `最长历史`
    - `近250日`
    - `近60日`
  - 对最长模式补充说明：
    - “显示当前可获取的全部历史”
  - 空数据与失败提示做得更清楚：
    - 历史数据不足
    - 成分股覆盖不足
    - 当前无法生成最长历史

### 6. 测试更新
- 文件：`test/test_a_share_matches_catalog.py`
- 修改内容：
  - 更新模板断言：
    - 不再只校验 `5日 / 20日 / 60日`
    - 改为校验存在 `最长` 入口
    - 校验 `data-theme-index-lookback` 已改为更长默认值或最大模式
    - 校验历史图相关新文案和 UI hook
- 文件：`test/test_a_share_matches_theme_index.py`
- 修改内容：
  - 增加“最长模式”测试：
    - 允许 `lookback_days=None / max`
    - 返回尽可能多的历史点
  - 增加部分覆盖下的历史构建测试，防止长历史时因个股缺失而直接空掉
- 如需要，可增加接口测试：
  - 主题指数历史接口在 `max` 模式下返回结构完整

## Assumptions & Decisions
- 已确认：
  - 用户不要只到 `60日`
  - 用户要“尽可能长的时间”
  - 用户认为当前图形不好看，需要视觉优化
- 本次执行默认采用：
  - 历史范围优先级：`最长` > `250日` > `60日` > `20日`
  - 图表类型仍为主题指数专用自绘历史图，不接股票缠论引擎
  - 第一目标是“长度放开 + 视觉变好”，不是做更复杂分析指标
- 不在本次范围：
  - 把主题指数注册成真实交易标的
  - 引入新的前端图表库
  - 持久化存储主题指数历史序列

## Verification Steps
1. 运行主题指数相关测试：
   - `python -m pytest test/test_a_share_matches_catalog.py -q`
   - `python -m pytest test/test_a_share_matches_theme_index.py -q`
2. 手工验证首页：
   - 打开 `a_share_matches`
   - 点击任意顶部主题指数卡
   - 弹窗默认展示长区间历史
   - 可切换到 `最长`
   - 状态文案正确显示为“最长历史”或等价表达
3. 手工验证图形：
   - 有更清晰的走势层次
   - 最新值/终点信息可读
   - 手机端不拥挤、不变形
4. 异常验证：
   - 历史不足时仍能看到明确提示
   - 部分成分股缺失时不导致整图崩溃
