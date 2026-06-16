# `a_share_matches` 机器人与量子计算主题扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `a_share_matches` 页面中新增“机器人”和“量子计算”两个独立主题，按 Serenity 方法保留“海外锚点股 + A股核心映射 + 候选池”的完整结构，并为新增项目股票补齐推荐理由、静态分析 note、详情页和测试。

**Architecture:** 继续沿用现有 `a_share_matches` 的静态 catalog 驱动架构，不新增页面入口或数据模型。实现重点集中在 `a_share_matches_catalog.py` 新增两段 `_theme(...)` 定义、扩展 `_PROJECT_STOCK_REASON_DATA`、补充 `a_share_matches_tweet_notes.py` 静态 notes，并更新测试断言以覆盖新增主题、项目股票和页面文案。Serenity 依据以仓库内缓存资料 `serenity-aleabitoreddit-main` 为准，不引入联网依赖。

**Tech Stack:** Flask、Jinja2、现有 `cl_app` catalog 结构、pytest、仓库内 Serenity 缓存资料

---

## Summary

- 新增两个独立主题：
  - `机器人`
  - `量子计算`
- 两个主题都采用现有统一结构：
  - 主题扩展 A 股
  - 海外项目股票
  - 每个项目股票下的 A 股核心映射
  - 每个项目股票下的 A 股候选池
- Serenity 依据固定使用仓库内缓存资料：
  - `serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/*.md`
  - `serenity-aleabitoreddit-main/serenity-aleabitoreddit/references/articles.md`
- 机器人主题采用 Serenity 已明确提到的机器人链条：
  - `VPG`、`AEVA`、`SSYS`
- 量子计算主题采用用户指定的“纯量子计算设备链”口径：
  - `INFQ`
  - `ALRIB`
- A 股映射采用用户确认的 `核心 + 候选双层` 口径：
  - 主映射尽量贴近 Serenity 的“上游瓶颈 / 精密制造 / 核心器件”逻辑
  - 候选池允许更宽的相关 A 股

## Current State Analysis

### 现有主题与接入方式

- 当前 `a_share_matches` 的主题完全由 [a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py) 中的静态 catalog 生成。
- 顶层返回结构在 [get_a_share_match_catalog](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L1744-L1758)，当前固定返回：
  - `theme_count == 10`
  - `project_stock_count == 21`
