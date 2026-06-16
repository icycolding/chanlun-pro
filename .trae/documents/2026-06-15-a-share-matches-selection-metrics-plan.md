# A Share Matches 选股解释与规模字段增强计划

## Summary
- 目标：为 `a_share_matches` 的 `project_stocks` 与 `main_matches/candidate_matches` 卡片补齐结构化选股解释，明确展示“为什么符合、是否稀缺、是否扩产难、是否涨价、研究市值、实时市值、产业链环节市场规模、公司份额”，并保持现有主题/详情页/行情与财务异步加载链路可复用。
- 成功标准：
  - 项目股卡与 A 股映射卡都能直接看到新增字段，不需要跳详情页才能理解核心判断。
  - 研究字段带来源认证，至少复用现有 `source_validation` 体系。
  - 卡片同时显示研究口径市值与实时口径市值；实时市值取不到时有稳定降级文案，不出现空白或误导性数字。
  - `test_a_share_matches_catalog.py` 与相关页面/数据测试覆盖新字段和新文案。

## Current State Analysis
- 数据主入口是 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)。
  - `project_stocks` 已有 `research_summary`、`serenity_reason_summary`、`stage_snapshot`、`market_cap_snapshot`、`source_validation`。
  - `main_matches/candidate_matches` 已有 `supply_chain_position`、`mapping_path`、`judgement`、`major_risk`、`source_validation`。
  - 现状偏“叙事摘要”，没有统一的结构化字段去表达稀缺性、扩产难度、涨价、市场规模、份额。
- 主页面模板是 [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html)。
  - 项目股卡当前展示公司信息、`Serenity 视角`、`Serenity 推荐理由`、`当前阶段`、`市值空间`、`财务分析`。
  - A 股映射卡当前展示 `供应链位置`、`映射路径`、`一句话判断`、`主要风险`、`财务分析`。
  - 现有 DOM 已有异步更新入口，适合继续扩展卡片内容而不用重写页面骨架。
- 路由入口在 [__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py)。
  - `/a_share_matches/stock_analysis_summaries` 负责卡片级财务摘要。
  - `/a_share_matches/project_ticks` 负责项目股行情快照。
  - `/ticks` 已被模板用于 A 股行情加载。
  - 当前行情快照只见 `price/rate/high/low/open/swing_rate`，没有已确认的 `market_cap` 输出。
- 行情工具在 [a_share_matches_quotes.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_quotes.py)。
  - `build_tick_snapshot()` 目前只拼价格与波动。
  - 仓库内未发现稳定使用中的 `market_value/capitalization/流通市值` 字段，说明实时市值要显式加提取和降级规则。
- 详情支撑信息在 [a_share_matches_tweet_notes.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py)。
  - 已有大量“稀缺性、市值空间、阶段、产业链节点”的叙事素材。
  - 可以作为结构化字段的研究来源，但当前没有统一 schema 暴露给主页卡片。
- 测试基线在 [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py)。
  - 已验证主题数、项目股数、认证字段、项目股与映射卡基本结构。
  - 还没有覆盖新的选股解释字段和市值/规模/份额字段。

## Assumptions & Decisions
- 范围只覆盖：
  - `project_stocks`
  - `main_matches`
  - `candidate_matches`
- 不在本轮内强制同步：
  - `theme_related_stocks` 详情页
  - `a_share_match_theme_stock.html`
- 市值展示采用双口径：
  - 研究口径：静态研究锚点/区间，来自 catalog 静态数据。
  - 实时口径：从行情快照尽力提取总市值；若行情源不提供，则显示固定降级文案 `实时总市值待行情源补齐`。
- 市场规模与份额展示采用“文本区间 + 份额判断”：
  - 优先展示 `xx 亿/xx 十亿美元区间`
  - 份额展示为 `约 x%-y%` 或 `低/中/高份额`
  - 必须挂来源认证，避免无来源定量描述。
- 涨价字段不强求“已涨价”二元判断，统一拆成：
  - `pricing_power_label`：`已涨价` / `有涨价基础` / `价格传导弱`
  - `pricing_power_detail`：一句话解释价格传导逻辑
- 稀缺性与扩产难度也统一拆成：
  - `scarcity_label` + `scarcity_detail`
  - `capacity_label` + `capacity_detail`
- 实施时优先复用现有 `source_validation`，不额外新建第二套“认证体系”字段。

## Proposed Changes

### 1. 扩展 catalog 数据结构
- 修改文件：[a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)
- 变更内容：
  - 为 `project_stocks` 新增结构化字段：
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
  - 为 `main_matches/candidate_matches` 新增同构字段：
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
  - 所有新增结构建议统一成小对象，避免模板散落硬编码。
- 推荐字段结构：

