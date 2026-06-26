# Serenity AI Stocks 涨跌幅点击排序 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `Serenity AI Stocks` 股票表格增加“点击价格表头按涨跌幅排序”的前端交互，并支持 `原顺序 → 高到低 → 低到高` 的三态循环。

**Architecture:** 复用现有模板中 `价格` 列已经渲染出的 `rate_text` 与 `price_status` 信息，不新增后端接口或数据库字段。排序完全在 `serenity_aistocks_index.html` 的前端完成，通过 DOM 数据属性和客户端重排 `tbody` 实现，同时保留现有价格刷新、同步状态刷新和 URL/Sheet 恢复逻辑。

**Tech Stack:** Flask, Jinja2, HTML/CSS/JavaScript, pytest

---

## Summary

- 当前股票表格里没有单独的“涨跌幅”列。
- 现有涨跌幅只显示在 `价格` 列里的 `.price-sub` 文本中，内容形如：
  - `+1.23% · 2026-06-17 10:00:00`
  - 或 `--`
  - 或 `等待后台同步`
- 用户需求已锁定：
  - 不新增单独的 `涨跌幅` 列。
  - 直接点击现有 `价格` 表头进行排序。
  - 排序循环为：`原顺序 → 高到低 → 低到高`。

## Current State Analysis

### 已确认的代码现状

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
  - 表头当前是静态输出：
    - `{% for column in selected_sheet.columns %}<th>{{ column }}</th>{% endfor %}`
  - 数据行当前没有任何排序相关数据属性，只有价格查询相关属性：
    - `data-row-id`
    - `data-market`
    - `data-code`
    - `data-symbol`
  - `价格` 列的副文本 `.price-sub` 在 `row.price_status == 'ok'` 时会显示 `row.rate_text` 与更新时间。
  - `refreshPrices()` 在轮询后只更新文本和价格状态颜色，不会重排行。

- `test/test_serenity_aistocks.py`
  - 当前只验证表格、价格列、刷新脚本和路由存在。
  - 尚未覆盖排序触发点、排序状态文案、排序脚本函数或排序相关数据属性。

### 约束

- 不新增后端排序参数，不改 `/serenity/aistocks/prices` API。
- 不新增数据库字段，不把排序状态持久化到服务端。
- 排序必须兼容已有价格刷新：
  - 后台价格刷新后，当前排序状态不能失效。
- 不新增单独“涨跌幅”列，排序入口固定为现有 `价格` 表头。

## Assumptions & Decisions

- 排序入口决策：
  - 将 `价格` 表头改成可点击元素，支持视觉上的可排序态。
  - 不改其他列，不做多列排序。

- 排序状态决策：
  - 三态循环：`none -> desc -> asc -> none`
  - 对应中文可视状态建议：
    - `原顺序`
    - `涨跌幅从高到低`
    - `涨跌幅从低到高`
  - 可用表头箭头或状态文案提示当前排序方向。

- 排序数据决策：
  - 每一行在首次渲染时写入：
    - 原始顺序索引，例如 `data-original-index`
    - 当前可排序的涨跌幅数值，例如 `data-rate-value`
  - `ok` 状态时从 `row.rate_text` 解析出数值。
  - `pending / unsupported / error` 状态统一视为不可排序值，并在排序时排到末尾。

- 刷新兼容决策：
  - `refreshPrices()` 更新单元格时，同时更新所在行的 `data-rate-value`。
  - 如果当前排序状态不是 `none`，刷新后需要重新应用一次当前排序，以保持用户看到的顺序稳定。

## Proposed Changes

### 1. 模板：让 `价格` 表头成为排序入口

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 把当前静态的 `价格` 表头改成可点击的排序控件。
- 为表格增加排序状态展示。

**Why**
- 用户明确要求“股票可以点击排序，按涨跌幅排序”，且入口固定在现有 `价格` 列。

**How**
- 将最后一个 `th` 单独处理，而不是简单 `for` 循环纯文本输出。
- 在 `价格` 表头内加入：
  - 可点击按钮或按钮样式的容器
  - 排序状态文字/箭头
  - 例如 `data-sort-state="none"`
- 维持其余列头不变，范围只限 `价格` 列。

### 2. 模板：为每一行注入排序元数据

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 在每个 `tr` 上写入排序需要的元数据。

**Why**
- 前端排序必须知道：
  - 原始顺序
  - 当前涨跌幅数值

**How**
- 为每个数据行增加：
  - `data-original-index="{{ loop.index0 }}"`
  - `data-rate-value="..."`，根据 `row.rate_text` 和 `row.price_status` 渲染
- `ok` 状态：
  - 可直接写入清洗过的数值字符串，例如 `1.23`
- `pending / unsupported / error`：
  - 写空字符串或特殊标记
- 排序时约定：
  - 有效数值优先
  - 无效值统一排到末尾

### 3. 前端：实现三态排序与刷新后重排

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 增加排序状态机与 `tbody` 重排逻辑。
- 在价格刷新后保持当前排序态。

**Why**
- 仅点击表头变样式不够，必须真正重排表格。
- 价格刷新会改变涨跌幅，不重新排序会让显示顺序和当前排序态不一致。

