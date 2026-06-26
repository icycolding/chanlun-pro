# Serenity AI Stocks 左右分栏布局改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前分离的 `Sheet 总览页` 和 `股票明细页` 改造成单一的左右分栏页面，左侧展示 Sheet 总览，右侧展示当前选中 Sheet 的股票表格与后台同步状态。

**Architecture:** 复用现有 workbook 加载、数据库价格水合、价格轮询和同步状态接口，不新增数据源。后端将 `/serenity/aistocks` 与 `/serenity/aistocks/<sheet_slug>` 都渲染为同一套 master-detail 模板；前端用 `localStorage` 记住上次选中的 Sheet，并在访问总览地址时恢复到上次选择。

**Tech Stack:** Python, Flask, Jinja2, 现有 `serenity_aistocks.py` 路由与数据函数, 原生 HTML/CSS/JavaScript, pytest

---

## Summary

- 当前 `Serenity AI Stocks` 仍是两页式：
  - `/serenity/aistocks` 渲染 `serenity_aistocks_index.html`，只显示 workbook 概览和 Sheet 卡片。
  - `/serenity/aistocks/<sheet_slug>` 渲染 `serenity_aistocks_sheet.html`，只显示单个 Sheet 的表格、价格轮询和后台同步状态。
- 本次改造目标是把它收敛为单一交互模型：
  - 左侧固定为 `Sheet 总览 / 导航`
  - 右侧显示 `当前选中 Sheet 的股票表格`
  - 价格列、同步状态面板、60 秒刷新逻辑继续保留
  - 明细 URL 继续可访问，并在左侧高亮对应 Sheet
  - 访问 `/serenity/aistocks` 时优先恢复上次选择，没有记录或记录失效时回退到第一个 Sheet

## Current State Analysis

### 已确认的代码现状

- `web/chanlun_chart/cl_app/serenity_aistocks.py`
  - `load_serenity_aistocks_workbook()` 只返回 workbook 摘要，不附带当前选中 Sheet。
  - `get_serenity_aistocks_sheet(sheet_slug)` 能返回单个 Sheet，且已从项目数据库水合价格字段。
  - `/serenity/aistocks` 路由当前只向模板传 `workbook`。
  - `/serenity/aistocks/<sheet_slug>` 路由当前渲染独立模板，并注入 `sheet` 与 `sync_status`。
  - `/serenity/aistocks/prices` 与 `/serenity/aistocks/status` 已满足新布局所需的数据刷新能力，无需新增 API。

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
  - 当前只包含 hero、统计卡片、Sheet 卡片网格。
  - 每个 Sheet 使用 `/serenity/aistocks/{{ sheet.sheet_slug }}` 跳转到独立详情页。

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`
  - 当前包含单个 Sheet 标题、返回总览按钮、后台同步状态面板、价格表格。
  - 已具备价格轮询和同步状态轮询脚本。

- `test/test_serenity_aistocks.py`
  - 已覆盖 workbook 加载、单个 sheet 水合、模板渲染、路由存在、价格接口、后台同步。
  - 当前模板断言仍基于“两页式”结构，后续需要改成同页左右分栏断言。

### 关键约束

- 不改动现有数据库结构和后台定时同步机制。
- 不新增价格接口或状态接口。
- `/serenity/aistocks/<sheet_slug>` 需要继续可用，避免已有链接失效。
- “记住上次选择” 不应引入服务端持久化；优先采用浏览器侧存储，保持改动最小。

## Assumptions & Decisions

- 统一模板决策：
  - 两个页面入口最终渲染为同一个 master-detail 模板。
  - 建议直接将 `serenity_aistocks_index.html` 升级为新的分栏模板。
  - `/serenity/aistocks/<sheet_slug>` 路由也渲染 `serenity_aistocks_index.html`，不再单独使用 `serenity_aistocks_sheet.html` 作为主模板。

- 选中 Sheet 决策：
  - 服务端始终需要一个可渲染的 `selected_sheet`。
  - `/serenity/aistocks/<sheet_slug>`：使用 URL 中的 slug；不存在时返回 404，保持当前行为。
  - `/serenity/aistocks`：服务端默认使用第一个 Sheet 作为回退选中项，保证首屏稳定渲染。
  - 前端加载后读取 `localStorage.lastSerenityAIStocksSheetSlug`：
    - 若当前地址是 `/serenity/aistocks`
    - 且本地记录的 slug 存在于当前 workbook
    - 且它不是当前服务端回退出的 slug
    - 则客户端跳转到 `/serenity/aistocks/<saved_slug>`，实现“记住上次选择”。

- 交互决策：
  - 左侧 Sheet 卡片/列表点击统一跳到 `/serenity/aistocks/<sheet_slug>`。
  - 当前选中项在左侧展示激活态。
  - 右侧顶部显示当前 Sheet 标题与摘要，不再保留“返回总览”按钮，因为总览已在左侧常驻。

- 响应式决策：
  - 桌面端采用左右两栏。
  - 窄屏下自动堆叠为上下结构，左侧导航在上，右侧表格在下，不额外新增移动端路由。

## Proposed Changes

### 1. 后端：统一页面上下文

**Files**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`

