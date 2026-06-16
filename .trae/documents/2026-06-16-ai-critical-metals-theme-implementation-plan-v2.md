## Summary
- 目标：在现有 `a_share_matches` 体系中新增一个独立主题 `AI稀有金属 / 关键矿物 / 上游资源`，按 Serenity 方法把 AI 真实会卡住的稀有金属层拆成两条主线，并接入外部锚点股、A 股核心映射、主题相关股和主题指数。
- 已锁定的产品决策：
  - 保留原主题 `关键矿物 / 稀土 / 战略材料`，不替换、不合并。
  - 继续沿用当前结构：`外部锚点股 -> main_matches / candidate_matches -> theme_related_stocks`。
  - 覆盖两条 AI 主线：
    - `半导体 / 光通信关键金属`
    - `机器人 / 电机 / 永磁关键矿物`
  - 选股风格为 `宁缺毋滥`，只保留最贴近稀缺层、能说清楚“到底卡住 AI 哪个环节”的标的。
- 本次计划输出的是执行方案，不在本轮 `/plan` 内直接改业务文件。

## Current State Analysis
- 主题主数据都在 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`：
  - `_THEME_ACCENTS` 维护主题配色。
  - `_PROJECT_STOCK_REASON_DATA` / `_PROJECT_SOURCE_VALIDATIONS` / `_PROJECT_SELECTION_METRICS` 维护外部锚点股研究元数据。
  - `_A_SHARE_SOURCE_VALIDATIONS` / `_MATCH_SELECTION_METRICS` 维护 A 股映射股研究元数据。
  - `_THEME_RELATED_STOCKS` 维护每个主题的扩展股票。
  - `_THEMES` 负责最终组装主题，并自动生成主题指数。
- 当前测试已经先行改成“新主题必须存在”：
  - `test/test_a_share_matches_catalog.py` 已要求 `theme_count == 13`。
  - 同文件已要求新主题标题为 `AI稀有金属 / 关键矿物 / 上游资源`。
  - 同文件已要求该主题至少包含项目股 `AXTI`、`MP`，并至少包含映射股 `002428`、`600111`、`300748`。
- 当前仓库里“已有可复用”和“仍然缺失”的内容已经分明：
  - 已有：
    - `AXTI` 的项目股推荐语、来源认证、选择指标。
    - `002428` 的来源认证和选择指标。
    - `600111`、`600392` 的来源认证和选择指标。
    - `AXTI` 的 tweet note 已存在于 `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`。
  - 缺失：
    - `MP` 的项目股推荐语、来源认证、选择指标。
    - `MP` 的 tweet note。
    - `300748` 的 A 股来源认证与选择指标。
    - 若使用 `600497` 作为新主题候选映射，也需要新增其 A 股来源认证与选择指标。
    - 新主题在 `_THEME_ACCENTS`、`_THEME_RELATED_STOCKS`、`_THEMES` 中的定义。
- 需要注意一个关键实现约束：
  - `_MATCH_SELECTION_METRICS` 是按 A 股 `code` 全局复用，不是按主题局部配置。
  - 这意味着如果新主题复用 `002428`、`600111` 等旧主题已有标的，修改后的文案必须同时满足旧测试和新测试，不能只为新主题写一套互斥口径。
- 还有一个容易漏掉的隐藏依赖：
  - `test/test_a_share_matches_catalog.py` 里的 `test_all_project_stocks_have_rich_tweet_note_content` 会遍历所有 `project_stocks` 调 `get_project_tweet_note(symbol)`。
  - 所以新增 `MP` 作为项目股时，除了 `catalog` 本体，还必须同步补 `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`。

## Assumptions & Decisions
- 新主题名称固定为：`AI稀有金属 / 关键矿物 / 上游资源`。
- 主题研究框架固定为两条主线，但最终收敛成两个外部锚点股：
  - `AXTI`：代表 AI 光通信 / 化合物半导体 / InP 与锗材料这条上游材料链。
  - `MP`：代表稀土分离 -> NdPr -> 高性能 NdFeB 永磁 -> 机器人电机 / physical AI 这条关键矿物流。
- 新主题的外部锚点股数量固定为 `2`，不再额外扩成 3-4 只，避免主题失焦。
- 新主题的 A 股映射采用以下固定结构：
  - `AXTI`
    - `main_matches`：`002428 云南锗业`
    - `candidate_matches`：`600497 驰宏锌锗`
  - `MP`
    - `main_matches`：`600111 北方稀土`、`300748 金力永磁`
    - `candidate_matches`：`600392 盛和资源`
- 新主题的 `theme_related_stocks` 固定为 5 只，既满足指数样本扩充，也保持纯度：
  - `002428 云南锗业`
  - `600497 驰宏锌锗`
  - `600111 北方稀土`
  - `300748 金力永磁`
  - `600392 盛和资源`
- 不修改模板、不新增接口、不新增数据库结构；本次属于纯 catalog 数据扩容。

## Proposed Changes
### 1. 在 `a_share_matches_catalog.py` 中新增主题视觉与组装入口
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 在 `_THEME_ACCENTS` 新增 `AI稀有金属 / 关键矿物 / 上游资源` 的配色。
  - 颜色沿用当前关键矿物主题的紫色族，但做轻微区分，建议：
    - `accent`: `#a855f7`
    - `accent_soft`: `rgba(168, 85, 247, 0.12)`
    - `accent_line`: `rgba(168, 85, 247, 0.28)`
  - 在 `_THEMES` 中新增 `_theme("AI稀有金属 / 关键矿物 / 上游资源", [...])`。
