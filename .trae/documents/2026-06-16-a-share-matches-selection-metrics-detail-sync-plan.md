# A Share Matches 选股说明与规模信息补齐实施计划

## Summary
- 目标：让 `a_share_matches` 的项目股卡、A 股映射卡和个股详情页，都能明确展示“为什么符合、是否稀缺、是否扩产难、是否具备涨价能力、研究市值、实时市值、产业链环节市场规模、公司份额”。
- 成功标准：
  - `web/chanlun_chart/cl_app/templates/a_share_matches.html` 的项目股卡和映射卡均展示上述字段。
  - 卡片上的实时市值来自行情快照；行情无字段时统一降级为 `实时总市值待行情源补齐`，不做推算。
  - `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html` 至少补齐一组兼容信息，避免主页与详情页表达断层。
  - `test/test_a_share_matches_catalog.py`、`test/test_a_share_matches_quotes.py`、`test/test_a_share_stock_analysis.py` 覆盖新增字段与降级文案。

## Current State Analysis
- `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 已存在结构化 helper：`_selection_reason()`、`_scarcity_view()`、`_capacity_view()`、`_pricing_view()`、`_market_cap_research()`、`_segment_market_view()`。
  - 已存在 `_PROJECT_SELECTION_METRICS` 与 `_MATCH_SELECTION_METRICS`，并且 `_stock()`、`_match()` 已把这些字段注入返回对象。
  - 现状说明：主页卡所需核心 schema 基本到位，后续执行重点不是“再设计 schema”，而是“补齐缺失值、保证所有目标主题数据完整、保持详情页兼容”。
- `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
  - 相关测试已经表明 `build_tick_snapshot()` 设计为返回 `market_cap`、`market_cap_text`、`market_cap_source`。
  - 当前执行计划里不需要重新发明实时市值规则，只需要保证模板和详情页消费这个字段的行为一致。
- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - `test/test_a_share_matches_catalog.py` 已要求页面出现 `为什么符合`、`稀缺性`、`扩产难度`、`涨价能力`、`研究市值`、`实时市值`、`环节市场规模`、`公司份额` 等文案。
  - 说明主页卡片 UI 方向已经锁定，后续只需围绕现有样式结构做修补和回归，不需要改页面信息架构。
- `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
  - 已新增 `_find_selection_metrics()`，`build_stock_analysis_detail_payload()` 也已经开始把主页卡的结构化字段合并到详情 payload。
  - 现状缺口：详情模板还没有消费这些字段，`market_cap_live_text` 目前仅有默认文案，没有在详情页显示。
- `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
  - 当前只展示基本元信息、财务分析、AI 财务解读、最新新闻。
  - 这是本轮最明确的剩余缺口，需要补一个最小兼容 panel，而不是重做整页布局。
- `test/test_a_share_stock_analysis.py`
  - 目前覆盖 `build_stock_analysis_detail_payload()` 的财务、AI 解读、新闻和 tweet link。
  - 还没有断言详情 payload/详情模板对 `selection_reason`、`market_cap_live_text`、`segment_market_view` 的处理。

## Assumptions & Decisions
- 范围聚焦三层对象：
  - `project_stocks`
  - `main_matches`
  - `candidate_matches`
- 研究信息与实时信息分离：
  - `market_cap_research` 负责静态研究口径。
  - `market_cap_live_text` / `market_cap_text` 负责行情口径。
- 实时市值规则固定，不再追加新的推算逻辑：
  - 仅消费 `build_tick_snapshot()` 提供的显式字段。
  - 没有字段时统一显示 `实时总市值待行情源补齐`。
- 详情页本轮只做“最小兼容同步”，不复制主页全部卡片层次：
  - 必须显示 `为什么符合`
  - 必须显示 `研究市值`
  - 必须显示 `实时市值`
  - 必须显示 `环节市场规模 / 公司份额`
  - `稀缺性 / 扩产难度 / 涨价能力` 可以同一 panel 内紧凑展示
- 数据补齐优先级固定：
  - 先保证已经重做并带认证的三条光通信链主题完整
  - 再用默认 helper 兜底其余主题，确保模板永不因字段缺失而报错
- 不在本轮范围：
  - `theme_related_stocks` 详情页 schema 扩展
  - 主页之外的新接口设计
  - 老首页删除项的清理请求

## Proposed Changes

### 1. 核对并补齐 catalog 的结构化字段覆盖面
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 变更目标：
  - 逐个检查已认证的三条主题：
    - `光模块 / CPO / 光子器件`
    - `光子材料 / 衬底 / 外延 / SOI`
    - `AI互连 / 连接芯片 / AEC`
  - 确保这些主题下的 `project_stocks`、`main_matches`、`candidate_matches` 都存在非空的：
    - `selection_reason.summary`
    - `selection_reason.fit_basis`
    - `scarcity_view.label/detail`
    - `capacity_view.label/detail`
    - `pricing_view.label/detail`
    - `market_cap_research.current_text/upside_text`
    - `segment_market_view.market_size_text/company_share_text/share_level`
- 实施方式：
  - 以 `_PROJECT_SELECTION_METRICS`、`_MATCH_SELECTION_METRICS` 为主维护点。
  - 避免把研究文本散落回各个 `_stock()` / `_match()` 调用处，保持单点维护。
