# 已选股票板块与市场空间增强方案 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `a_share_matches` 里已选出的项目股与映射股，统一展示“所属板块、市场空间、增长前景、公司地位、公司份额”，并在主列表与个股详情页都能看到。

**Architecture:** 复用现有 `a_share_matches_catalog.py` 的结构化研究字段模式，在 `a_share_stock_analysis.py` 中新增一组“公司所处板块与行业位置”研究视图，并通过 AI 优先的 enrichment 层自动生成摘要；主列表页显示摘要卡片，详情页显示完整字段与来源/生成状态。缺失时保留稳定的默认占位，不阻塞页面渲染。

**Tech Stack:** Flask, Jinja2, Python, 现有 `a_share_matches`/`a_share_stock_analysis` 模块, 现有 AI 分析能力 `AIAnalyse`

---

## Summary

- 当前系统已经有一套接近目标的数据基础：
  - `a_share_matches_catalog.py` 已有 `segment_market_view`，包含 `market_size_text`、`company_share_text`、`share_level`
  - `a_share_stock_analysis.py` 已能把 `selection_reason`、`market_cap_research`、`segment_market_view` 注入详情页
  - `a_share_matches.html` 主列表页已经直接展示了项目股和映射股的“环节市场规模 / 公司份额”
- 当前缺口主要在 3 点：
  - 没有统一的“所属板块 / 增长前景 / 行业地位”结构化字段
  - 这些字段还没有 AI 优先的自动生产链路
  - 主列表虽然已有部分市场空间信息，但没有把“板块归属 + 增长前景 + 地位”整合成用户一眼能读懂的摘要
- 用户偏好已锁定：
  - 展示范围：`主列表 + 详情`
  - 数据生产：`AI 生成优先`

## Current State Analysis

### 现有数据与构建链路

- `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
  - 定义项目股与映射股的结构化元数据
  - 已存在 `_segment_market_view()`，适合继续承载“市场空间 / 份额”
  - `get_a_share_match_catalog()` 输出主列表页最终数据
- `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
  - `build_stock_analysis_detail_payload()` 会聚合财务、新闻、实时行情与 catalog 研究字段
  - `_find_selection_metrics()` 目前只回传：
    - `selection_reason`
    - `scarcity_view`
    - `capacity_view`
    - `pricing_view`
    - `market_cap_research`
    - `segment_market_view`
  - 这里是新增“板块 / 增长 / 地位”研究视图的最佳聚合点
- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 项目股卡片与映射股卡片都已渲染 `segment_market_view`
  - 已有“查看个股分析”入口，适合在卡片中补“行业定位摘要”
- `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
  - 已有 `selection-metric-grid`
  - 详情页是展示完整行业上下文的自然落点
- `web/chanlun_chart/cl_app/__init__.py`
  - 已有：
    - `/a_share_matches/stock_analysis_summaries`
    - `/a_share_matches/stock-analysis/<entity_type>/<identifier>`
  - 无需新增路由，优先复用现有入口

### 当前设计缺口

- `segment_market_view` 只解决了“市场规模 / 份额”，没有覆盖：
  - 所属板块
  - 增长前景
  - 行业地位
- 现有结构偏人工策展，没有 AI 优先的自动补全层
- 主列表页的信息点偏分散，不是“一个完整的行业画像”

## Proposed Changes

### 1. 新增统一研究结构：`sector_context_view`

**目标**

- 用一套可复用的结构同时覆盖项目股与映射股：
  - 属于哪个板块
  - 该板块市场空间有多少
  - 增长前景如何
  - 公司在市场中的地位如何
  - 公司份额如何

**修改文件**

- Modify: `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- Modify: `web/chanlun_chart/cl_app/a_share_stock_analysis.py`

**设计**

- 在 `a_share_matches_catalog.py` 中新增 helper：
  - `_sector_context_view(sector_name="", sector_role="", market_size_text="", growth_outlook="", company_position_text="", company_share_text="", share_level="", evidence_note="")`
