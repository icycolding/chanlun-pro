# Serenity AI Stocks 点击股票打开缠论图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `Serenity AI Stocks` 页面中的股票名称可点击，并复用 `a_share_matches` 的弹窗方式在当前页打开对应缠论图。

**Architecture:** 复用现有 `quote_target` 推导出的市场与代码信息，在 `serenity_aistocks.py` 中为每行补充 `chart_url` / `chart_unavailable_reason`，并在 `serenity_aistocks_index.html` 中把股票名称改成 chart trigger。前端不新增后端接口，直接复用 `a_share_matches_quotes.py` 中的 `build_chart_url()` 和 `a_share_matches.html` 的 chart modal 交互模型。

**Tech Stack:** Python, Flask, Jinja2, HTML/CSS/JavaScript, pytest

---

## Summary

- 用户目标已锁定：
  - 点击 `Serenity AI Stocks` 表格中的股票名称
  - 在当前页弹出缠论图
  - 打开方式参考 `a_share_matches`
- 经过只读确认：
  - `a_share_matches` 后端会给股票补 `chart_url`，前端通过 `data-chart-trigger` 打开 modal。
  - `Serenity AI Stocks` 当前只有 `quote_target`、价格和涨跌幅，没有 `chart_url`、modal 和触发器。
  - `Serenity AI Stocks` 表格里股票名称当前仍是普通文本。

## Current State Analysis

### 已确认的参考实现

- `web/chanlun_chart/cl_app/__init__.py`
  - `/a_share_matches` 路由中会为每个 `project_stocks` 项补充：
    - `chart_url`
    - `chart_unavailable_reason`
    - `chart_frequency_label`
  - 具体逻辑是：
    - `infer_project_chart_target(...)`
    - `build_chart_url(...)`

- `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
  - 已有可复用函数：
    - `build_chart_url(market, code)`
    - `normalize_a_share_code(code)`
    - `normalize_hk_code(code)`
  - `build_chart_url()` 返回主图页可嵌入地址：

```python
return (
    f"/?market={normalized_market}&code={normalized_code}&embedded=1"
    "&lite_chart=1&default_interval=1D&load_last_chart=0"
)
```

- `web/chanlun_chart/cl_app/templates/a_share_matches.html`
  - 按钮触发器做法：
    - `data-chart-trigger`
    - `data-chart-title`
    - `data-chart-frequency`
    - `data-chart-url`
    - `data-chart-unavailable-reason`
  - 页面底部已有完整的 chart modal 结构和 JS 初始化逻辑，可缩小复用。

### Serenity 当前现状

- `web/chanlun_chart/cl_app/serenity_aistocks.py`
  - `_infer_row_quote_target()` 已能给行生成：
    - `market`
    - `code`
    - `normalized_code`
    - `symbol`
    - `status`
  - 这意味着缠论图目标所需的最核心信息已经存在。
  - 但当前没有任何 `chart_url` / `chart_unavailable_reason` 字段。

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
  - 表格渲染时，名称单元格仍走：
    - `<td>{{ row.cells.get(column, "") }}</td>`
  - 当前页面已有：
    - 价格轮询
    - 同步状态轮询
    - 涨跌幅排序
  - 当前页面没有：
    - chart modal
    - 名称点击触发器
    - 图表不可用时的弹窗兜底提示

- `test/test_serenity_aistocks.py`
  - 当前只覆盖：
    - workbook / sheet 加载
    - 价格列
    - 排序入口
    - 刷新脚本
    - 路由存在
  - 尚未覆盖：
    - 股票名称变成 chart trigger
    - chart modal DOM
    - chart URL 注入

## Assumptions & Decisions

- 点击入口决策：
  - 只把“股票名称”单元格做成可点击入口。
  - 不改整行点击，不改代码列点击。

- 打开方式决策：
  - 复用 `a_share_matches` 的当前页 modal 方式。
  - modal 内仍保留“新标签页打开”兜底入口。

- 数据决策：
  - `Serenity AI Stocks` 不引入新的行情推断接口。
  - 直接基于现有 `quote_target` 生成图目标：
    - `a` 市场：`build_chart_url("a", 6位代码)`
    - `hk` 市场：`build_chart_url("hk", KH.XXXXX)`
    - `us` 市场：`build_chart_url("us", SYMBOL)`
  - `quote_target.status != "ok"` 或缺少有效目标时：
    - `chart_url = ""`
    - `chart_unavailable_reason = "当前未获取到可用缠论图地址"` 或等价明确文案

- 范围控制：
  - 不在本次引入新的股票详情页。
  - 不改变当前价格排序、价格刷新、同步状态逻辑。
  - 只在现有页面上增加名称点击打开缠论图的能力。

## Proposed Changes

### 1. 后端：为 Serenity 行数据补充图表字段

**Files**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`

