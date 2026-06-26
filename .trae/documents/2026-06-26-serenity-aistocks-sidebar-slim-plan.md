# Serenity AI Stocks 侧栏收缩与同步状态迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `Serenity AI Stocks` 页面左侧收缩成纯 Sheet 导航栏，移除页面标题大卡片，并把“后台同步状态”从右侧主内容区迁到左侧底部的紧凑区域。

**Architecture:** 保持现有 `/serenity/aistocks` 与 `/serenity/aistocks/<sheet_slug>` 的统一模板、价格轮询和状态接口不变，只调整 `serenity_aistocks_index.html` 的布局层级与状态展示位置。测试继续围绕模板渲染和路由输出做断言，确保本次只是 UI 收缩，不影响数据与接口行为。

**Tech Stack:** Python, Flask, Jinja2, HTML/CSS/JavaScript, pytest

---

## Summary

- 当前页面左侧由两个大块组成：
  - `hero` 区块，显示 `Serenity AI Stocks` 标题、说明和 workbook 统计。
  - `Sheet 总览` 区块，显示所有 Sheet 导航。
- 当前页面右侧把“后台同步状态”作为独立大卡片放在股票表格上方，视觉占用较大。
- 本次目标已经锁定：
  - 左侧只保留 Sheet 列表，不再显示 `Serenity AI Stocks` 标题与统计卡片。
  - “后台同步状态”移到左侧底部，并改成更紧凑的展示。
  - 不调整接口、不新增交互、不改数据库同步逻辑。

## Current State Analysis

### 已确认的代码现状

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
  - 左侧 `.sidebar` 里先渲染 `.hero`，再渲染 `.sidebar-panel`。
  - `.hero` 内包含：
    - `Serenity AI Stocks` 标题
    - 一段说明文案
    - `Workbook / Sheet 数量 / 总行数` 三张统计卡
  - `Sheet 总览` 列表在第二个卡片 `.sidebar-panel` 内。
  - 右侧主内容区在股票表格上方单独渲染 `<section class="sync-status">`。

- `test/test_serenity_aistocks.py`
  - 模板测试当前显式断言 `Serenity AI Stocks` 和 `后台同步状态` 出现在页面中。
  - 路由测试也断言 overview/detail 页包含 `后台同步状态`。
  - 这些测试需要跟着新布局一起调整：
    - 不再要求标题文案 `Serenity AI Stocks` 出现在左侧页面主体中。
    - 仍需断言存在同步状态，但位置与结构要改成“左侧底部紧凑区”。

### 约束

- 只做布局收缩，不改 `serenity_aistocks.py` 路由和状态接口结构，除非模板上下文字段确有缺失。
- 仍需保留：
  - 左侧当前选中 Sheet 的高亮态
  - 价格轮询
  - 同步状态轮询
  - `/serenity/aistocks` 与 `/serenity/aistocks/<sheet_slug>` 的兼容行为

## Assumptions & Decisions

- 左侧结构决策：
  - 完全移除 `.hero` 区块。
  - 左侧只保留一个主要导航容器，顶部可保留极简的 `Sheet 总览` 标题，但不再显示 `Serenity AI Stocks`。
  - workbook 统计卡不再展示。

- 同步状态决策：
  - 右侧不再保留独立的 `.sync-status` 大卡片。
  - 同步状态迁移到左侧导航列表下方，作为一个更紧凑的底部状态块。
  - 默认展示最关键的字段：
    - 运行状态
    - 上次同步
    - 成功数 / 总数
    - 错误文案（仅存在错误时显示）
  - “同步周期”从主视图移除，避免占位；如果后续需要，可作为 tooltip 或二级信息补回，但不在本次范围。

- 右侧结构决策：
  - 保留当前 Sheet 标题和摘要卡。
  - 股票表格紧跟在标题摘要区后面，优先提升可视区域。

## Proposed Changes

### 1. 模板：收缩左侧为纯导航

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 删除左侧 `.hero` 模块和其中的统计卡。
- 保留 `Sheet 总览` 标题与 Sheet 列表，但整体改成更紧凑的单容器结构。

**Why**
- 用户明确要求 `Serenity AI Stocks` 不需要显示。
- 目前左侧两个大块导致导航真正可见区域被压缩。

**How**
- 移除：
  - `.hero`
  - `.stats`
  - `.stat-card`
  - `.stat-label`
  - `.stat-value`
- 保留并精简：
  - `.sidebar-panel`
  - `.sheet-nav`
  - `.sheet-link`
- 需要同步清理不再使用的 CSS，避免模板里残留无效样式。

### 2. 模板：把同步状态移到左侧底部

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 将右侧独立的 `<section class="sync-status" id="sync-status-panel">` 移出主内容区。
- 在左侧 Sheet 列表下方新增一个更小的同步状态块。

**Why**
- 用户明确指出“后台同步状态占用地方太多”。
- 同步状态是辅助信息，更适合放在导航侧边，不应抢占表格上方的首屏空间。

**How**
- 左侧状态块建议结构：
  - 标题：`后台同步`
  - 一行或两行网格展示：
    - `运行状态`
    - `上次同步`
    - `成功数 / 总数`
  - `last_error` 仅在非空时显示红色错误提示
