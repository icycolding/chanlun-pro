## Summary
- 目标：按 Serenity 的方法，在 `a_share_matches` 体系中新增一个独立主题，把“创新药股票推荐”做成可落地、可回归、可出详情页的系统能力，而不是只给一份临时清单。
- 已锁定的产品决策：
  - 做成 `a_share_matches` 里的 `新增独立主题`，不是单次推荐文案。
  - 继续沿用当前系统结构：`海外/H股锚点股 -> A股 main_matches / candidate_matches -> theme_related_stocks -> 主题指数`。
  - 主题范围选 `广义创新药`，但执行风格坚持 `宁缺毋滥`。
  - A 股映射边界允许 `创新药企 + CXO/CDMO`，不扩到设备/原料大而全。
  - Serenity 排序口径以 `BD / 授权出海优先`，其次看平台能力、商业化和临床兑现。
  - 对当前未完成的 `AI稀有金属 / 关键矿物 / 上游资源` 主题，用户明确要求 `再新增独立主题`，不替换、不覆盖。
- 本计划的最终落点是：在不改前端 schema 的前提下，新增一个完整的创新药 Serenity 主题，并把推荐逻辑、来源认证、详情页同步和回归测试全部接上。

## Current State Analysis
- 当前 Serenity 主题系统主数据集中在 `web/chanlun_chart/cl_app/a_share_matches_catalog.py`。
  - 主题通过 `_theme(title, project_stocks)` 统一组装。
  - `project_stocks`、`main_matches`、`candidate_matches`、`theme_related_stocks` 都已经有稳定字段结构。
  - 新主题只要进 `_THEMES`，页面、详情页、主题指数都会自动接上。
- 当前系统里还没有医药 / 创新药相关主题。
  - 本地搜索 `web/chanlun_chart/cl_app` 与 `test` 后，没有现成的创新药主题、项目股、映射股或相关测试。
  - 这说明本次不是“改已有主题”，而是从 0 到 1 新增一个完整主题。
- 当前主题集成存在一个必须纳入计划的上下文约束：
  - 之前用户已经要求新增 `AI稀有金属 / 关键矿物 / 上游资源` 主题。
  - `test/test_a_share_matches_catalog.py` 已经朝“新增 1 个主题”的方向修改了部分断言，但 `catalog` 本体还没完全补齐。
  - 因此创新药若再新增一个独立主题，执行顺序必须写清楚，否则 `theme_count`、`project_stock_count` 和代表性断言会互相冲突。
- 当前隐藏依赖与实现规律已经确认：
  - 新增 `project_stock` 时，不只改 `a_share_matches_catalog.py`，还必须补 `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`，否则 `test_all_project_stocks_have_rich_tweet_note_content` 会失败。
  - A 股深研字段是按 `code` 全局复用的：
    - `_A_SHARE_SOURCE_VALIDATIONS`
    - `_MATCH_SELECTION_METRICS`
  - 项目股深研字段按 `symbol` 维护：
    - `_PROJECT_STOCK_REASON_DATA`
    - `_PROJECT_SOURCE_VALIDATIONS`
    - `_PROJECT_SELECTION_METRICS`
- 当前仓库的实际主题数仍是 `12`，但测试里已经把上一个新增主题预期推到了 `13`。
  - 因此本次创新药主题的最终正确目标，不应是 `13`，而应是：
    - 先补齐 AI 稀有金属主题到 `13`
    - 再新增创新药主题到 `14`

## Serenity Scope
- 这次创新药主题不是做“医药大全”，而是只保留三类最符合 Serenity 方法的层级：
  - `全球化商业化药企`
    - 不是只看故事，而是已经跨过商业化 / 全球化门槛，证明研发平台和执行体系能兑现。
  - `BD / 授权出海驱动的中国创新药平台`
    - 不是单纯看一期二期数据，而是看是否真的被 MNC 或全球资本高价验证。
  - `创新药卖铲子：CXO / CDMO / CRDMO`
    - 不是泛外包，而是贴近 ADC / 多肽 / 寡核苷酸 / 生物药这类高景气分子形式的关键承接层。
- 主题排序规则固定为：
  - 先排 `谁最接近被全球定价验证`
  - 再排 `谁真正卡在创新药研发、放量、生产和出海链路`
  - 最后才排 `谁有弹性`