- 结构建议：

```python
{
    "sector_name": "创新药 / 双抗出海",
    "sector_role": "所属板块中的平台型药企",
    "market_size_text": "双抗 / 肿瘤创新药 / 授权出海平台可按数十亿美元到百亿美元级理解。",
    "growth_outlook": "未来 2-3 年增长更多取决于 BD 持续兑现、全球注册推进和商业化放量。",
    "company_position_text": "更接近中国创新药全球化平台中的头部样本。",
    "company_share_text": "公司份额适合按中国创新药全球化平台理解。",
    "share_level": "中高",
    "evidence_note": "优先来自财报、公司材料、权威行业数据与 AI 摘要归纳。"
}
```

- `segment_market_view` 暂时保留，避免一次性破坏现有模板与测试
- `sector_context_view` 成为新的主结构，`segment_market_view` 作为兼容字段

**为什么这样做**

- 最小化破坏现有页面和测试
- 明确区分“行业画像”与“市场空间/份额”子视图
- 后续若要接数据库或缓存，不需要再次拆 schema

### 2. 在 catalog 中补默认字段与兼容回退

**目标**

- 确保未补齐 AI/人工研究的股票仍然能正常渲染

**修改文件**

- Modify: `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

**具体做法**

- 为项目股与映射股的 `_stock()` / `_match()` 增加入参：
  - `sector_context_view: dict[str, str] | None = None`
- 若未传值：
  - 自动从 `segment_market_view` 回填：
    - `market_size_text <- segment_market_view.market_size_text`
    - `company_share_text <- segment_market_view.company_share_text`
    - `share_level <- segment_market_view.share_level`
  - 其余字段用明确占位：
    - `sector_name="板块待补充"`
    - `growth_outlook="增长前景待 AI 研究补齐"`
    - `company_position_text="行业地位待 AI 研究补齐"`

**为什么这样做**

- 先保证全量股票都能进入新 UI
- 后续只需逐步补高价值股票，不会阻塞整体上线

### 3. 增加 AI 优先的行业画像生成层

**目标**

- 对“已选股票”自动生成板块归属、市场空间、增长前景、行业地位和份额判断

**修改文件**

- Modify: `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
- Optional future source: `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`（本次先不改，除非需要复用现有推荐脉络）

**设计**

- 在 `a_share_stock_analysis.py` 新增函数：
  - `_build_sector_context_from_metrics(...)`
  - `_build_ai_sector_context(...)`
  - `_merge_sector_context(...)`
- 输入优先级：
  1. catalog 已配置的 `sector_context_view`
  2. 由现有字段拼接出的显式信息：
     - `selection_reason`
     - `market_cap_research`
     - `segment_market_view`
     - `company_name` / `display_name`
  3. 本地新闻搜索结果标题摘要
  4. 财务摘要
  5. AI 生成的补全文案

**AI 输出要求**

- 输出 JSON 或严格结构化文本，字段固定为：
  - `sector_name`
  - `sector_role`
  - `market_size_text`
  - `growth_outlook`
  - `company_position_text`
  - `company_share_text`
  - `share_level`
  - `evidence_note`
- 若 AI 失败：
  - 不报错
  - 回退到 `catalog` + 默认占位文案

**提示词原则**

- 明确要求：
  - 使用中文
  - 尽量给“细分板块”而不是泛行业
  - 市场空间使用区间或量级表达，不强造精确值
  - 行业地位和份额必须体现“不确定性”，避免伪精度

**为什么这样做**

- 符合用户的 `AI 生成优先`
- 同时保留当前 Serenity 研究骨架，避免完全依赖模型幻觉

### 4. 主列表页增加“行业画像摘要”展示

**目标**

- 用户在 `a_share_matches` 列表页上，不点详情也能直接知道：
  - 这只票属于哪个板块
  - 这个板块空间多大
  - 增长如何
  - 公司地位如何