- 样式建议：
  - 使用更小的 padding
  - 将 `sync-status-grid` 从 `repeat(4, ...)` 缩到 `1-2 列`
  - 字号比右侧当前实现略小
- JavaScript 仍复用现有 DOM id：
  - `sync-status-label`
  - `sync-last-run`
  - `sync-success-summary`
  - `sync-error-text`
- `sync-interval` 若移除，则需同步更新前端脚本，避免继续查询不存在的 DOM。

### 3. 模板：扩大右侧表格可视空间

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 删除右侧的大块同步状态区后，保留当前 Sheet 标题摘要和股票表格。
- 适度缩短右侧顶部摘要区的高度，让表格更早进入视口。

**Why**
- 本次收缩的主要受益区域就是股票表格首屏。

**How**
- 保留 `content-panel`，但可减少 `padding`、`margin-bottom`。
- 让 `table-shell` 紧接 `content-panel`。
- 不新增任何筛选/排序/搜索功能，防止范围膨胀。

### 4. 测试：更新断言以匹配精简布局

**Files**
- Modify: `test/test_serenity_aistocks.py`

**What**
- 调整模板与路由测试，反映新的结构。

**Why**
- 当前测试仍把旧大标题和右侧同步状态卡作为预期行为。

**How**
- 调整/新增断言：
  - `test_serenity_aistocks_index_template_renders_sheet_cards`
    - 不再断言 `Serenity AI Stocks`
    - 继续断言 `Sheet 总览`
    - 断言同步状态仍存在，但以左侧紧凑模块方式出现
  - `test_serenity_aistocks_index_template_includes_price_cells_and_restore_hooks`
    - 保留价格轮询和状态轮询脚本断言
    - 若 `sync-interval` DOM 被移除，则不要再隐式依赖它
  - `test_serenity_aistocks_routes_exist`
    - 继续断言 overview/detail 都包含 `Sheet 总览` 和同步状态文字
    - 不再要求旧标题块存在

## Implementation Steps

### Task 1: 先写失败测试锁定新布局

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] **Step 1: 写模板失败测试，去掉旧标题断言并保留紧凑同步状态断言**

```python
def test_serenity_aistocks_index_template_renders_sheet_cards(monkeypatch):
    ...
    assert "Serenity AI Stocks" not in html
    assert "Sheet 总览" in html
    assert "后台同步" in html
```

- [ ] **Step 2: 写路由失败测试，锁定 overview/detail 仍能看到左侧同步状态**

```python
def test_serenity_aistocks_routes_exist(app_client):
    ...
    assert "Sheet 总览" in overview_html
    assert "后台同步" in overview_html
```

- [ ] **Step 3: 运行测试确认红灯**

Run: `pytest test/test_serenity_aistocks.py -k "index_template or routes_exist" -v`

Expected: FAIL，因为模板仍然输出旧的 `Serenity AI Stocks` 大标题和右侧大块同步状态结构。

### Task 2: 精简左侧并迁移同步状态

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 删除左侧 hero 与统计卡相关 HTML**

```html
<!-- 删除原 hero 区块 -->
<!-- 保留 sidebar-panel + sheet-nav 作为唯一主要左栏结构 -->
```

- [ ] **Step 2: 把右侧 sync-status 模块移动到左侧底部，并改成紧凑版**

```html
<section class="sidebar-panel sync-status compact-sync-status" id="sync-status-panel">
    <h3>后台同步</h3>
    ...
</section>
```

- [ ] **Step 3: 清理并重写相关 CSS**

```css
.compact-sync-status {
    padding: 14px 16px;
}
.compact-sync-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
}
```

- [ ] **Step 4: 运行定向测试确认转绿**

Run: `pytest test/test_serenity_aistocks.py -k "index_template or routes_exist" -v`

Expected: PASS

### Task 3: 修正前端状态脚本与完整回归

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] **Step 1: 若移除了 `sync-interval` DOM，则同步收敛 JS 更新逻辑**

```javascript
const interval = document.getElementById("sync-interval");
if (interval) {
    interval.textContent = `${status.interval_seconds || 60} 秒`;
}
```

- [ ] **Step 2: 保持价格刷新与状态刷新断言不变，只更新必要的模板结构断言**

```python
assert "/serenity/aistocks/status" in html
assert "refreshSyncStatus" in html
assert "lastSerenityAIStocksSheetSlug" in html
```

- [ ] **Step 3: 跑完整测试文件**

Run: `pytest test/test_serenity_aistocks.py -v`

Expected: PASS

- [ ] **Step 4: 检查编辑文件诊断**

Check diagnostics for:
- `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

Expected: 无新增 diagnostics

## Verification

- 自动化验证：

```bash
pytest test/test_serenity_aistocks.py -v
```

- 人工验证：
  - 打开 `/serenity/aistocks`，左侧不再显示 `Serenity AI Stocks` 大标题与统计卡。
  - 左侧主体以 `Sheet 总览` + Sheet 列表为主。
  - 左侧底部可看到更紧凑的“后台同步”状态。
  - 右侧首屏更快进入股票表格，不再被独立大块同步状态压住。
  - 点击左侧 Sheet 后，右侧表格正常切换，`localStorage` 恢复逻辑仍可工作。
  - 状态轮询和价格轮询继续生效。