**What**
- 在构建行数据或水合行数据时，为每一行补充：
  - `chart_url`
  - `chart_unavailable_reason`
  - `chart_frequency_label`
  - 可选：`chart_title`

**Why**
- 前端 modal 触发器需要稳定的图表数据来源。
- 这样模板只负责渲染，不需要在 Jinja 中重复写市场映射逻辑。

**How**
- 从 `quote_target` 读取：
  - `market`
  - `normalized_code`
  - `symbol`
  - `status`
- 新增内部 helper，例如：
  - `_build_row_chart_view(row: dict[str, Any]) -> dict[str, str]`
- 逻辑建议：
  - 若 `quote_target.status != "ok"`：返回空 `chart_url` 和明确 unavailable reason
  - 若市场为 `a`：
    - 从 `normalized_code` 取 `SH.600183` 的右侧六位，传给 `build_chart_url("a", "600183")`
  - 若市场为 `hk`：
    - 直接使用 `normalized_code`，例如 `KH.09868`
  - 若市场为 `us`：
    - 直接使用标准化 symbol/code
- 在 `_build_sheet_rows()` 生成每个 `data_rows` 项时写入图字段，保证首屏即可渲染名称点击入口。

### 2. 模板：把股票名称改成缠论图触发器

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 将“名称”列改造成 clickable trigger。

**Why**
- 用户明确要求“点击股票，可以出现缠论图”。
- 名称是最自然的点击入口。

**How**
- 仅在列名为 `名称` 时特殊渲染：
  - 输出一个按钮或链接样式元素
  - 挂载：
    - `data-chart-trigger`
    - `data-chart-title`
    - `data-chart-frequency`
    - `data-chart-url`
    - `data-chart-unavailable-reason`
- 非 `名称` 列维持当前纯文本输出。
- 若名称为空但代码存在，可允许退回显示代码；但不扩展到其它列。

### 3. 模板：复用 a_share_matches 的 chart modal

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 在页面底部加入缠论图 modal DOM。
- 增加对应的初始化脚本、打开/关闭逻辑。

**Why**
- 用户指定参考 `a_share_matches`。
- 复用现成交互能降低设计与实现风险。

**How**
- 从 `a_share_matches.html` 中迁移最小必要子集：
  - modal 外层
  - backdrop
  - title/subtitle
  - iframe
  - loading 状态
  - unavailable message
  - “新标签页打开”按钮
- 新增 JS helper，例如：
  - `initChartModal()`
  - `openChartModal({...})`
  - `closeChartModal()`
- 初始化时扫描当前页面的 `[data-chart-trigger]`。
- 打开逻辑：
  - 若有 `data-chart-url`：显示 loading，设置 iframe `src`
  - 若无 `data-chart-url`：显示 unavailable message
- 关闭逻辑：
  - 支持 backdrop、关闭按钮、ESC

### 4. 排序与刷新兼容：避免点击名称与现有交互冲突

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 确保名称点击不会影响现有“点击价格排序”逻辑。
- 确保价格刷新后，名称触发器仍然可用。

**Why**
- 当前页面已经有价格排序和价格轮询，新增 modal 不应破坏原有行为。

**How**
- 名称 trigger 放在单元格内部，避免用整行点击。
- `refreshPrices()` 只更新价格单元格，不改名称列 DOM，因此 chart trigger 不需要在刷新后重新绑定。
- 只要 modal 初始化基于事件监听绑定在首屏静态 DOM 上即可。

### 5. 测试：补齐 chart trigger 与 modal 覆盖

**Files**
- Modify: `test/test_serenity_aistocks.py`

**What**
- 先写失败测试，锁定股票名称点击缠论图的 contract。

**Why**
- 当前测试尚未覆盖这条新交互链路。

**How**
- 新增模板测试：
  - 断言名称列存在 `data-chart-trigger`
  - 断言模板包含 `chart-modal`
  - 断言模板包含 `chart-modal-frame`
  - 断言模板包含 `chart-modal-open-new-tab`
  - 断言模板包含 `data-chart-url` 或 `data-chart-unavailable-reason`