**How**
- 新增脚本函数建议：
  - `parseRateValue(rateText)`
  - `getNextRateSortState(currentState)`
  - `applyRateSort()`
  - `updateRateSortIndicator()`
- 维护全局状态，例如：
  - `let currentRateSortState = "none";`
- 点击 `价格` 表头时：
  - `none -> desc`
  - `desc -> asc`
  - `asc -> none`
- 排序规则：
  - `desc`: 按 `data-rate-value` 从大到小
  - `asc`: 按 `data-rate-value` 从小到大
  - `none`: 按 `data-original-index` 还原
  - 无效值始终排在末尾
- 在 `updatePriceCell()` 中：
  - 重新计算并写回所属行的 `data-rate-value`
- 在 `refreshPrices()` 成功更新后：
  - 若当前状态不是 `none`，调用 `applyRateSort()`

### 4. 测试：锁定排序入口与脚本行为

**Files**
- Modify: `test/test_serenity_aistocks.py`

**What**
- 先写失败测试，再实现排序。

**Why**
- 本次是明确的前端行为变化，需要先由测试描述新的交互 contract。

**How**
- 模板测试新增断言：
  - `价格` 表头可点击
  - 存在排序状态变量/函数
  - 存在 `data-original-index`
  - 存在 `data-rate-value`
  - 存在 `applyRateSort` 或等价函数
  - 存在排序状态循环逻辑
- 路由测试无需新增接口，但要确保 overview/detail 继续渲染出排序入口。

## Implementation Steps

### Task 1: 先写排序的失败测试

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] **Step 1: 为模板新增排序入口断言**

```python
def test_serenity_aistocks_index_template_includes_rate_sort_controls(monkeypatch):
    ...
    assert 'id="rate-sort-button"' in html
    assert "data-original-index=" in html
    assert "data-rate-value=" in html
```

- [ ] **Step 2: 为脚本新增排序状态机断言**

```python
assert "applyRateSort" in html
assert "getNextRateSortState" in html
assert 'currentRateSortState = "none"' in html
```

- [ ] **Step 3: 运行定向测试确认红灯**

Run: `pytest test/test_serenity_aistocks.py -k "rate_sort or index_template" -v`

Expected: FAIL，因为当前模板尚无排序入口和排序脚本。

### Task 2: 为模板注入排序元数据与可点击表头

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 调整表头，给 `价格` 列单独渲染排序按钮**

```html
<th class="sortable-price-header">
    <button type="button" id="rate-sort-button">价格</button>
</th>
```

- [ ] **Step 2: 为每个数据行写入原始顺序与涨跌幅元数据**

```html
<tr data-original-index="{{ loop.index0 }}" data-rate-value="...">
```

- [ ] **Step 3: 增加必要样式，让表头可点击且能显示状态**

```css
.sortable-price-header button {
    cursor: pointer;
}
```

- [ ] **Step 4: 运行定向测试，确认模板结构层面通过**

Run: `pytest test/test_serenity_aistocks.py -k "rate_sort or index_template" -v`

Expected: 部分通过，若脚本尚未补齐则继续红灯。

### Task 3: 实现前端三态排序和刷新后重排

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 增加排序状态机与重排函数**

```javascript
let currentRateSortState = "none";

function getNextRateSortState(currentState) {
    if (currentState === "none") return "desc";
    if (currentState === "desc") return "asc";
    return "none";
}
```

- [ ] **Step 2: 在点击 `价格` 表头时触发排序**

```javascript
const rateSortButton = document.getElementById("rate-sort-button");
if (rateSortButton) {
    rateSortButton.addEventListener("click", () => {
        currentRateSortState = getNextRateSortState(currentRateSortState);
        applyRateSort();
    });
}
```

- [ ] **Step 3: 在 `updatePriceCell()` 中同步更新行级 `data-rate-value`**

```javascript
const row = cell.closest("tr");
if (row) {
    row.dataset.rateValue = parseRateValue(rateText);
}
```

- [ ] **Step 4: 在 `refreshPrices()` 完成后重用当前排序态**

```javascript
if (currentRateSortState !== "none") {
    applyRateSort();
}
```

- [ ] **Step 5: 再跑定向测试，确认全部转绿**

Run: `pytest test/test_serenity_aistocks.py -k "rate_sort or index_template" -v`

Expected: PASS

### Task 4: 完整回归与诊断

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 跑完整 Serenity AI Stocks 测试**

Run: `pytest test/test_serenity_aistocks.py -v`

Expected: PASS

- [ ] **Step 2: 检查编辑文件诊断**

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
  - 打开任一 `/serenity/aistocks/<sheet_slug>` 页面。
  - 点击 `价格` 表头第一次，表格按涨跌幅从高到低重排。
  - 第二次点击，表格按涨跌幅从低到高重排。
  - 第三次点击，恢复 Excel 原始顺序。
  - `pending / unsupported / error` 行在排序时落到表格末尾。
  - 后台 60 秒价格刷新后，若当前处于排序态，表格会按照最新涨跌幅重新排序。
