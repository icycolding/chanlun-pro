## Summary
- 目标：在 `a_share_matches` 中新增一个独立主题，围绕“AI 涉及的稀有金属 / 关键矿物”，按 Serenity 方法做外部锚点股筛选、A 股核心映射和相关股补充。
- 已锁定的产品决策：
  - 保留现有 `关键矿物 / 稀土 / 战略材料` 主题不动
  - 新增一个独立主题，不与现有关键矿物主题合并
  - 继续沿用当前 `a_share_matches` 的结构：`外部锚点股 -> A股 main_matches/candidate_matches -> theme_related_stocks`
  - 主题范围同时覆盖：
    - AI 半导体 / 光通信相关关键金属
    - 机器人 / 电机 / 永磁链相关关键矿物
  - 选股风格：`宁缺毋滥`，优先保留最接近稀缺层的少数核心标的
- 成功标准：
  - 新主题在 `a_share_matches` 页面正常出现并自动生成 A 股指数
  - 每个外部锚点股和核心 A 股映射都带有 Serenity 风格的 `selection_reason / scarcity_view / capacity_view / pricing_view / market_cap_research / segment_market_view`
  - 核心项目股、核心 A 股映射股和主题相关股都带有 `source_validation`，且满足现有测试要求的 `>= 2` 条来源
  - 回归测试通过，尤其是 `theme_count`、主题标题、代表性标的、认证来源和模板渲染

## Current State Analysis
- 主题数据集中维护在 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 主题由 `_THEMES` 统一组装，入口在 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L2256-L3676)
  - 单个主题由 `_theme(title, project_stocks)` 自动生成 slug、A 股指数和 `theme_related_stocks`，见 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L2200-L2231)
  - 主题指数权重与样本来自 `project_stocks.main_matches/candidate_matches + theme_related_stocks`，见 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L2134-L2197)
- 当前仓库里已经存在一个相近但更泛化的主题：
  - `关键矿物 / 稀土 / 战略材料`
  - 它在 `_THEME_RELATED_STOCKS` 和 `_THEMES` 中已有完整定义，且测试已覆盖 `VNP -> 600111` 等映射，见 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L1938-L2004) 和 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L3328-L3427)
- 当前研究元数据按多张表分散维护：
  - `_THEME_ACCENTS`
  - `_PROJECT_STOCK_REASON_DATA`
  - `_PROJECT_SOURCE_VALIDATIONS`
  - `_MATCH_SELECTION_METRICS`
  - `_A_SHARE_SOURCE_VALIDATIONS`
  - `_THEME_RELATED_STOCKS`