- 主题名称固定为：
  - `创新药 / BD出海 / CXO服务`

## Assumptions & Decisions
- 本轮创新药主题采用 `3 个外部/H股锚点股`，不扩到 4-5 个，保持高纯度。
- 主题内固定使用以下 3 个锚点股：
  1. `ONC` `BeOne Medicines`
     - 角色：全球化商业化肿瘤药企锚点
     - 选择原因：已经从中国 Biotech 走到全球肿瘤 Biopharma，兼具研发、临床、商业化和制造验证
  2. `9926` `康方生物-B`
     - 角色：BD / 授权出海驱动的双抗平台锚点
     - 选择原因：最贴近“被海外高价验证”的中国创新药逻辑
  3. `2269` `药明生物`
     - 角色：创新药卖铲子的大分子 / ADC CDMO 锚点
     - 选择原因：补齐用户明确要求的 `药企 + CXO/CDMO` 边界，并且更贴近生物药 / ADC 的产业承接层
- 对应 A 股映射固定为以下结构：
  - `ONC -> BeOne Medicines`
    - `main_matches`
      - `688235 百济神州`
    - `candidate_matches`
      - `688331 荣昌生物`
  - `9926 -> 康方生物-B`
    - `main_matches`
      - `688506 百利天恒`
    - `candidate_matches`
      - `688062 迈威生物`
  - `2269 -> 药明生物`
    - `main_matches`
      - `603259 药明康德`
    - `candidate_matches`
      - `300759 康龙化成`
- 新主题的 `theme_related_stocks` 固定保留 6 只，用于扩展主题横截面和主题指数样本：
  - `688235 百济神州`
  - `688506 百利天恒`
  - `603259 药明康德`
  - `688331 荣昌生物`
  - `688062 迈威生物`
  - `300759 康龙化成`
- 不在本主题中纳入设备、原料药、上游试剂或泛医药流通股。
- 不改当前模板结构，不新增新的前端字段 schema。

## Proposed Changes
### 1. 先处理主题计数基线，再新增创新药主题
- 文件：
  - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - `test/test_a_share_matches_catalog.py`
- 做法：
  - 先承认并保留上一个未完成需求：`AI稀有金属 / 关键矿物 / 上游资源` 仍然是一个独立主题。
  - 执行创新药主题时，目标状态是：
    - `AI稀有金属` 主题落地后，主题数到 `13`
    - `创新药 / BD出海 / CXO服务` 新增后，主题数到 `14`
  - 对应测试最终要改到：
    - `theme_count == 14`
    - `theme_titles` 同时包含：
      - `AI稀有金属 / 关键矿物 / 上游资源`
      - `创新药 / BD出海 / CXO服务`
- 原因：
  - 用户明确要求“再新增独立主题”，不是替换前一个未完成主题。

### 2. 在 `a_share_matches_catalog.py` 中新增创新药主题 accent
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 在 `_THEME_ACCENTS` 中增加 `创新药 / BD出海 / CXO服务`。
  - 颜色建议使用偏冷的医疗蓝绿系，与现有半导体/资源/机器人主题区分：
    - `accent`: `#14b8a6`
    - `accent_soft`: `rgba(20, 184, 166, 0.12)`
    - `accent_line`: `rgba(20, 184, 166, 0.28)`
- 原因：
  - 主题导航和卡片要有稳定视觉识别，但不需要新增样式逻辑。

### 3. 在 `a_share_matches_catalog.py` 中补齐 3 个项目股元数据
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 需要新增到以下表：
  - `_PROJECT_STOCK_REASON_DATA`
  - `_PROJECT_SOURCE_VALIDATIONS`
  - `_PROJECT_SELECTION_METRICS`
- 固定新增对象与口径：
  - `ONC`
    - `serenity_reason_summary`：强调“全球肿瘤商业化 + 临床开发 superhighway + 制造能力”
    - `selection_reason`：强调它不只是中国药企映射，而是已经被全球收入和利润验证的平台型肿瘤药企
    - `source_validation`：至少 2 条来源，优先使用
      - `BeOne Medicines 2025 Full Year Results`
      - `BeOne Medicines Q1 2026 Results`
  - `9926`
    - `serenity_reason_summary`：强调“PD-1/VEGF 双抗 + Summit 授权出海 + 中国创新药全球化定价”
    - `selection_reason`：强调真正卡点是 `BD/授权出海`，而不是单纯国内卖药
    - `source_validation`：至少 2 条来源，优先使用
      - 康方年报/IR材料
      - Summit/海外审批或受理进展的公开材料
  - `2269`
    - `serenity_reason_summary`：强调“生物药/ADC CDMO 平台 + 后端生产转化 + 订单可见性”
    - `selection_reason`：强调它卡的是创新药后端放大生产，不是泛 CRO
    - `source_validation`：至少 2 条来源，优先使用
      - 药明生物年报/业绩公告
      - 公司公开订单/项目进展或权威行业来源