**What**
- 增加一个内部辅助函数，统一为模板组装页面上下文：
  - `workbook`
  - `selected_sheet`
  - `selected_sheet_slug`
  - `sync_status`
  - `sheet_slug_set` 或等价数据，用于前端校验本地缓存 slug 是否有效
- 让 `/serenity/aistocks` 与 `/serenity/aistocks/<sheet_slug>` 都渲染相同模板。

**Why**
- 避免在两个路由里复制“选中 Sheet 解析”和模板参数组装逻辑。
- 为单一布局准备一致的数据结构，减少模板条件分支。

**How**
- 新增内部帮助函数，例如：
  - `_resolve_serenity_aistocks_page_context(sheet_slug: str | None, status_provider) -> dict[str, Any]`
- 该函数内部流程：
  - 调用 `load_serenity_aistocks_workbook()`
  - 取 `workbook["sheets"]`
  - 若为空则返回空态上下文
  - 若 `sheet_slug` 为空，选中第一个 `sheet_slug`
  - 若 `sheet_slug` 非空，则调用 `get_serenity_aistocks_sheet(sheet_slug)`，不存在时返回 `None`
  - 组装 `selected_sheet_summary`（从 workbook.sheets 中匹配）
  - 注入 `_build_sync_status_payload(status_provider())`
- 路由行为：
  - `/serenity/aistocks`：渲染统一模板
  - `/serenity/aistocks/<sheet_slug>`：若无此 sheet 返回 404，否则渲染统一模板

### 2. 模板：将总览页改造成左导航 + 右表格

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 将当前只显示总览的模板改成单页 master-detail 结构。
- 左侧包含：
  - Hero 简介
  - workbook 统计卡片
  - `Sheet 总览` 导航列表
- 右侧包含：
  - 当前选中 Sheet 的标题与统计信息
  - 后台同步状态面板
  - 股票表格与价格列

**Why**
- 这是用户明确要求的主视觉结构。
- 复用现有表格和状态模块，可降低回归风险。

**How**
- 页面骨架建议：
  - `.layout` 外层 `display: grid`
  - 左侧 `.sidebar`
  - 右侧 `.content`
- 左侧列表数据来自 `workbook.sheets`，每项展示：
  - `sheet_name`
  - `row_count`
  - `has_price_candidates`
  - `sample_symbols`
- 当前选中项增加：
  - `active` class
  - 清晰背景、边框或左侧高亮条
- 右侧表格直接迁移 `serenity_aistocks_sheet.html` 里的成熟结构：
  - `sync-status`
  - `table-shell`
  - `.price-cell` 数据属性
  - 价格状态类名与刷新脚本
- 右侧标题区增加当前 Sheet 摘要：
  - `sheet_name`
  - `row_count`
  - 原始列数
  - 可抓价数量

### 3. 前端：记住上次选择并恢复

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 在统一模板中加入浏览器侧记忆逻辑。

**Why**
- 用户明确选择“记住上次选择”。
- 该需求无需引入 cookie 或后端会话，使用 `localStorage` 成本最低。

**How**
- 页面渲染时输出：
  - 当前 `selected_sheet_slug`
  - 所有合法 sheet slug 列表
  - overview 基础路径 `/serenity/aistocks`
- JavaScript 逻辑：
  - 若当前页面是明细路径，则保存 `selected_sheet_slug` 到 `localStorage.lastSerenityAIStocksSheetSlug`
  - 若当前页面是 overview 路径，则读取本地记录：
    - 本地 slug 在合法集合内
    - 且与当前选中 slug 不同
    - 则 `window.location.replace("/serenity/aistocks/" + savedSlug)`
  - 若无本地记录或记录失效，则保持当前首屏

### 4. 模板收敛：处理旧明细模板

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

**What**
- 将其收敛为两种可选策略中的一种，执行时二选一并保持最小变更：
  - 首选：保留文件但不再被路由使用，模板内容改为简短注释或复用说明，仅为后续清理留口子。
  - 备选：保持文件存在但不改内容，路由完全切到 `serenity_aistocks_index.html`。

**Why**
- 降低一次性删除模板带来的额外风险。
- 本次目标是完成布局改造，不是模板清理工程。

**How**
- 实施时优先选择“保留文件但不再被路由使用”，避免不必要的删除操作。
- 如果测试和引用已全部迁移，也可以在后续单独整理，不纳入本次范围。