- 新增后端/数据测试：
  - 对 `get_serenity_aistocks_sheet(...)` 返回的行，断言存在 `chart_url` 字段或合理的 unavailable reason
- 路由测试补充：
  - overview/detail 页面 HTML 中都能看到 chart modal 相关 DOM

## Implementation Steps

### Task 1: 先写失败测试

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] **Step 1: 新增模板级失败测试，要求名称列具有 chart trigger**

```python
def test_serenity_aistocks_index_template_includes_chart_trigger_on_stock_name(monkeypatch):
    ...
    assert "data-chart-trigger" in html
    assert "data-chart-url" in html
```

- [ ] **Step 2: 新增 modal 结构失败测试**

```python
assert 'id="chart-modal"' in html
assert 'id="chart-modal-frame"' in html
assert 'id="chart-modal-open-new-tab"' in html
```

- [ ] **Step 3: 新增行数据图字段失败测试**

```python
first_row = sheet["rows"][0]
assert "chart_url" in first_row
assert "chart_unavailable_reason" in first_row
```

- [ ] **Step 4: 运行定向测试确认红灯**

Run: `pytest test/test_serenity_aistocks.py -k "chart_trigger or sheet_detail or routes_exist" -v`

Expected: FAIL，因为当前 Serenity 行数据和模板里都还没有缠论图 trigger / modal。

### Task 2: 后端补充图字段

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`

- [ ] **Step 1: 引入 `build_chart_url`**

```python
from .a_share_matches_quotes import (
    build_chart_url,
    fetch_tick_snapshots,
    normalize_a_share_code,
    normalize_hk_code,
)
```

- [ ] **Step 2: 新增行级图字段 helper**

```python
def _build_row_chart_view(row: dict[str, Any]) -> dict[str, str]:
    ...
```

- [ ] **Step 3: 在 `_build_sheet_rows()` 中把图字段写入每一行**

```python
row_chart_view = _build_row_chart_view(...)
data_rows.append({
    ...
    "chart_url": row_chart_view["chart_url"],
    "chart_unavailable_reason": row_chart_view["chart_unavailable_reason"],
})
```

- [ ] **Step 4: 运行与数据相关的定向测试**

Run: `pytest test/test_serenity_aistocks.py -k "sheet_detail" -v`

Expected: PASS 或仅剩模板相关失败

### Task 3: 模板接入名称点击和 modal

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 名称列改成 chart trigger**

```html
<button
    type="button"
    data-chart-trigger
    data-chart-title="{{ row.cells.get('名称', '') }} 缠论图"
    data-chart-url="{{ row.chart_url }}"
    data-chart-unavailable-reason="{{ row.chart_unavailable_reason }}"
>
    {{ row.cells.get("名称", "") }}
</button>
```

- [ ] **Step 2: 迁移最小可用 chart modal DOM**

```html
<div class="chart-modal" id="chart-modal" aria-hidden="true">
    ...
</div>
```

- [ ] **Step 3: 迁移最小可用 JS 初始化与打开关闭逻辑**

```javascript
document.querySelectorAll("[data-chart-trigger]").forEach((trigger) => {
    trigger.addEventListener("click", () => { ... });
});
```

- [ ] **Step 4: 运行定向模板测试**

Run: `pytest test/test_serenity_aistocks.py -k "chart_trigger or routes_exist or index_template" -v`

Expected: PASS

### Task 4: 完整回归与诊断

**Files:**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] **Step 1: 跑完整 Serenity AI Stocks 测试**

Run: `pytest test/test_serenity_aistocks.py -v`

Expected: PASS

- [ ] **Step 2: 检查最近编辑文件诊断**

Check diagnostics for:
- `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`
- `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

Expected: 无新增 diagnostics

## Verification

- 自动化验证：

```bash
pytest test/test_serenity_aistocks.py -v
```

- 人工验证：
  - 打开任一 `Serenity AI Stocks` sheet 页面。
  - 点击股票名称，当前页弹出缠论图 modal。
  - modal 内 iframe 正常加载图形时，可直接查看。
  - 如果当前股票不支持图形，modal 显示不可用提示，并保留“新标签页打开”入口。
  - 点击 backdrop、关闭按钮或按 `ESC` 可以关闭 modal。
  - 价格排序、价格刷新、同步状态刷新仍正常工作。