**修改文件**

- Modify: `web/chanlun_chart/cl_app/templates/a_share_matches.html`

**具体做法**

- 在项目股卡片、主映射卡片、候选池卡片中新增一个紧凑的“行业画像”区域
- 建议字段顺序：
  - `所属板块`
  - `增长前景`
  - `行业地位`
  - `市场空间 / 公司份额`
- UI 形式：
  - 主列表只显示摘要版，每项 1 行
  - `市场空间 / 公司份额` 继续保留现有卡片样式
  - 避免再堆 6 个同样大小的卡片，改成 2 列摘要栅格，减少页面高度膨胀

**为什么这样做**

- 现有主列表已经信息很多，若继续平铺卡片会显著拉长页面
- 摘要化更适合“先看一眼再决定是否点进详情”

### 5. 详情页增加完整“行业画像”模块

**目标**

- 在 `stock-analysis` 详情页中提供完整版本，作为用户查看一只股票行业位置的标准页面

**修改文件**

- Modify: `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
- Modify: `web/chanlun_chart/cl_app/a_share_stock_analysis.py`

**具体做法**

- 在详情页新增一个独立 section，例如：
  - `行业画像`
- 推荐展示项：
  - `所属板块`
  - `板块定位`
  - `市场空间`
  - `增长前景`
  - `行业地位`
  - `公司份额`
  - `份额等级`
  - `判断依据`
- 保留现有 `selection_reason / 稀缺性 / 扩产难度 / 涨价能力 / 市值空间`
- 形成两层逻辑：
  - “为什么选它” = Serenity 研究逻辑
  - “它在行业里是什么位置” = 行业画像逻辑

**为什么这样做**

- 这正对应用户的问题，不与现有 Serenity 视角混淆
- 详情页适合承载完整解释和更长文本

### 6. 复用现有 summaries 接口，增加行业画像摘要字段

**目标**

- 保持主列表懒加载财务摘要的模式一致，不强行改成全服务端同步

**修改文件**

- Modify: `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
- Optional Modify: `web/chanlun_chart/cl_app/__init__.py`（仅在响应字段需要调整时）

**具体做法**

- `build_stock_analysis_summaries(items)` 返回值增加：
  - `sector_name`
  - `growth_outlook_short`
  - `company_position_short`
  - `market_size_short`
  - `company_share_short`
- 若模板当前直接使用 catalog 静态字段，也可先不依赖 summaries 接口
- 但详情页 payload 必须包含完整 `sector_context_view`

**为什么这样做**

- 保留现有异步汇总接口扩展性
- 后续若要对更多页面复用同一摘要，无需再从详情 payload 裁剪

### 7. 测试补齐

**目标**

- 覆盖 schema、payload、模板渲染和默认回退

**修改文件**

- Modify: `test/test_a_share_stock_analysis.py`
- Modify: `test/test_a_share_matches_catalog.py`

**新增/调整测试**

- `test_build_stock_analysis_detail_payload_includes_sector_context_for_project_and_match`
  - 断言 project / match 的 payload 都包含 `sector_context_view`
  - 断言至少有：
    - `sector_name`
    - `market_size_text`
    - `growth_outlook`
    - `company_position_text`
    - `company_share_text`
- `test_build_stock_analysis_detail_payload_falls_back_to_default_sector_context`
  - 当 catalog 未提供或 AI 失败时，仍返回默认占位
- `test_a_share_matches_catalog_contains_sector_context_for_representative_symbols`
  - 选代表性股票断言新字段存在
- `test_stock_analysis_template_renders_sector_context_block`
  - 渲染 HTML 后断言出现：
    - `所属板块`
    - `增长前景`
    - `行业地位`
    - `公司份额`

## Assumptions & Decisions