```python
{
    "selection_reason": {
        "summary": "为什么这只股票符合 Serenity 方法",
        "fit_basis": "卡住的环节 / 为什么不是普通受益股",
    },
    "scarcity_view": {
        "label": "高",
        "detail": "供应商数量少、验证周期长、替代成本高",
    },
    "capacity_view": {
        "label": "扩产难",
        "detail": "产线爬坡慢 / 客户认证长 / 上游材料约束强",
    },
    "pricing_view": {
        "label": "有涨价基础",
        "detail": "供需偏紧时更容易向下游传导",
    },
    "market_cap_research": {
        "current_text": "当前按 60-90 亿美元理解",
        "upside_text": "若验证成立可上看 120-150 亿美元",
    },
    "segment_market_view": {
        "market_size_text": "对应环节市场规模约 80-120 亿美元",
        "company_share_text": "公司份额约 8%-12%",
        "share_level": "中高",
    },
}
```

- 实施原则：
  - `selection_reason.summary` 不重复 `research_summary` 原文，要更聚焦“为什么选它”。
  - `market_cap_research.current_text` 与已有 `market_cap_snapshot.current_anchor` 对齐；可以把旧字段作为兼容来源，但新模板读取新字段。
  - `segment_market_view` 的区间和份额必须与 `source_validation.summary/sources` 能对应得上。

### 2. 统一研究辅助构造函数
- 修改文件：[a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)
- 变更内容：
  - 新增内部 helper，例如：
    - `_selection_reason()`
    - `_scarcity_view()`
    - `_capacity_view()`
    - `_pricing_view()`
    - `_market_cap_research()`
    - `_segment_market_view()`
  - 在 `_stock()` 与 `_match()` 中统一注入默认值，避免未来新增主题时漏字段。
- 目的：
  - 把数据 schema 固定住。
  - 让后续按主题补数据时，不需要每个对象手写重复字典。

### 3. 扩展实时市值快照能力
- 修改文件：[a_share_matches_quotes.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_quotes.py)
- 变更内容：
  - 在 `build_tick_snapshot()` 中增加实时市值提取逻辑。
  - 提取顺序固定为：
    - `tick.market_cap`
    - `tick.market_value`
    - `tick.capitalization`
    - `tick.total_mv`
    - `tick.circulation_value`
  - 仅当字段存在且为有效数字时才返回。
  - 新增格式化字段，例如：
    - `market_cap`
    - `market_cap_text`
    - `market_cap_source`
- 降级规则：
  - 如果上述字段全部缺失，不做推算型造数。
  - 返回：

```python
{
    "market_cap": None,
    "market_cap_text": "实时总市值待行情源补齐",
    "market_cap_source": "tick_unavailable",
}
```

- 原因：
  - 当前仓库没有总股本或总市值稳定来源，不能拿价格硬算。
  - 必须把“不知道”表达清楚，避免错误数字。

### 4. 扩展路由返回给前端的数据
- 修改文件：[__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py)
- 变更内容：
  - 让 `/a_share_matches/project_ticks` 保留原价格字段，并额外透出实时市值字段。
  - 检查 `/ticks` 的返回结构是否同样可携带 `market_cap_text`；若当前通用 `/ticks` 路由已复用同一 snapshot builder，则只需模板读取即可，否则补齐 A 股分支。
  - 若卡片研究字段需要后端合并，也可在 `/a_share_matches/stock_analysis_summaries` 中顺带返回结构化研究摘要，但优先建议从 `catalog` 直接渲染静态研究字段，减少异步耦合。

### 5. 改造主页卡片模板
- 修改文件：[a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html)
- 项目股卡新增展示块：
  - `为什么符合`
  - `稀缺性`
  - `扩产难度`
  - `涨价能力`
  - `研究市值`
  - `实时市值`
  - `环节市场规模`
  - `公司份额`
- A 股映射卡新增同样字段，但版式更紧凑，避免卡片过长。
- 建议布局：
  - 把当前 `snapshot-grid` 升级成 `selection-metric-grid`
  - 每张卡用 2 列或 4 宫格呈现核心指标
  - 文本长字段单独占一行，短标签用 badge/card
- 具体展示建议：
  - 项目股卡：
    - 保留 `Serenity 视角`、`推荐理由`
    - 新增一个 `为什么选它` 区块
    - `研究市值/实时市值/市场规模/份额` 放在同一组信息卡
  - 映射卡：
    - `供应链位置/映射路径/一句话判断/主要风险` 保留
    - 新增一组 `稀缺/扩产/涨价/份额`
    - 研究市值与实时市值放在卡片底部或副标题区
- UI 约束：
  - 不删除已有 `财务分析` 块
  - 不改变按钮顺序与 `data-*` 属性
  - 保持现有移动端断点可工作