- 决策：
  - 对于没有可靠定量份额的对象，允许使用“低/中/高份额 + 文本区间”的方式表达，但必须保留 `company_share_text` 非空。

### 2. 固化详情 payload 对结构化字段的输出契约
- 文件：`web/chanlun_chart/cl_app/a_share_stock_analysis.py`
- 变更目标：
  - 保证 `build_stock_analysis_detail_payload()` 总是返回以下键，即使 catalog 中缺失也有默认值：
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
    - `market_cap_live_text`
- 实施方式：
  - 继续复用 `_find_selection_metrics()`，但要在 payload 层补一层默认值合并，避免模板直接访问时出现 KeyError 或空对象。
  - 保持现有财务/新闻逻辑不变，不把新闻重新带回主页卡。
- 决策：
  - `market_cap_live_text` 本轮先展示默认文案，后续如有详情页异步行情需求再扩展接口；本轮不新增详情页专用行情请求。

### 3. 为详情页增加一个最小兼容研究信息面板
- 文件：`web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
- 变更目标：
  - 在现有“财务分析”和“最新新闻”之间，插入一个新的研究信息 panel。
  - panel 内展示：
    - `为什么符合`
    - `稀缺性`
    - `扩产难度`
    - `涨价能力`
    - `研究市值`
    - `实时市值`
    - `环节市场规模`
    - `公司份额`
- 实施方式：
  - 复用页面现有暗色面板风格，新增紧凑型 grid 样式，不重做顶栏和操作区。
  - 用文本块承接长说明，用两列小卡承接短标签。
- 决策：
  - 详情页 `实时市值` 本轮显示 `analysis.market_cap_live_text`，默认即 `实时总市值待行情源补齐`。
  - 不在详情页新增加载脚本，保持纯服务端渲染。

### 4. 确认主页卡片继续消费现有字段，不再改变接口形状
- 文件：`web/chanlun_chart/cl_app/templates/a_share_matches.html`
- 变更目标：
  - 只做必要校验和小修，不重新设计 DOM 层级。
  - 保证项目股卡和 A 股映射卡的实时市值位置与研究市值区块保持一致。
  - 确认 JS 渲染在以下三种场景文案稳定：
    - 请求成功且行情含 `market_cap_text`
    - 请求成功但行情缺 `market_cap_text`
    - 请求失败
- 实施方式：
  - 保持当前异步接口：
    - `/a_share_matches/project_ticks`
    - `/ticks`
  - 保持当前财务摘要接口：
    - `/a_share_matches/stock_analysis_summaries`
- 决策：
  - 不再新增字段到 `stock_analysis_summaries` 返回体，主页静态研究信息仍直接来自 catalog，减少前后端耦合。

### 5. 扩展测试到详情页兼容与实时市值降级链路
- 文件：`test/test_a_share_stock_analysis.py`
- 变更目标：
  - 新增断言，验证 `build_stock_analysis_detail_payload()` 至少返回：
    - `selection_reason["summary"]`
    - `market_cap_research["current_text"]`
    - `segment_market_view["market_size_text"]`
    - `market_cap_live_text`
  - 对项目股和映射股各覆盖一个样例，避免只测一侧。
- 文件：`test/test_a_share_matches_catalog.py`
- 变更目标：
  - 保持现有结构断言，必要时新增对 `share_level` 的显式断言，确保“份额等级”不是模板死字串。
  - 新增或补充详情页模板渲染测试；若当前测试文件不适合，可在本文件中新增一个只渲染 `a_share_match_stock_analysis.html` 的 helper。
- 文件：`test/test_a_share_matches_quotes.py`
- 变更目标：
  - 保持已有快照测试，必要时补充“优先级取值顺序”测试，例如 `market_cap` 优先于 `market_value`。
- 决策：
  - 本轮测试重点是“字段存在”和“降级文案正确”，不是数值精度回归的大规模覆盖。

### 6. 最终执行顺序
- 第一步：完善 `a_share_matches_catalog.py` 的数据覆盖，保证三条光通信链主题完整，其余对象有默认值兜底。
- 第二步：完善 `a_share_stock_analysis.py` 的详情 payload 默认值合并。
- 第三步：更新 `a_share_match_stock_analysis.html`，加入最小兼容研究 panel。
- 第四步：检查 `a_share_matches.html` 是否还存在遗漏的实时市值占位或异常文案。
- 第五步：补测试并跑回归，按失败结果修正实现。

## Verification Steps
- 语法与诊断检查：
  - `GetDiagnostics` 检查最近编辑文件：
    - `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
    - `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
    - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 目标测试命令：
  - `pytest test/test_a_share_matches_catalog.py -q`
  - `pytest test/test_a_share_matches_quotes.py -q`
  - `pytest test/test_a_share_stock_analysis.py -q`
- 验收点：
  - 主页卡片能看到研究市值与实时市值两个口径。
  - 主页卡片能看到“为什么符合、稀缺性、扩产难度、涨价能力、环节市场规模、公司份额”。
  - 个股详情页新增研究信息 panel，且不影响原有财务分析、AI 解读、最新新闻区块。
  - 无可轻易修复的 linter / template / pytest 回归。