- 原因：
  - 主题页和主题指数都靠 `_theme(...)` 自动派生，无需新基础设施。

### 2. 在 `a_share_matches_catalog.py` 中补齐 `MP` 项目股研究元数据
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 在 `_PROJECT_STOCK_REASON_DATA` 增加 `MP`：
    - 口径强调它不是普通稀土矿股，而是“稀土分离 + NdPr + 磁材一体化”更接近真实稀缺层。
    - 推荐理由要显式提到 `physical AI`、`机器人电机`、`高性能 NdFeB`。
  - 在 `_PROJECT_SOURCE_VALIDATIONS` 增加 `MP`：
    - 采用 2 条强来源，优先使用：
      - `MP Materials Reports Fourth Quarter and Full Year 2025 Results`
      - `MP Materials Reports Third Quarter 2025 Results`
    - 摘要聚焦：
      - `NdPr oxide` 放量
      - `heavy rare earth separation`
      - `commercial-scale NdFeB magnets`
      - `physical AI` / 战略 OEM 协议
  - 在 `_PROJECT_SELECTION_METRICS` 增加 `MP`：
    - `selection_reason.summary` 必须明确它卡的是 `NdPr / 稀土分离 / 永磁`，不是泛资源行情。
    - `selection_reason.fit_basis` 必须明确 AI 需求如何传导到机器人电机和高性能磁材。
    - `scarcity_view` 强调 `稀土分离 + 重稀土 + 磁材链认证` 的难复制性。
    - `capacity_view` 强调重稀土分离线与磁体产能爬坡。
    - `pricing_view` 强调 NdPr 与高性能磁材在紧平衡时更容易承接议价。
    - `segment_market_view` 口径落在 `NdPr / high-performance NdFeB / magnetics`。

