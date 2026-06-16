# 全主题 Serenity 深度投研版实施计划

## Summary
- 目标：把当前已经在 `a_share_matches` 中形成的 Serenity 研究方法沉淀为统一执行方法，并将这套方法完整推广到现有 `12` 个主题，做到“每个主题都有深度投研版的结构化研究字段、来源认证、详情页同步、可回归测试”。
- 本计划同时承担两件事：
  - 方法论总结：把当前已经跑通的“稀缺层优先、海外+国内双验证、价格传导判断、失败条件约束”的做法固化下来。
  - 全主题落地：不只补默认值，而是把所有主题都至少做一轮接近当前光模块 / 光子材料 / AI互连三条线的深度研究版数据。
- 成功标准：
  - `a_share_matches_catalog.py` 中 `12` 个主题的 `project_stocks`、`main_matches`、`candidate_matches` 都有非泛化、非占位的研究字段。
  - 至少每个主题都新增一组“主题级深研断言”，测试能防止文案回退成泛描述。
  - `a_share_stock_analysis.py` 现有 `_find_selection_metrics()` 不改接口即可继续同步详情页。
  - 不新增前端 schema；优先复用现有 `selection_reason / scarcity_view / capacity_view / pricing_view / market_cap_research / segment_market_view / source_validation`。

## Current State Analysis
- 当前主数据文件是 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)。
  - 已有 `12` 个主题：
    - `光模块 / CPO / 光子器件`
    - `光子材料 / 衬底 / 外延 / SOI`
    - `AI互连 / 连接芯片 / AEC`
    - `存储 / SSD / Memory Cycle`
    - `Neocloud / 算力租赁 / GPU供给`
    - `晶圆代工 / Specialty Foundry`
    - `先进封装 / HBM / 玻璃基板`
    - `商业航天`
    - `电力 / 电网 / Power Bottleneck`
    - `关键矿物 / 战略材料`
    - `机器人 / 具身智能 / 核心部件`
    - `量子计算 / 精密制造 / 上游设备`
  - 已有统一结构化字段 helper：
    - `_selection_reason()`
    - `_scarcity_view()`
    - `_capacity_view()`
    - `_pricing_view()`
    - `_market_cap_research()`
    - `_segment_market_view()`
  - 已有 `source_validation` 体系，且 `stock / match / related_stock` 都能挂来源。
