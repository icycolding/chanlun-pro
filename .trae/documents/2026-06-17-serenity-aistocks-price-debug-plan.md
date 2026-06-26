# Serenity AI Stocks 价格不显示排查与修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `Serenity AI Stocks` 明细页点开后价格列一直不显示的问题，确保至少 A 股 `sh/sz/bj` 前缀代码能被正确抓价并在页面自动刷新出来。

**Architecture:** 这次优先按最小修复处理，不改页面结构，聚焦价格链路的后端归一化和回归测试。核心做法是修正共享代码归一化函数对 `sh600183` / `sz002xxx` / `bj830xxx` 这类格式的处理，并补上 `serenity_aistocks` 的接口级测试，证明价格接口不仅返回 `200`，而且真的能返回可渲染的 `quotes`。

**Tech Stack:** Flask, Python, pytest, 现有 `chanlun.exchange` 行情抽象, `a_share_matches_quotes.py`, `serenity_aistocks.py`

---

## Summary

- 当前症状是：打开 `Serenity AI Stocks` 明细页后，价格列没有出现实际价格。
- 通过静态检查已定位高概率根因：
  - `serenity_aistocks.py` 会把 Excel 行内 `代码` 字段传给 `fetch_serenity_aistocks_prices()`
  - A 股样例代码来自 Excel，格式是 `sh600183`
  - 共享函数 `normalize_a_share_code()` 只对纯 6 位数字做 `SH./SZ./BJ.` 标准化
  - 对 `sh600183` 这种值，它当前会错误返回 `SH600183`，而不是 `SH.600183`
- 这会导致价格接口很可能向行情层请求错误代码，最终拿不到 snapshot，前端就会一直显示 `--`
- 当前测试缺口也很明显：
  - `test_serenity_aistocks.py` 只断言价格接口返回 `200`
  - 没有断言接口返回了真实 `quotes`
  - 没有断言 `sh600183 -> SH.600183` 这条关键归一化路径

## Current State Analysis

### 已确认的代码路径

- `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`
  - 页面打开会立即执行 `refreshPrices()`
  - 会把表格里的 `data-market` / `data-code` / `data-row-id` 发给：
    - `POST /serenity/aistocks/prices`
- `web/chanlun_chart/cl_app/serenity_aistocks.py`
  - `fetch_serenity_aistocks_prices()` 负责：
    - 按 market 分组
    - A 股走 `normalize_a_share_code(code)`
    - 港股走 `normalize_hk_code(code)`
    - 然后调用 `fetch_tick_snapshots()`
- `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
  - `normalize_a_share_code()` 当前逻辑：
    - 支持 `600183 -> SH.600183`
    - 不支持 `sh600183 -> SH.600183`
    - 对 `sh600183` 实际会返回 `SH600183`

### 当前最可能的失败点

- Excel 的 A 股代码使用了带前缀的小写格式：
  - `sh600183`
  - `sz...`
- 进入价格接口后被错误归一化
- 行情层因此返回空结果
- 前端收到的 JSON 中 `quotes` 为空，或条目进入 `unsupported`
- 页面最终保持 `--`

### 现有测试缺口

- `test/test_serenity_aistocks.py`
  - 只验证页面和接口存在
  - 没有验证价格 JSON 内容
- `test/test_a_share_matches_quotes.py`
  - 只验证纯数字 A 股代码标准化
  - 没有覆盖带 `sh/sz/bj` 前缀但无点的输入

## Proposed Changes

### 1. 修正 A 股代码标准化逻辑

**Files**

- Modify: `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
- Test: `test/test_a_share_matches_quotes.py`

**What**

- 让 `normalize_a_share_code()` 额外支持以下输入：
  - `sh600183 -> SH.600183`
  - `sz002281 -> SZ.002281`
  - `bj830000 -> BJ.830000`

**How**

- 在原函数前半段增加前缀格式识别：
  - 如果匹配 `^(SH|SZ|BJ)\d{6}$`
  - 则标准化为 `SH.600183` 这种带点格式
- 保持以下兼容性不变：
  - 已经带点的 `SH.600183` 直接返回
  - 纯 6 位数字继续按原逻辑推断市场

**Why**

- 这是当前最可能导致 A 股价格全拿不到的根因
- 修在共享归一化层，比只在 `serenity_aistocks.py` 内做特殊处理更一致

### 2. 补 `serenity_aistocks` 的接口级回归测试

**Files**

- Modify: `test/test_serenity_aistocks.py`

**What**

- 新增或调整测试，证明 `/serenity/aistocks/prices` 真能返回 `quotes`

**How**

- 在测试中 monkeypatch：
  - `cl_app.serenity_aistocks.get_exchange`
  - 或直接 patch `fetch_tick_snapshots`
- 使用示例请求：

```json
{
  "items": [
    {"row_id": "a-1", "market": "a", "code": "sh600183", "symbol": "sh600183"},
    {"row_id": "us-1", "market": "us", "code": "NVDA", "symbol": "NVDA"}
  ]
}
```