### 6. 扩展前端行情渲染
- 修改文件：[a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html)
- 变更内容：
  - 在现有 `fetch("/a_share_matches/project_ticks")` 与 `fetch("/ticks")` 处理逻辑里，新增实时市值渲染。
  - 为项目股卡和 A 股映射卡分别增加：
    - `data-market-cap-live`
    - 或单独的 DOM 容器用于写入实时市值
  - 页面初始态显示：
    - `实时总市值加载中...`
  - 请求成功后更新为 `market_cap_text`
  - 请求失败时更新为：
    - `实时总市值加载失败`
  - 行情无字段时更新为：
    - `实时总市值待行情源补齐`

### 7. 详情页是否同步的兼容处理
- 修改文件：[a_share_match_stock_analysis.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html)
- 本轮不要求完整同步主页新增字段，但建议顺手补最小兼容：
  - 显示 `研究市值`
  - 显示 `实时市值`
  - 显示 `环节市场规模 / 公司份额`
- 原因：
  - 否则主页和详情页会形成认知断层。
  - 该模板结构简单，补 1 个 panel 即可，不需要大改。

### 8. 扩展测试
- 修改文件：[test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py)
- 新增断言：
  - 每个 `project_stock` 都有：
    - `selection_reason.summary`
    - `scarcity_view.label/detail`
    - `capacity_view.label/detail`
    - `pricing_view.label/detail`
    - `market_cap_research.current_text`
    - `segment_market_view.market_size_text`
    - `segment_market_view.company_share_text`
  - 每个 `match` 也有同样字段。
  - 模板渲染后包含文案：
    - `为什么符合`
    - `稀缺性`
    - `扩产难度`
    - `涨价能力`
    - `研究市值`
    - `实时市值`
    - `环节市场规模`
    - `公司份额`
- 建议新增针对行情快照的测试文件或补现有测试：
  - 若已有 quotes 测试，优先补在 [test_a_share_matches_quotes.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_quotes.py)
  - 重点验证：
    - `build_tick_snapshot()` 有市值字段时格式化正确
    - 无市值字段时输出固定降级文案

## Execution Plan

### 步骤 1：先锁数据 schema
- 先修改 `a_share_matches_catalog.py` 的 helper 和默认字段。
- 目标是让任何 stock/match 即使未补全研究数据，也有稳定默认值，不会把模板渲染炸掉。

### 步骤 2：为已做过来源认证的主题先补字段
- 优先补当前已经重做过的 3 个主题：
  - 光模块 / CPO / 光子器件
  - 光子材料 / 衬底 / 外延 / SOI
  - AI互连 / 连接芯片 / AEC
- 原因：
  - 这些主题已有强来源认证，最容易先把“市场规模/份额/稀缺性/扩产难/涨价”补齐。
  - 其余主题先用默认值或后续再扩。

### 步骤 3：扩展实时行情返回
- 修改 `a_share_matches_quotes.py` 与对应路由，把 `market_cap_text` 带回前端。
- 优先保证“有值就显示、没值就清晰降级”。

### 步骤 4：改主页模板
- 先改项目股卡，再改映射卡。
- 每改一层就跑模板测试，避免样式和结构一起失控。

### 步骤 5：补详情页最小同步
- 只做一个简洁 panel，不把详情页也改成大表格。

### 步骤 6：跑完整回归
- 重点跑：
  - `test/test_a_share_matches_catalog.py`
  - `test/test_a_share_matches_quotes.py`
  - `test/test_a_share_stock_analysis.py`
  - `test/test_a_share_matches_tweets.py`

## Verification Steps
- 数据结构验证：
  - `get_a_share_match_catalog()` 返回的每个 `project_stock` 与 `match` 都有新增字段。
  - 对于已重做的光通信链 3 个主题，新增字段应不是默认空文案。
- 模板验证：
  - `a_share_matches.html` 能渲染新增模块，不破坏现有按钮、卡片分组和图表入口。
  - 移动端下新增指标块不会溢出。
- 行情验证：
  - 项目股卡能显示 `实时市值`。
  - A 股映射卡能显示 `实时市值`。
  - 行情缺字段时显示 `实时总市值待行情源补齐`。
- 内容验证：
  - 卡片上能直接回答：
    - 为什么符合
    - 是否稀缺
    - 是否扩产难
    - 是否有涨价基础
    - 当前研究市值
    - 实时总市值
    - 环节市场有多大
    - 这只股票份额大概多少
- 测试验证：
  - `pytest test/test_a_share_matches_catalog.py -q`
  - `pytest test/test_a_share_matches_quotes.py -q`
  - `pytest test/test_a_share_stock_analysis.py test/test_a_share_matches_tweets.py -q`