- 测试已明确约束：
  - `theme_count == 12`
  - 主题标题集合必须包含若干指定主题
  - 每个 theme/project/match/related 都要有完整结构
  - 代表性主题会检查具体 symbol/code 与来源认证，见 [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py#L63-L219) 和 [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py#L518-L585)
- 前端模板 `web/chanlun_chart/cl_app/templates/a_share_matches.html` 是通用渲染：
  - 新主题只要进 `catalog["themes"]`，页面会自动展示，无需新增专用组件
  - 因此本次主要改动应集中在 `a_share_matches_catalog.py` 与测试文件

## Proposed Changes
### 1. 新增独立主题定义
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 新增一个独立主题标题，固定命名为：`AI稀有金属 / 关键矿物 / 上游资源`
  - 在 `_THEME_ACCENTS` 中为该主题补一组独立 accent，避免和现有 `关键矿物 / 稀土 / 战略材料` 视觉完全重叠
  - 在 `_THEMES` 中新增一段 `_theme("AI稀有金属 / 关键矿物 / 上游资源", [...])`
- 原因：
  - 用户明确要求“新增独立主题”，不是覆盖旧主题
  - 现有 `_theme(...)` 会自动生成 slug、详情页地址与 A 股指数，不需要新增主题基础设施

### 2. 研究口径按 Serenity 方法拆成两条 AI 主线，但最终收敛为少数核心标的
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 先按产业链层级确定两个 AI 稀有金属子方向：
    - `半导体 / 光通信关键金属`
      - 优先看：镓、锗、铟、钽、钨等高纯材料、化合物材料、蒸镀/靶材/衬底相关稀缺层
    - `机器人 / 电机 / 永磁关键矿物`
      - 优先看：稀土分离、磁材、钕铁硼上游与高端永磁材料
  - 但最终主题内只保留少数最贴近稀缺层的项目股和 A 股核心映射，避免把“泛资源股”塞进来
  - 选股约束写入计划中并在执行时遵循：
    - 必须能清楚回答“它到底卡住 AI 哪个环节”
    - 必须有至少两条公开来源支撑
    - 必须说明为什么不是普通周期资源股
    - 对 A 股优先保留更接近分离/高纯材料/磁材/化合物材料的标的，弱化纯价格 beta
- 原因：
  - 用户选择了“关键矿物广义 + 两边都覆盖 + 宁缺毋滥”
  - 需要兼顾 AI 全口径，但不能把主题做成泛有色大全

### 3. 外部锚点股继续沿用当前结构，但更强调“链条锚点”而不是主题热度
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 继续使用 `_stock(...)` 形式定义少量外部锚点股
  - 外部锚点股的选择以“真实稀缺层”优先，而非仅按市值或热度排序
  - 计划中的执行约束：
    - 至少覆盖 1 个偏半导体/光通信关键金属锚点
    - 至少覆盖 1 个偏稀土/永磁/机器人关键矿物锚点
    - 若证据支持，可用 2-4 个外部锚点股，不追求堆数量
  - 同时补齐这些锚点对应的：
    - `_PROJECT_STOCK_REASON_DATA`
    - `_PROJECT_SOURCE_VALIDATIONS`
    - `_PROJECT_SELECTION_METRICS`
- 原因：
  - 当前 `a_share_matches` 的风格就是“先有外部参考，再映射 A 股”
  - 用户已明确要沿用这套结构

### 4. 新主题的 A 股核心映射与相关股分层维护
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 在新增主题下，为每个外部锚点股配置：
    - `main_matches`：最接近稀缺层的 A 股核心映射
    - `candidate_matches`：强相关但纯度略低的补充映射
  - 同时在 `_THEME_RELATED_STOCKS` 中为该主题补一组主题相关股，用于：
    - 扩充主题横截面
    - 参与主题指数样本
  - 对每个 A 股 match/related 至少补齐：
    - `source_validation`
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
- 执行时的筛选原则：
  - `main_matches` 更偏：
    - 稀土分离 / 高端永磁 / 高纯金属 / 化合物材料 / 关键靶材 / 上游资源控制
  - `candidate_matches` 更偏：
    - 需求传导明确，但离真正稀缺层稍远的材料加工或配套
  - `theme_related_stocks` 只保留对主题理解有帮助的少量扩展样本
- 原因：
  - 当前页面与详情页已经围绕这些字段工作
  - 若不补齐这些层级，模板和详情页虽然能渲染，但内容会明显发虚

### 5. 来源认证按现有测试标准执行
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 为新增主题中的：
    - 外部锚点股
    - 主要 A 股映射
    - 主题相关股
    全部补 `source_validation`
  - 每个核心对象至少保留 2 条来源
  - 来源优先级保持与现有 Serenity 主题一致：
    - 公司年报 / 季报 / 业绩说明会
    - 交易所公告
    - 官方新闻稿 / 官网页面
    - 权威行业媒体或研究材料
  - 对“AI 关联性”必须做显式说明，不能只证明它是资源公司
- 原因：
  - 现有测试要求 `status == 已认证` 且 `sources >= 2`
  - 用户要求“按 Serenity 的方法查找”，方法论里源验证是硬要求

### 6. 测试同步更新为“新增第 13 个主题”
- 文件：`test/test_a_share_matches_catalog.py`
- 做法：
  - 将 `theme_count == 12` 更新为 `13`
  - 将 `theme_titles` 断言补入新主题标题：`AI稀有金属 / 关键矿物 / 上游资源`
  - 为新主题新增结构断言：
    - 主题存在
    - 至少有项目股
    - 至少有主题相关股
    - A 股指数样本已生成
  - 新增代表性断言：
    - 抽取 1 个外部锚点股 symbol
    - 抽取 1 个核心 A 股映射 code
    - 验证它们的 `source_validation`、`selection_reason`、`scarcity_view` 等字段非空
  - 将 `representative_pairs` 扩充一组新主题样本
- 原因：
  - 这是新增主题，最直接的回归就是结构与代表性数据校验

### 7. 详情页链路仅做被动回归，不新增专属 UI
- 文件：`test/test_a_share_stock_analysis.py`
- 做法：
  - 不计划新增模板或页面结构
  - 仅在回归阶段确认新主题下的 project/match 数据仍能被 stock analysis 详情页读取
- 原因：
  - `a_share_stock_analysis.py` 是从 `get_a_share_match_catalog()` 反查详情
  - 只要 catalog 结构正确，详情页应自动兼容

## Assumptions & Decisions
- 已锁定决策：
  - 新主题名称：`AI稀有金属 / 关键矿物 / 上游资源`
  - 保留旧主题：`关键矿物 / 稀土 / 战略材料`
  - 采用现有 `外部锚点股 -> A股映射 -> 主题相关股` 结构
  - 覆盖两条 AI 主线：
    - 半导体 / 光通信关键金属
    - 机器人 / 永磁关键矿物
  - 选股策略：`宁缺毋滥`
- 范围内：
  - `a_share_matches_catalog.py` 新增主题数据与认证来源
  - `test/test_a_share_matches_catalog.py` 更新计数与代表性断言
  - 必要时回归 `test/test_a_share_stock_analysis.py`
- 范围外：
  - 不新增专用页面、专用接口或专用模板
  - 不改现有关键矿物主题内容
  - 不新增数据库结构
- 研究执行边界：
  - 必须证明“AI 需求如何传导到该稀有金属环节”
  - 不把普通大宗资源 beta 直接当 Serenity 结论
  - 若某标的只能证明“它是矿业公司”，不能证明其 AI 关键性，应降级或剔除

## Verification Steps
1. 结构与主题回归
   - `python -m pytest test/test_a_share_matches_catalog.py -q`
   - 重点检查：
     - `theme_count` 从 12 变 13
     - 新主题标题存在
     - 新主题项目股、A 股映射、相关股完整
2. 详情页兼容回归
   - `python -m pytest test/test_a_share_stock_analysis.py -q`
   - 重点检查：
     - 新主题下 project/match 的详情页字段仍能正确读取
3. 诊断检查
   - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
   - `test/test_a_share_matches_catalog.py`
4. 手工验收
   - 打开 `a_share_matches` 页面，确认新主题可见
   - 主题下能看到 Serenity 风格的核心锚点、A 股映射和相关股
   - 新主题自动生成顶部 A 股指数卡
   - 点击项目股 / A 股映射详情时，字段完整、不空白