- 断言响应：
  - `quotes` 非空
  - A 股返回的 `row_id == "a-1"`
  - `price_text` 不是 `--`
  - `status == "ok"`

**Why**

- 这能直接覆盖用户当前看到的问题，而不是只验证接口“活着”

### 3. 补共享归一化的单元测试

**Files**

- Modify: `test/test_a_share_matches_quotes.py`

**What**

- 新增归一化断言：

```python
assert normalize_a_share_code("sh600183") == "SH.600183"
assert normalize_a_share_code("sz002281") == "SZ.002281"
assert normalize_a_share_code("bj830000") == "BJ.830000"
```

**Why**

- 防止以后再出现“纯数字能用、带前缀不能用”的回归

### 4. 视结果决定是否补前端兜底文案

**Files**

- Optional Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

**What**

- 如果后端修复后仍存在“部分行长期没有价格”的情况，再补一个更明确的前端状态：
  - 首次加载时显示 `价格加载中`
  - 接口明确 unsupported 时显示 `价格不可用`

**Why**

- 这不是当前首要根因
- 先修后端代码归一化和接口正确性，再看是否需要做体验层增强

## Assumptions & Decisions

- 决策：本次先按“价格获取不对”的方向做最小修复，不改页面结构和轮询周期
- 决策：优先修共享函数 `normalize_a_share_code()`，而不是只在 `serenity_aistocks.py` 里打补丁
- 决策：测试重点从“接口存在”升级为“接口真正返回价格”
- 假设：当前用户看到的“没价格”主要出现在 A 股行；即使美股/港股部分可用，这个修复仍然必要
- 假设：`fetch_tick_snapshots()` 对 `SH.600183` / `SZ.002281` / `BJ.830000` 是可工作的

## Verification Steps

- 单元测试：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_a_share_matches_quotes.py -q`
- 功能测试：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_serenity_aistocks.py -q`
- 页面验证：
  - 打开任一包含 A 股代码的 sheet 明细页
  - 首次加载后应出现价格，不应长期停留在 `--`
  - 若行情层无该标的，则应显示 `价格不可用`

## Implementation Tasks

### Task 1: 锁定失败测试

**Files:**
- Modify: `test/test_a_share_matches_quotes.py`
- Modify: `test/test_serenity_aistocks.py`

- [ ] **Step 1: 写归一化失败测试**

```python
def test_normalize_a_share_code_supports_prefixed_exchange_codes():
    assert normalize_a_share_code("sh600183") == "SH.600183"
    assert normalize_a_share_code("sz002281") == "SZ.002281"
    assert normalize_a_share_code("bj830000") == "BJ.830000"
```

- [ ] **Step 2: 写价格接口失败测试**

```python
def test_serenity_aistocks_prices_returns_quotes_for_prefixed_a_share_codes(app_client, monkeypatch):
    def fake_fetch_tick_snapshots(ex, codes):
        assert codes == ["SH.600183"]
        return {
            "SH.600183": {"price": 23.45, "rate": 1.23}
        }
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  test/test_a_share_matches_quotes.py \
  test/test_serenity_aistocks.py -q
```

Expected:
- 归一化断言失败，显示当前返回 `SH600183`
- 或价格接口测试拿不到 `quotes`

### Task 2: 最小实现归一化修复

**Files:**
- Modify: `web/chanlun_chart/cl_app/a_share_matches_quotes.py`

- [ ] **Step 1: 修改 `normalize_a_share_code()`**

```python
if re.fullmatch(r"(SH|SZ|BJ)\d{6}", normalized):
    return f"{normalized[:2]}.{normalized[2:]}"
```

- [ ] **Step 2: 保留现有纯数字与已带点格式逻辑**

```python
if "." in normalized:
    return normalized
if len(normalized) != 6 or not normalized.isdigit():
    return normalized
```

- [ ] **Step 3: 重新运行相关测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  test/test_a_share_matches_quotes.py \
  test/test_serenity_aistocks.py -q
```

Expected:
- 新增归一化测试通过
- 价格接口测试通过

### Task 3: 补 `serenity_aistocks` 接口断言

**Files:**
- Modify: `test/test_serenity_aistocks.py`

- [ ] **Step 1: 将路由测试从 `status_code == 200` 升级为“返回有效 quotes”**

```python
payload = prices.get_json()
assert payload["quotes"]
assert payload["quotes"][0]["row_id"] == "a-1"
assert payload["quotes"][0]["price_text"] != "--"
```

- [ ] **Step 2: 增加 unsupported 分支断言**

```python
assert payload["unsupported"] == []
```

- [ ] **Step 3: 重新运行单文件测试**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_serenity_aistocks.py -q
```

Expected:
- PASS

### Task 4: 页面回归确认

**Files:**
- Optional Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

- [ ] **Step 1: 若后端已返回 quotes，则先不动模板**
- [ ] **Step 2: 手工验证价格从 `--` 更新为具体数值**
- [ ] **Step 3: 若仍不清晰，再补 `价格加载中` 文案**

```html
<span class="price-main">价格加载中</span>
```

- [ ] **Step 4: 仅在必要时追加模板小修，不扩大范围**