### 5. 测试：以 TDD 锁定新布局

**Files**
- Modify: `test/test_serenity_aistocks.py`

**What**
- 先新增失败测试，再改代码。
- 将断言从“两页式”切换到“统一左右分栏页”。

**Why**
- 本次是明确的行为变更，必须先让测试描述新页面结构和恢复逻辑。

**How**
- 新增或调整测试覆盖点：
  - `test_serenity_aistocks_index_template_renders_sidebar_and_selected_sheet_table`
    - 断言同一 HTML 同时包含 `Sheet 总览`、当前选中 Sheet 名称、价格表格、后台同步状态、左侧 active 状态
  - `test_serenity_aistocks_index_template_includes_local_storage_restore_script`
    - 断言存在 `localStorage.lastSerenityAIStocksSheetSlug`
    - 断言 overview 恢复跳转逻辑存在
  - `test_serenity_aistocks_routes_exist`
    - 保留 `/serenity/aistocks` 和 `/serenity/aistocks/<sheet_slug>` 均返回 200
    - 额外断言两者都包含左右分栏关键文案
  - 可选新增 `test_serenity_aistocks_detail_route_still_404s_for_unknown_sheet`
    - 保持非法 slug 的兼容行为
- 旧的 `test_serenity_aistocks_sheet_template_renders_price_cells_and_refresh_hooks` 需要迁移：
  - 若统一模板后只测试 `serenity_aistocks_index.html`，则把价格轮询相关断言并入新的 index 模板测试。

## Implementation Steps

### Task 1: 写出统一布局的失败测试

**Files**
- Modify: `test/test_serenity_aistocks.py`

- [ ] 新增模板级失败测试，明确一个 HTML 页面内同时出现左侧 Sheet 总览和右侧股票表格。
- [ ] 新增本地记忆脚本失败测试，断言 `localStorage.lastSerenityAIStocksSheetSlug` 和 overview 恢复逻辑存在。
- [ ] 更新路由测试，要求 `/serenity/aistocks` 与 `/serenity/aistocks/<sheet_slug>` 都命中新布局。
- [ ] 运行针对性测试，确认先红灯：

```bash
pytest test/test_serenity_aistocks.py -k "index_template or routes_exist" -v
```

### Task 2: 后端统一页面上下文

**Files**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`

- [ ] 新增内部 helper，统一解析 `workbook`、`selected_sheet`、`selected_sheet_slug`、`selected_sheet_summary`、`sync_status`。
- [ ] 将 overview/detail 两个路由都切换到渲染同一模板。
- [ ] 保持 detail 非法 slug 返回 404。
- [ ] 运行相关测试，确保 helper 接入后路由层通过。

### Task 3: 重写 index 模板为 master-detail

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] 把左侧导航和右侧内容整合到一个模板中。
- [ ] 从旧 `serenity_aistocks_sheet.html` 迁移同步状态面板、表格结构和价格刷新脚本。
- [ ] 增加当前选中 Sheet 的 active 视觉状态和统计信息。
- [ ] 增加窄屏堆叠样式，保证移动端可浏览。
- [ ] 运行模板与路由测试，确认绿灯。

### Task 4: 接入“记住上次选择”

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] 在明细路径保存当前 slug 到 `localStorage`。
- [ ] 在 overview 路径尝试恢复本地保存的 slug，并校验 slug 合法性。
- [ ] 保证恢复逻辑不影响无 JS 或无本地记录场景。
- [ ] 重新运行模板测试，确认脚本断言通过。

### Task 5: 回归验证与模板收敛

**Files**
- Modify: `test/test_serenity_aistocks.py`
- Optional Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

- [ ] 跑完整 `test/test_serenity_aistocks.py`。
- [ ] 如有必要，保留 `serenity_aistocks_sheet.html` 但停止路由使用，不在本次做额外清理。
- [ ] 检查是否存在因模板切换导致的遗漏断言，补足最小回归覆盖。

## Verification

- 单测：

```bash
pytest test/test_serenity_aistocks.py -v
```

- 重点人工验证点：
  - 打开 `/serenity/aistocks`，左侧出现 Sheet 总览，右侧直接显示股票表格。
  - 点击左侧任一 Sheet，URL 变为 `/serenity/aistocks/<sheet_slug>`，右侧切换为对应股票表。
  - 刷新后再次进入 `/serenity/aistocks`，若浏览器保留本地记录，应恢复上次选择。
  - 右侧仍显示“后台同步状态”。
  - 价格列仍保留 `pending / ok / unsupported / error / up / down` 展示状态。
  - 非法 slug 访问仍返回 404。

- 非目标范围：
  - 不改数据库表或同步任务。
  - 不新增筛选、搜索、排序等额外交互。
  - 不在本次重构中做模板文件大清理。