### 3. 在 `a_share_matches_tweet_notes.py` 中补齐 `MP` 的 note
- 文件：`web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
- 具体改动：
  - 新增 `_NOTES["MP"] = _note(...)`。
  - 内容结构与现有项目股一致，至少补齐：
    - `overview_title`
    - `overview_summary`
    - `why_serenity_likes_it`
    - `industry_chain.nodes`
    - `stage_view`
    - `market_cap_view`
    - `timeline_sections`
  - 产业链节点明确拆成：
    - 稀土矿 / concentrate
    - 分离与 NdPr oxide
    - 金属 / 合金 / NdFeB magnets
    - 机器人电机 / physical AI / 高端工业
- 原因：
  - 这是当前测试链路对每个新增项目股的硬依赖。

### 4. 在 `a_share_matches_catalog.py` 中补齐新增 A 股映射股元数据
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 在 `_A_SHARE_SOURCE_VALIDATIONS` 新增：
    - `300748 金力永磁`
    - `600497 驰宏锌锗`
  - 在 `_MATCH_SELECTION_METRICS` 新增：
    - `300748`
    - `600497`
- 口径要求：
  - `300748 金力永磁`
    - `selection_reason.summary` 必须包含 `高性能钕铁硼`
    - `selection_reason.fit_basis` 必须包含 `人形机器人`
    - 来源优先使用：
      - 公司调研 / 投资者关系记录，证明具身机器人电机转子和小批量交付
      - 公司年报 / 经营数据，证明高性能磁材产能与放量
  - `600497 驰宏锌锗`
    - 角色定位为 `锗深加工 / 高纯四氯化锗 / 锗材料补充映射`
    - 来源优先使用：
      - 公司官网产品页中的 `高纯四氯化锗`
      - 年报或公开资料中对锗深加工业务定位的披露
    - 该股只作为 `AXTI` 的候选映射和新主题扩展样本，不抬升为主映射。

### 5. 调整复用标的的全局文案，确保新老主题断言同时成立
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 更新 `002428` 在 `_MATCH_SELECTION_METRICS` 中的 `selection_reason.summary`，让它同时覆盖：
    - 旧测试要求的 `批量供货`
    - 新测试要求的 `光纤级四氯化锗`
  - 推荐写法方向：
    - 总结句同时提到“控股子公司光纤级四氯化锗销量同比上涨”和“磷化铟晶片已批量供货并推进扩产”。
  - 保留现有 `pricing_view.detail` 中的 `价格有所上涨` 与 `capacity_view.detail` 中的 `18个月`，避免破坏旧测试。
  - `600111` 尽量复用现有内容，不为新主题单独改写，避免引入不必要回归。
- 原因：
  - 这些字段是按 `code` 全局复用，必须兼容所有主题。

### 6. 在 `_THEME_RELATED_STOCKS` 中新增新主题的扩展股票
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 增加键 `AI稀有金属 / 关键矿物 / 上游资源`。
  - 固定放入 5 只：
    - `002428 云南锗业`：`核心卡位`
    - `600497 驰宏锌锗`：`关键受益`
    - `600111 北方稀土`：`核心卡位`
    - `300748 金力永磁`：`关键受益`
    - `600392 盛和资源`：`观察候选`
  - `serenity_angle` 的写法分别聚焦：
    - `002428`：InP / 光纤级四氯化锗 / AI 光通信材料
    - `600497`：高纯四氯化锗 / 锗深加工补充
    - `600111`：稀土分离 / NdPr
    - `300748`：高性能钕铁硼 / 机器人电机转子
    - `600392`：资源+加工一体化，作为次级补充
- 原因：
  - 新主题必须有 `theme_related_stocks`，同时这些股票会进入主题指数样本池。

### 7. 在 `_THEMES` 中新增新主题的精确组装内容
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 具体改动：
  - 新主题固定紧跟在 `关键矿物 / 稀土 / 战略材料` 之后，`机器人 / 具身智能 / 核心部件` 之前，便于主题导航保持产业连续性。
  - 主题内项目股固定如下：
    - `AXTI`
      - `main_matches`
        - `002428 云南锗业`
      - `candidate_matches`
        - `600497 驰宏锌锗`
    - `MP`
      - `main_matches`
        - `600111 北方稀土`
        - `300748 金力永磁`
      - `candidate_matches`
        - `600392 盛和资源`
  - 评分建议：
    - `002428`: `16`
    - `600497`: `12`
    - `600111`: `17`
    - `300748`: `16`
    - `600392`: `13`
  - 评分逻辑：
    - 主映射优先给 `16-17`
    - 候选映射放在 `12-13`
    - 保持与当前仓库风格一致，不做极端高分
- 原因：
  - 这套配置已经满足测试要求、用户偏好和“宁缺毋滥”的主题纯度约束。

### 8. 更新目录测试，但不额外扩写低价值测试
- 文件：`test/test_a_share_matches_catalog.py`
- 现状：
  - 新主题相关的关键断言已经先写入，不需要再次扩一批重复性测试。
- 执行时只需要确保已有测试被实现满足：
  - `theme_count == 13`
  - 新主题标题存在
  - 新主题项目股包含 `AXTI`、`MP`
  - 新主题映射股包含 `002428`、`600111`、`300748`
  - `002428` 文案同时满足旧主题和新主题断言
  - `300748` 的文案满足 `高性能钕铁硼` 和 `人形机器人`

### 9. 回归详情页，但默认不修改 `test/test_a_share_stock_analysis.py`
- 文件：`test/test_a_share_stock_analysis.py`
- 做法：
  - 先跑现有回归，不预设需要改测试。
  - 如果因为新增 `MP` note 或 catalog 字段联动出现 detail payload 缺字段，再做最小修补。
- 原因：
  - 当前详情页是 catalog 反查链路，理论上新主题只要数据完整就能自动兼容。

## Verification Steps
1. 目录结构回归
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_matches_catalog.py -q`
   - 重点看：
     - `theme_count` 从 12 变 13
     - 新主题标题存在
     - `AXTI` / `MP` / `002428` / `600111` / `300748` 断言通过
     - `MP` 不再触发 tweet note 缺失
2. 详情页兼容回归
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_stock_analysis.py -q`
3. 定点诊断检查
   - `GetDiagnostics` 检查：
     - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
     - `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
4. 手工验收
   - 打开 `a_share_matches` 页面，确认：
     - 新主题显示在主题导航中
     - 新主题有 2 个项目股、若干映射股、若干扩展股
     - 自动生成新的主题指数卡片
     - `MP` 和 `AXTI` 详情入口都可点击
     - `300748`、`002428` 的详情字段完整，不出现空白块

## Out Of Scope
- 不修改原有 `关键矿物 / 稀土 / 战略材料` 的主题结构，只允许在全局复用指标上做兼容性补强。
- 不引入第三个或第四个外部锚点股。
- 不扩展成泛有色 / 泛资源主题。
- 不新增模板、接口、数据库表或缓存逻辑。