- 新增主题的实际接入点已经清楚：
  - 主题配色：[_THEME_ACCENTS](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L10-L61)
  - 项目股票推荐文案：[_PROJECT_STOCK_REASON_DATA](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L64-L170)
  - 主题扩展 A 股：[_THEME_RELATED_STOCKS](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L252-L572)
  - 主题主体：[_THEMES](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_catalog.py#L686-L1741)

### 页面与路由现状

- 主页面入口已经固定在 [__init__.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/__init__.py#L474-L504)，只读取 catalog 并补充项目股图表与 tweet 详情 URL。
- 主页面模板 [a_share_matches.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_matches.html#L826-L1152) 不依赖具体主题名，只要 catalog 数据结构合法，就会自动渲染新增主题。
- 主题扩展详情页 [a_share_match_theme_stock.html](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/a_share_match_theme_stock.html#L169-L220) 也复用 catalog，不需要新增新路由。
- 结论：这次不需要新增 Flask 页面入口；核心工作都在 catalog 与静态 note 数据。

### Serenity 资料现状

- Serenity 缓存资料在仓库内已有完整落点：
  - [README.md](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/README.md)
  - `serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/*.md`
  - `serenity-aleabitoreddit-main/serenity-aleabitoreddit/references/articles.md`
- 机器人主题已有直接依据：
  - 机器人方法论总述在 [articles.md:L94-L129](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/references/articles.md#L94-L129)
  - `VPG` 证据在 [2026-02.md:L358-L366](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/2026-02.md#L358-L366)
  - `AEVA` 证据在 [2026-02.md:L339-L345](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/2026-02.md#L339-L345)
  - `SSYS` 证据在 [2025-12_to_2026-01.md:L265-L272](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/2025-12_to_2026-01.md#L265-L272)
- 量子计算主题已有直接依据：
  - `INFQ` 证据在 [2026-02.md:L349-L354](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/2026-02.md#L349-L354)
  - `ALRIB` 证据在 [2026-04_to_05.md:L255-L261](file:///Users/jiming/Documents/trae/chanlun-pro/serenity-aleabitoreddit-main/serenity-aleabitoreddit/analysis/2026-04_to_05.md#L255-L261)

### 测试与约束现状

- [test_a_share_matches_catalog.py](file:///Users/jiming/Documents/trae/chanlun-pro/test/test_a_share_matches_catalog.py#L63-L119) 对主题总数、项目股票总数和结构字段做了硬编码断言。
- 新增项目股票后，还必须在 [a_share_matches_tweet_notes.py](file:///Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py#L120) 补 `_NOTES`，否则 `get_project_tweet_note()` 的测试会走默认值，破坏现有结构预期。
- 当前已有 `analysis_detail_url`、财务分析占位、tweet 详情入口，不需要为新增主题单独造新接口。

## Proposed Changes

### 1. 扩展主题配色与主题扩展 A 股

**Modify:** `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

**新增主题名**

- `机器人 / 具身智能 / 核心部件`
- `量子计算 / 精密制造 / 上游设备`

**新增 `_THEME_ACCENTS`**

- 为两个主题分别配置独立 accent，避免走默认蓝色 fallback。

**新增 `_THEME_RELATED_STOCKS`**

- `机器人 / 具身智能 / 核心部件`
  - `300124 汇川技术`：运动控制 / 伺服 / 控制平台
  - `688017 绿的谐波`：谐波减速器
  - `688333 铂力特`：金属 3D 打印 / 结构件制造
- `量子计算 / 精密制造 / 上游设备`
  - `688027 国盾量子`：量子硬件 / 系统侧锚点
  - `688167 炬光科技`：精密激光 / 光源器件
  - `002158 汉钟精机`：真空 / 压缩与设备基础能力

**原因**

- `theme_related_stocks` 是页面上“主题扩展股票”的独立入口，不依赖项目股票映射。
- 用户明确希望主题在 `a_share_matches` 里完整可见，因此每个主题都要有自己的扩展 A 股列表。

### 2. 新增海外项目股票与 A 股映射

**Modify:** `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

**机器人主题项目股票**

- `VPG`
  - 主题芯片：高精度传感 / 机器人手部与力感知
  - A 股核心映射：
    - `301413 安培龙`
    - `300124 汇川技术`
  - A 股候选池：
    - `603728 鸣志电器`
    - `688160 步科股份`
- `AEVA`
  - 主题芯片：FMCW LiDAR / 具身智能感知
  - A 股核心映射：
    - `688167 炬光科技`
    - `301421 波长光电`
  - A 股候选池：
    - `688307 中润光学`
    - `688002 睿创微纳`
- `SSYS`
  - 主题芯片：机器人骨架 / 3D 打印 / 轻量结构材料
  - A 股核心映射：
    - `688333 铂力特`
    - `300580 贝斯特`
  - A 股候选池：
    - `002747 埃斯顿`
    - `603667 五洲新春`

**量子计算主题项目股票**

- `INFQ`
  - 主题芯片：中性原子量子计算 / 商业化量子 sensing
  - A 股核心映射：
    - `688027 国盾量子`
    - `688167 炬光科技`
  - A 股候选池：
    - `301421 波长光电`
    - `002158 汉钟精机`
- `ALRIB`
  - 主题芯片：MBE / 量子器件精密制造设备
  - A 股核心映射：
    - `688012 中微公司`
    - `300316 晶盛机电`
  - A 股候选池：
    - `002008 大族激光`
    - `688120 华海清科`

**实现方式**

- 在 `_THEMES` 中新增两段 `_theme(...)`。
- 每个项目股票都用现有 `_stock(...)`，并为 `main_matches` 与 `candidate_matches` 传入对应 `_match(...)` 列表。
- 评分标准遵循现有页面口径：
  - 核心映射打分偏高，集中在 `14-18`
  - 候选池打分偏低，集中在 `10-14`

**原因**

- 用户已确认要保留“海外锚点股 + A股核心映射 + 候选池”的完整结构。
- `核心 + 候选双层` 比“只放概念股”更符合 Serenity 的瓶颈方法，也和现有主题风格一致。

### 3. 补齐项目股票推荐理由

**Modify:** `web/chanlun_chart/cl_app/a_share_matches_catalog.py`

**新增 `_PROJECT_STOCK_REASON_DATA` 条目**

- `VPG`
- `AEVA`
- `SSYS`
- `INFQ`
- `ALRIB`

**每个条目至少包含**

- `serenity_reason_summary`
- `serenity_reason_highlights`
- `tweet_detail_label`

**文案要求**

- 机器人主题文案必须明确体现 Serenity 的机器人供应链方法：
  - 不把机器人只看成软件 AI
  - 强调传感、执行器、轻量结构、材料与精密制造
- 量子计算主题文案必须体现“纯量子计算设备链”口径：
  - 不扩到量子通信泛主题
  - 强调激光、真空、MBE、精密工艺与量子 sensing / 设备化落地

### 4. 补齐项目股票静态 notes 与详情页内容

**Modify:** `web/chanlun_chart/cl_app/a_share_matches_tweet_notes.py`

**新增 `_NOTES` 条目**

- `VPG`
- `AEVA`
- `SSYS`
- `INFQ`
- `ALRIB`

**每个 note 必须补齐**

- `overview_title`
- `overview_summary`
- `why_serenity_likes_it`
- `industry_chain`
- `stage_view`
- `market_cap_view`
- `timeline_sections`

**内容口径**

- `VPG`：
  - 强调手部/力控/高精度传感在具身智能中的高附加值
- `AEVA`：
  - 强调 FMCW LiDAR 的 deterministic velocity 与机器人感知价值
- `SSYS`：
  - 强调机器人骨架、结构件、美国认证与 3D 打印材料路径
- `INFQ`：
  - 强调 neutral-atom 与已有量子 sensing 收入，而非“science project”
- `ALRIB`：
  - 强调 MBE 设备在量子点 / 量子器件制造中的前段卡位

**原因**

- 新增项目股票如果没有 notes，会破坏现有详情页与测试预期。
- `a_share_matches` 当前的用户体验并不只是展示名字和映射，还依赖 note 驱动的阶段、市值空间和产业链说明。

### 5. 同步更新模板断言与统计测试

**Modify:** `test/test_a_share_matches_catalog.py`

**需要更新的硬编码断言**

- `theme_count`：从 `10` 更新为 `12`
- `project_stock_count`：从 `21` 更新为 `26`

**新增断言**

- 页面 HTML 中出现：
  - `机器人`
  - `量子计算`
  - `VPG`
  - `AEVA`
  - `SSYS`
  - `INFQ`
  - `ALRIB`
- 主题 slug 唯一性继续成立
- 新增项目股票都具备：
  - `analysis_detail_url`
  - `serenity_reason_summary`
  - `stage_snapshot`
  - `market_cap_snapshot`

### 6. 补充与 Serenity 方法一致性的说明性验证

**Modify:** `test/test_a_share_matches_catalog.py`

**新增针对性断言**

- 机器人主题项目股票至少有一个映射到：
  - 传感 / 光学感知
  - 执行器 / 运动控制
  - 结构件 / 制造
- 量子计算主题项目股票至少有一个映射到：
  - 量子系统 / 硬件
  - 激光 / 光源
  - 真空 / 精密制造设备

**原因**

- 这不是为了测试金融正确性，而是为了防止实现时把量子和机器人主题做成泛概念股堆砌。
- 能把 Serenity 的“上游瓶颈 / 精密制造”方法约束进测试，减少后续偏移。

## Assumptions & Decisions

- 用户已经确认：
  - 做两个独立主题，不合并
  - 保留“海外锚点股 + A股映射”完整结构
  - A 股采用“核心 + 候选双层”
  - 量子计算采用“纯量子计算设备链”口径
  - Serenity 依据使用仓库内缓存资料
- 本次不做：
  - 新增新的页面路由
  - 新增新的数据库表
  - 联网刷新 Serenity 数据
  - 给机器人/量子主题增加单独的前端交互逻辑
- `a_share_matches` 现有模板与路由足以承载新增主题，因此主要是静态数据和测试扩展。
- 由于 Serenity 官方刷新命令在当前环境不可用，实施时默认以仓库内 `serenity-aleabitoreddit-main` 为事实依据；若执行阶段发现本地资料与当前市场明显脱节，只允许作为注释性风险提示，不改动用户已确认的主题边界。

## Verification Steps

### 自动化验证

- 运行：

```bash
pytest test/test_a_share_matches_catalog.py -q
```

- 补充回归：

```bash
pytest test/test_a_share_matches_tweets.py test/test_a_share_matches_quotes.py -q
```

### 手工验证

- 打开 `/a_share_matches`
- 验证主题导航中新增：
  - `机器人`
  - `量子计算`
- 验证两个新主题 section 都包含：
  - 主题扩展股票
  - 海外项目股票
  - A 股核心映射
  - A 股候选池
- 点击新增项目股票的：
  - `查看推荐脉络`
  - `查看个股分析`
  - `查看缠论图`
  确认页面仍能正常工作
- 打开主题扩展股票详情：
  - 验证新主题的 `theme_slug` 和 `theme_title` 正确传递

### 交付检查

- 不破坏现有 10 个主题内容
- 不破坏现有项目股票详情页与 tweet 详情页
- 新增 5 个项目股票的 note 结构完整
- 测试断言与 catalog 实际数量保持一致