### 4. 在 `a_share_matches_tweet_notes.py` 中为 3 个项目股补 note
- 文件：`web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
- 做法：
  - 新增 `_NOTES["ONC"]`
  - 新增 `_NOTES["9926"]`
  - 新增 `_NOTES["2269"]`
- 每个 note 都必须补齐：
  - `overview_title`
  - `overview_summary`
  - `why_serenity_likes_it`
  - `industry_chain`
  - `stage_view`
  - `market_cap_view`
  - `timeline_sections`
- 产业链节点写法固定：
  - `ONC`
    - 靶点/分子研发
    - 全球临床开发
    - 商业化放量
    - 制造与准入
  - `9926`
    - 双抗平台
    - 海外 BD / Licensing
    - 注册推进
    - 商业化兑现
  - `2269`
    - 分子进入临床
    - 工艺开发
    - PPQ / 商业化生产
    - 大分子 / ADC 产能与交付
- 原因：
  - 这是所有新增项目股通过结构测试的前提。

### 5. 在 `a_share_matches_catalog.py` 中补齐 6 只 A 股映射股的认证与深研字段
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 需要新增到以下表：
  - `_A_SHARE_SOURCE_VALIDATIONS`
  - `_MATCH_SELECTION_METRICS`
- 固定新增对象：
  - `688235 百济神州`
  - `688331 荣昌生物`
  - `688506 百利天恒`
  - `688062 迈威生物`
  - `603259 药明康德`
  - `300759 康龙化成`
- 口径固定：
  - `688235 百济神州`
    - 关键词：`全球化商业化`、`BTK`、`收入兑现`
    - 作为 `ONC` 最直接主映射
  - `688331 荣昌生物`
    - 关键词：`ADC`、`出海授权`、`差异化肿瘤/自免`
    - 作为 `ONC` 的候选映射，同时可出现在 related
  - `688506 百利天恒`
    - 关键词：`ADC`、`BMS`、`首付款/里程碑`、`全球临床`
    - 作为 `9926` 主映射
  - `688062 迈威生物`
    - 关键词：`双抗/平台型`、`出海推进`
    - 作为 `9926` 候选映射
  - `603259 药明康德`
    - 关键词：`CRDMO`、`TIDES`、`在手订单`
    - 作为 `2269` 主映射
  - `300759 康龙化成`
    - 关键词：`一体化医药研发服务`、`临床前到开发`
    - 作为 `2269` 候选映射
- 字段要求：
  - 每只股票必须补齐
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
    - `source_validation`
  - 每只核心对象至少 `2` 条来源

### 6. 在 `_THEME_RELATED_STOCKS` 中新增创新药主题相关股
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 新增键：`创新药 / BD出海 / CXO服务`
  - 固定放入以下 related stocks：
    - `688235 百济神州`
    - `688506 百利天恒`
    - `603259 药明康德`
    - `688331 荣昌生物`
    - `688062 迈威生物`
    - `300759 康龙化成`
- `serenity_angle` 固定写法方向：
  - `688235`：中国创新药少数已被全球商业化验证的平台
  - `688506`：最接近“BD 出海 + ADC 高定价验证”的 A 股样本
  - `603259`：创新药放量背后的 CRDMO 卖铲子
  - `688331`：差异化 ADC 出海与全球授权的观察样本
  - `688062`：平台型双抗/生物药候选
  - `300759`：CXO 扩散层补充映射

### 7. 在 `_THEMES` 中新增完整创新药主题
- 文件：`web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 做法：
  - 新增：
    - `_theme("创新药 / BD出海 / CXO服务", [...])`
  - 固定项目股配置：
    1. `_stock(symbol="ONC", ...)`
       - `main_matches`:
         - `688235 百济神州`
       - `candidate_matches`:
         - `688331 荣昌生物`
    2. `_stock(symbol="9926", ...)`
       - `exchange="HKEX"`
       - `market="Hong Kong"`
       - `main_matches`:
         - `688506 百利天恒`
       - `candidate_matches`:
         - `688062 迈威生物`
    3. `_stock(symbol="2269", ...)`
       - `exchange="HKEX"`
       - `market="Hong Kong"`
       - `main_matches`:
         - `603259 药明康德`
       - `candidate_matches`:
         - `300759 康龙化成`