- 决策：优先增强现有 `a_share_matches` / `stock-analysis`，不新增新页面
- 决策：保留 `segment_market_view`，新增 `sector_context_view` 而不是直接替换
- 决策：AI 优先，但必须有稳定默认回退，不能因为 AI 失败导致页面缺字段
- 决策：先做“文本级结构化研究”，不引入新数据库表或后台任务
- 假设：当前 `AIAnalyse` 可用于输出受控中文摘要；若稳定性不足，后续再改为缓存或离线生成
- 假设：当前用户所说“选出来的股票”包含：
  - 项目股 `project stocks`
  - A 股映射股 `main_matches` / `candidate_matches`

## Verification Steps

### 功能验证

- 打开 `a_share_matches`：
  - 项目股卡片能看到 `所属板块 / 增长前景 / 行业地位 / 市场空间 / 公司份额`
  - 主映射与候选池卡片也能看到对应摘要
- 打开任意 `查看个股分析`：
  - 详情页出现完整 `行业画像` 模块
  - 字段不缺失，AI 失败时也有占位

### 测试验证

- 运行：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_stock_analysis.py -q`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_matches_catalog.py -q`

### 回归重点

- 不能破坏现有字段：
  - `selection_reason`
  - `market_cap_research`
  - `segment_market_view`
- 不能影响现有页面入口：
  - `/a_share_matches`
  - `/a_share_matches/stock-analysis/<entity_type>/<identifier>`
- 新字段必须同时兼容：
  - `project`
  - `match`

## Implementation Tasks

### Task 1: 定义行业画像 schema

**Files:**
- Modify: `web/chanlun_chart/cl_app/a_share_matches_catalog.py`
- Test: `test/test_a_share_matches_catalog.py`

- [ ] 新增 `_sector_context_view()` helper，并为 `_stock()` / `_match()` 增加 `sector_context_view` 入参
- [ ] 保留 `segment_market_view` 兼容逻辑
- [ ] 为默认回退值补齐统一占位文案
- [ ] 先写 catalog 测试，验证代表性股票包含 `sector_context_view`

### Task 2: 扩展 stock analysis payload

**Files:**
- Modify: `web/chanlun_chart/cl_app/a_share_stock_analysis.py`
- Test: `test/test_a_share_stock_analysis.py`

- [ ] 在 `_find_selection_metrics()` 与 `_default_selection_metrics()` 中加入 `sector_context_view`
- [ ] 新增 `_build_ai_sector_context()` 和 `_merge_sector_context()`
- [ ] 在 `build_stock_analysis_detail_payload()` 中注入完整 `sector_context_view`
- [ ] 在 `build_stock_analysis_summaries()` 中注入摘要字段
- [ ] 先写 payload 测试，再做最小实现

### Task 3: 渲染主列表摘要

**Files:**
- Modify: `web/chanlun_chart/cl_app/templates/a_share_matches.html`

- [ ] 为项目股卡片新增紧凑“行业画像”摘要区
- [ ] 为主映射与候选池卡片新增同样摘要区
- [ ] 控制样式密度，避免页面高度膨胀

### Task 4: 渲染详情页完整模块

**Files:**
- Modify: `web/chanlun_chart/cl_app/templates/a_share_match_stock_analysis.html`
- Test: `test/test_a_share_stock_analysis.py`

- [ ] 在详情页新增 `行业画像` section
- [ ] 渲染 `所属板块 / 板块定位 / 市场空间 / 增长前景 / 行业地位 / 公司份额 / 份额等级 / 判断依据`
- [ ] 补模板渲染测试

### Task 5: 回归与样本校验

**Files:**
- Modify: `test/test_a_share_matches_catalog.py`
- Modify: `test/test_a_share_stock_analysis.py`

- [ ] 选 2-4 个代表性股票做断言样本
- [ ] 跑 `catalog` 与 `stock_analysis` 两组测试
- [ ] 手工检查 `a_share_matches` 与详情页字段顺序和文案一致性