- 当前详情页同步逻辑已经具备，入口在 [a_share_stock_analysis.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_stock_analysis.py#L130-L193)。
  - `_find_selection_metrics()` 已经能从 catalog 读取结构化研究字段。
  - `_default_selection_metrics()` 与 `_merge_selection_metrics()` 已经提供兼容默认值。
  - 这意味着“全主题深研”的主战场是 catalog 数据与测试，不是详情路由接口改造。
- 当前测试主入口是 [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py)。
  - 已验证所有主题的字段结构完整性。
  - 已对 `光模块 / 光子器件`、`光子材料` 等少数主题写了深度断言。
  - 剩余 `9` 个主题还没有“主题级深研回归断言”，因此即使字段存在，也无法防止退化成泛描述。
- 当前研究深度分布不均：
  - 已完成较深的主题：`光模块 / CPO / 光子器件`、`光子材料 / 衬底 / 外延 / SOI`、`AI互连 / 连接芯片 / AEC`。
  - 其余主题多为“有统一字段 + 有项目映射 + 局部 source_validation”，但还未系统完成“海外+国内+价格传导+失败条件”的深度投研版重做。

## 方法论总结
### 统一研究框架
- 每个主题、每个候选必须先回答“产业链哪一层最稀缺”，不是先看公司热度。
- 研究顺序固定为：
  - `System Change`：这条主题主线为什么现在成立，真正的系统变化是什么。
  - `Scarce Layer`：链条上最卡的是哪一层，项目股站在哪一层。
  - `Overseas Validation`：先找海外锚点公司/官方/权威媒体确认该层是否真实存在瓶颈。
  - `Domestic Validation`：再找 A 股公司年报、业绩说明会、互动易、公告或权威媒体做国内验证。
  - `Price Transmission`：判断利润改善来自涨价、结构升级、验证放量，还是仅仅来自景气跟涨。
  - `Failure Conditions`：明确什么情况下这条映射会失效或降级为观察。
- 文案表达规则固定为：
  - `selection_reason.summary`：一句话说明“为什么符合”。
  - `selection_reason.fit_basis`：说明它卡在哪层、为什么不是普通受益股。
  - `scarcity_view`：说明稀缺性来源，不允许只写“有壁垒”。
  - `capacity_view`：说明扩产难来自工艺、认证、良率、客户导入还是资本开支。
  - `pricing_view`：必须区分 `已涨价 / 有涨价基础 / 结构升级 / 验证期 / 价格传导弱`，不能偷换成“看好前景”。
  - `segment_market_view`：优先给出“数十亿美元 / 百亿美元 / xx亿元”级别的环节口径，并说明份额是早期、低个位数、中个位数还是平台级。
- 证据优先级固定为：
  - 第一优先：公司年报、业绩说明会、投资者关系记录、官方新闻稿、交易所公告。
  - 第二优先：权威行业媒体、主流卖方框架、行业机构数据。
  - 第三优先：聚合站摘要只能辅助定位，不能单独作为最终定量依据。

### 统一执行规则
- 每个主题都按 TDD 执行：
  - 先给该主题加“会失败的深研断言”。
  - 跑单测确认失败。
  - 最小化改 catalog 数据。
  - 回跑主题测试与详情页测试。
- 每个主题至少要有一组不可轻易回退的深断言，避免重新变回“方向相关、待验证、补涨映射”。
- 优先改数据，不新增页面功能；当前页面和详情同步结构已够用。

## Assumptions & Decisions
- 这轮的核心产物是“计划文档 + catalog 深研数据 + 回归测试”，不是新的页面功能。
- 本轮不新增字段 schema；继续沿用当前已稳定的结构化字段和详情页读取逻辑。
- `theme_related_stocks` 不要求全部做到与 `main_matches` 同等深度，但至少要保证来源认证与角色定位不失真。
- 全主题执行时采用“分波次深研”，但目标是全部 `12` 个主题都完成，不是只完成第一批。
- 所有定量表述都遵循“有证据才写，无证据用区间/层级文本，不造精确数”。
- 对于价格传导难以证实的主题，允许明确写成 `结构升级`、`验证期` 或 `价格传导弱`，但不能留成空泛 `待验证`，除非确实没有任何足够公开信息。

## Proposed Changes
### 1. 把本计划作为方法论总文档
- 修改文件：本计划文件本身  
  [2026-06-16-all-themes-serenity-method-and-rollout-plan.md](file:///Users/jiming/Documents/trae/chanlun-pro/.trae/documents/2026-06-16-all-themes-serenity-method-and-rollout-plan.md)
- 变更内容：
  - 固化 Serenity 深研方法、证据优先级、表达规则、分波次策略。
  - 后续执行时直接以本计划为准，不再在代码里重复写长篇方法注释。

### 2. 按主题补全 `a_share_matches_catalog.py`
- 修改文件：  
  [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)
- 变更内容：
  - 对剩余 `9` 个未系统深研主题，逐个重写：
    - `project_stocks` 的研究文案
    - `main_matches`
    - `candidate_matches`
    - 必要时同步该主题的 `theme_related_stocks`
  - 研究字段必须至少覆盖：
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
  - 对已有泛化文案做去占位处理，例如：
    - “延伸映射”
    - “待验证”
    - “主题纯度一般”
    - “价格弹性取决于主题外溢”
    - “更像补涨”
    - 这些只能作为最终判断的一部分，不能再是主句。
- 为什么需要改：
  - 当前结构已经够用，真正的缺口是主题深度不均衡。
  - 继续在 `catalog` 里补强，是最少改动、最大收益的路径。

### 3. 只在必要时补 `source_validation` 索引
- 修改文件：  
  [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py)
- 变更内容：
  - 若某个主题的项目股或 A 股映射还没有足够强的 `_A_SHARE_SOURCE_VALIDATIONS` / `_PROJECT_SOURCE_VALIDATIONS`，在同文件中补齐。
  - 保持每个被深研的核心条目至少有两条可靠来源。
- 为什么需要改：
  - 计划目标是“全主题深研版”，不能只升级文案而没有来源认证支撑。

### 4. 扩展全主题回归测试
- 修改文件：  
  [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py)
- 变更内容：
  - 在现有 `test_optical_chain_selection_metrics_include_deep_research_fields()` 模式基础上，新增剩余主题的分组断言。
  - 每个主题至少新增一个测试分段，断言该主题中的代表性项目股与 A 股映射出现“主题专属、不可替换”的证据性关键词。
  - 每个主题的断言重点：
    - `存储 / SSD / Memory Cycle`：价格修复、库存/资本开支、NAND/SSD 周期验证。
    - `Neocloud / 算力租赁 / GPU供给`：供给缺口、GPU 获取能力、平台交付与电力/机柜约束。
    - `晶圆代工 / Specialty Foundry`：specialty foundry、photonics/模拟/功率工艺、客户验证。
    - `先进封装 / HBM / 玻璃基板`：封装瓶颈、HBM/玻璃基板路线、设备与材料卡点。
    - `商业航天`：发射频次、系统级能力、关键部件/材料映射。
    - `电力 / 电网 / Power Bottleneck`：AI 用电约束、电网 capex、输配电链条与价格传导。
    - `关键矿物 / 战略材料`：战略材料稀缺、供给安全、海外与国内验证。
    - `机器人 / 具身智能 / 核心部件`：感知/执行/结构的 choke point，而不是泛机器人。
    - `量子计算 / 精密制造 / 上游设备`：设备前段、激光/真空/精密制造，而不是泛量子概念。
- 为什么需要改：
  - 没有主题级深研断言，就无法防止全主题改完后被后续泛化回退。

### 5. 验证详情页同步不需要新接口
- 修改文件：  
  [test_a_share_stock_analysis.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_stock_analysis.py)
- 变更内容：
  - 给每个剩余主题至少选一只代表股，验证 `_find_selection_metrics()` 仍能返回完整结构化字段。
  - 不改 [a_share_stock_analysis.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_stock_analysis.py#L130-L193) 的接口，只通过测试保证 catalog 增强后详情仍同步。
- 为什么需要改：
  - 用户已经在详情页路径上使用这些字段，计划必须保证“全主题深研”不会破坏同步。

## 分波次执行方案
### Wave 1：补齐 AI 基础设施剩余主线
- 主题：
  - `存储 / SSD / Memory Cycle`
  - `Neocloud / 算力租赁 / GPU供给`
  - `晶圆代工 / Specialty Foundry`
  - `先进封装 / HBM / 玻璃基板`
  - `电力 / 电网 / Power Bottleneck`
- 原因：
  - 这些主题与当前已做深的 `光模块 / 光子材料 / AI互连` 逻辑最相邻，方法迁移成本最低。
  - 公开资料更容易落到“真实瓶颈层、capex、价格与结构升级”。

### Wave 2：补齐资源与硬件系统主题
- 主题：
  - `商业航天`
  - `关键矿物 / 战略材料`
- 原因：
  - 这两条线更依赖“资源 / 系统能力 / 供给安全”的 Serenity 式判断，需要单独写清楚与 AI 链不同的方法差异。

### Wave 3：补齐前瞻技术主题
- 主题：
  - `机器人 / 具身智能 / 核心部件`
  - `量子计算 / 精密制造 / 上游设备`
- 原因：
  - 这两条线容易退化成概念股叙事，必须用“上游设备、感知/执行 choke point、商业化验证”重新收紧。

## 分文件实施说明
### `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- 主要工作：
  - 深化剩余 `9` 个主题的项目股与 A 股映射文案。
  - 补强对应 `source_validation` 条目。
  - 清理泛化措辞，统一深研表达层级。
- 不做的事：
  - 不改 helper schema。
  - 不改页面模板结构。

### `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
- 主要工作：
  - 本轮原则上不改实现。
  - 只作为同步消费端验证入口。

### `test/test_a_share_matches_catalog.py`
- 主要工作：
  - 为剩余 `9` 个主题补深研断言。
  - 保证每个主题至少有一组不可替代的关键词断言。

### `test/test_a_share_stock_analysis.py`
- 主要工作：
  - 验证 catalog 新增深研内容能被详情页逻辑读取。

## Acceptance Criteria
- 所有 `12` 个主题都至少有一组代表性的深研断言。
- `a_share_matches_catalog.py` 中所有核心主题条目都不再以泛化占位描述为主。
- 任意主题的代表股打开详情页时，都能看到与主页一致的结构化研究字段。
- `source_validation` 对所有深研核心条目维持有效，且至少有两条可靠来源。

## Verification Steps
- 先跑主题回归：
  - `pytest test/test_a_share_matches_catalog.py -q`
- 再跑详情同步：
  - `pytest test/test_a_share_stock_analysis.py -q`
- 若执行中新增了更细的主题测试块，按主题单独回放：
  - `pytest test/test_a_share_matches_catalog.py -k <theme_keyword> -vv`
- 人工校验：
  - 随机抽 `3-5` 个非光通信主题，确认卡片文案能直接回答：
    - 为什么符合
    - 稀缺性来自哪里
    - 扩产难在哪里
    - 利润来自涨价、结构升级还是验证期
    - 环节市场多大
    - 公司份额处于什么层级

## 执行备注
- 这份计划即为“上述方法总结”的正式沉淀，不再额外新建方法文档。
- 实施时严格遵循：
  - 先测试失败
  - 再最小改数据
  - 最后回归详情同步
- 优先做“全主题完成一轮深研”，之后若用户继续要求，再进入“二轮加深与更严的海外/国内交叉验证”。