- 建议评分固定为：
  - `688235`: `18`
  - `688331`: `14`
  - `688506`: `18`
  - `688062`: `13`
  - `603259`: `17`
  - `300759`: `13`
- 排序逻辑：
  - 被全球商业化或高额 BD 定价验证的主映射给 `17-18`
  - 仍处平台成长期或更偏扩散映射的候选给 `13-14`

### 8. 扩展 `test/test_a_share_matches_catalog.py` 的主题结构与深研断言
- 文件：`test/test_a_share_matches_catalog.py`
- 做法：
  - 更新总量断言：
    - `theme_count == 14`
  - 更新标题断言：
    - 增加 `创新药 / BD出海 / CXO服务`
  - 更新项目股数量断言：
    - 当前为 `27`
    - 若同时补齐前一个 `AI稀有金属` 两只项目股，再新增创新药 `3` 只，最终固定为 `32`
  - 增加创新药主题结构断言：
    - `project_stocks` 至少包含 `ONC`、`9926`、`2269`
    - A 股映射至少包含 `688235`、`688506`、`603259`
  - 增加创新药主题深研断言：
    - `688235` 文案含 `全球化` 或 `商业化`
    - `688506` 文案含 `ADC` 和 `BMS`
    - `603259` 文案含 `CRDMO` 和 `TIDES` 或 `在手订单`
  - 更新 `representative_pairs`：
    - 新增 `("创新药 / BD出海 / CXO服务", "ONC", "688235")`
- 原因：
  - 没有主题级深断言，后续最容易退化成“泛医药推荐”。

### 9. 回归 `test/test_a_share_stock_analysis.py`，但优先不新增专用测试
- 文件：`test/test_a_share_stock_analysis.py`
- 做法：
  - 先跑现有回归，确认新增主题的 `project` / `match` 详情能读出结构化字段。
  - 如果 detail payload 因为新 symbol 缺 note 或缺 selection metrics 才失败，再做最小修补。
- 原因：
  - 当前详情页逻辑已经是 catalog 的消费端，不需要新接口设计。

## Implementation Order
1. 补齐上一个已承诺但未落完的 `AI稀有金属 / 关键矿物 / 上游资源`，把分支从“测试预期 13、实际 12”恢复到一致。
2. 在创新药主题计划下新增：
   - 3 个项目股
   - 6 个 A 股映射
   - 6 个主题相关股
   - 1 个新主题
3. 更新总量与代表性测试到最终状态：
   - `theme_count == 14`
   - `project_stock_count == 32`
4. 回归结构、详情和主题页渲染。

## Verification Steps
1. 结构与主题回归
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_matches_catalog.py -q`
   - 重点检查：
     - `theme_count == 14`
     - `project_stock_count == 32`
     - 新主题标题存在
     - `ONC`、`9926`、`2269` 及其代表 A 股映射存在
2. 详情链路回归
   - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_stock_analysis.py -q`
3. 诊断检查
   - `GetDiagnostics` 检查：
     - `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
     - `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`
     - `test/test_a_share_matches_catalog.py`
4. 手工验收
   - 打开 `a_share_matches` 页面，确认：
     - 新增 `创新药 / BD出海 / CXO服务` 主题
     - 主题卡、主题指数、项目股和映射股都能显示
     - 项目股详情页能看到 Serenity 风格推荐理由和时间线
     - 主题指数样本来自创新药 A 股映射和 related stocks

## Out Of Scope
- 不新增医药专用页面或专用接口。
- 不扩成“医疗器械 / 医药流通 / 中药 / 原料药”大主题。
- 不把创新药主题改成只给一份静态推荐清单。
- 不替换或取消已承诺的 `AI稀有金属 / 关键矿物 / 上游资源` 主题。
