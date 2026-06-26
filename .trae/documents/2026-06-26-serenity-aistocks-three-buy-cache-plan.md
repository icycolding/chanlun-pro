# Serenity AI Stocks 三买扫描结果持久化计划

## Summary

- 目标：`Serenity AI Stocks` 页面点击“三买扫描”后，将每只股票最近一次扫描到的三买结果保存到当前项目数据库；后续再次打开页面时，首屏优先显示上一次已保存的扫描结果，而不是回到 `未扫描`。
- 范围：只覆盖当前已实现的 `最近 3买` 功能，不新增自动定时扫描，不改变现有价格缓存与图表弹窗逻辑。
- 方案：复用现有 `Serenity AI Stocks latest price` 的数据库模式，新增一张“最近三买扫描结果”表与对应 query/replace 方法；在页面首屏构建时进行 DB 水合，在手动扫描成功后写库并返回保存结果。

## Current State Analysis

### 当前页面行为

- 文件：`web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- 当前 `最近 3买` 列只在前端点击按钮后通过 `/serenity/aistocks/recent-three-buy-times` 回填。
- 页面初始化时默认显示：
  - `recent_three_buy_time_text = "--"`
  - `recent_three_buy_label = "未扫描"`
- 刷新页面后，扫描结果会丢失，因为没有任何后端持久化读取逻辑。

### 当前后端行为

- 文件：`web/chanlun_chart/cl_app/serenity_aistocks.py`
- `fetch_serenity_aistocks_recent_three_buy_times(...)` 现在只负责：
  - 扫描日线 `d`
  - 优先提取 `BI:3B / BI:L3B`
  - 失败时返回 `misses`
- 但它不会把结果写入数据库。
- `_build_sheet_rows()` 默认仍写死：
  - `recent_three_buy_time_text = "--"`
  - `recent_three_buy_label = "未扫描"`
- `get_serenity_aistocks_sheet(...)` 目前只会做价格 DB 水合，不会对三买结果做 DB 水合。

### 当前数据库能力

- 文件：`src/chanlun/db.py`
- 已有最近价格缓存表：`TableBySerenityAIStocksLatestPrice`
- 已有配套方法：
  - `serenity_aistocks_latest_prices_replace(...)`
  - `serenity_aistocks_latest_prices_query(...)`
- 这已经提供了本次最适合复用的模式：
  - 按 `market + code` 唯一
  - 保存最新结果
  - 下次查询时直接按 symbol/market/code 回填

## Assumptions & Decisions

- 保存模型：使用“最新覆盖”模式，不保留三买扫描历史版本。
- 唯一键：沿用 `market + code`，与价格缓存保持一致。
- 保存时机：仅在用户点击“三买扫描”并得到扫描结果后保存。
- 首屏行为：
  - 页面加载时优先读取数据库中的上次扫描结果。
  - 若没有历史记录，仍显示 `未扫描`。
- 状态展示：
  - `ok`：显示日期 + `最近 3买`
  - `not_found`：显示 `--` + `未找到 3买`
  - `error`：显示 `--` + `扫描异常`
  - `unsupported`：显示 `--` + `暂不支持`
- 更新策略：
  - 用户再次点击扫描时，覆盖数据库中的旧结果。
  - 不增加后台 scheduler；仍由用户手动触发。

## Proposed Changes

### 1. 数据库：新增 Serenity 三买扫描结果表

**Files**
- Modify: `src/chanlun/db.py`

**What**
- 新增一张与 latest price 平行的表，例如：
  - `TableBySerenityAIStocksRecentThreeBuy`
- 建议字段：
  - `market`
  - `code`
  - `symbol`
  - `recent_three_buy_time`
  - `recent_three_buy_time_text`
  - `label`
  - `status`
  - `source`
  - `scanned_at`
  - `created_at`
  - `updated_at`
- 唯一键：
  - `UniqueConstraint("market", "code", ...)`

**Why**
- 需要把用户手动扫描的结果持久化，供页面下次加载时直接读取。

**How**
- 复用 `_normalize_serenity_aistocks_market_code(...)`
- 新增两个 DB 方法：
  - `serenity_aistocks_recent_three_buy_replace(rows: List[dict]) -> bool`
  - `serenity_aistocks_recent_three_buy_query(items: List[dict]) -> List[dict]`

### 2. 后端：新增三买结果 DB 水合能力

**Files**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`

**What**
- 在页面构建阶段，把数据库里已有的三买结果写回行数据。

**Why**
- 用户要求“下次加载先加载上次扫描过的”。

**How**
- 新增 helper：
  - `_build_db_recent_three_buy_map(items)`
  - `_hydrate_sheet_rows_with_recent_three_buy(rows)`
- 在 `get_serenity_aistocks_sheet(...)` 中：
  - 先做价格水合
  - 再做三买结果水合
- 默认值逻辑保持不变，只在 DB 命中时覆盖：
  - `recent_three_buy_time_text`
  - `recent_three_buy_label`
  - 可选增加：
    - `recent_three_buy_status`
    - `recent_three_buy_updated_at_text`

### 3. 后端：扫描接口在返回前写库

**Files**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`

**What**
- `fetch_serenity_aistocks_recent_three_buy_times(...)` 不再只是返回 hits/misses，还要把本次扫描结果统一落库。

**Why**
- 这样一次扫描就能同时完成：
  - 当前页面回填
  - 后续页面首屏可读

**How**
- 在函数内部构建 `rows_to_replace`
- 对 `hits` / `misses` 都写入数据库，避免旧结果残留：
  - `ok` 写入日期与 label
  - `not_found` / `error` / `unsupported` 写入状态与 `--`
- source 建议：
  - `serenity_aistocks_manual_scan`
- scanned_at / updated_at：
  - 使用本次扫描时间
- 返回 payload 结构保持兼容现有前端，不增加 breaking change

### 4. 前端：页面加载优先显示上次扫描结果

**Files**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

**What**
- 模板无需新增主动请求“读取三买结果”的 API。
- 直接消费后端首屏已水合好的 `row.recent_three_buy_*` 字段。

**Why**
- 当前页面渲染已是 SSR 模式，首屏直接带上 DB 结果最简洁。

**How**
- 保持现有 `three-buy-cell` 结构。
- 若后端首屏已注入：
  - `recent_three_buy_time_text`
  - `recent_three_buy_label`
  - 则页面首屏直接展示上次扫描过的值。
- 按钮点击后的现有回填逻辑保留，仅在扫描成功后更新 DOM。

### 5. 测试：补充持久化与首屏回填覆盖

**Files**
- Modify: `test/test_serenity_aistocks.py`

**What**
- 新增测试覆盖：
  - 三买结果保存到 DB
  - 页面加载优先展示 DB 中上次扫描值
  - 新扫描覆盖旧结果

**How**
- 测试 1：DB query 命中时，`get_serenity_aistocks_sheet(...)` 返回的第一行带有历史 `recent_three_buy_time_text`
- 测试 2：扫描函数执行后调用 replace 方法，断言写入 payload 中包含：
  - `market`
  - `code`
  - `status`
  - `recent_three_buy_time_text`
- 测试 3：模板首屏包含历史三买时间与 label，而不是只显示 `未扫描`
- 测试 4：接口返回后前端 contract 仍兼容，`/serenity/aistocks/recent-three-buy-times` 不变

## Implementation Steps

### Task 1: 先写失败测试

**Files**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] 新增“首屏读取历史三买结果”的失败测试
- [ ] 新增“扫描后写库”的失败测试
- [ ] 新增“新扫描覆盖旧结果”的失败测试
- [ ] 运行定向测试，确认红灯

建议命令：

```bash
pytest test/test_serenity_aistocks.py -k "recent_three_buy and (hydrate or replace or routes_exist)" -v
```

### Task 2: 数据库新增三买缓存表与读写方法

**Files**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/src/chanlun/db.py`

- [ ] 添加 `TableBySerenityAIStocksRecentThreeBuy`
- [ ] 添加 `serenity_aistocks_recent_three_buy_replace(...)`
- [ ] 添加 `serenity_aistocks_recent_three_buy_query(...)`
- [ ] 复用现有市场代码规范化逻辑，保持与 price cache 一致

### Task 3: 页面首屏水合三买结果

**Files**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`

- [ ] 添加 `_build_db_recent_three_buy_map(...)`
- [ ] 添加 `_hydrate_sheet_rows_with_recent_three_buy(...)`
- [ ] 在 `get_serenity_aistocks_sheet(...)` 中串联价格水合 + 三买水合
- [ ] 默认 `未扫描` 值仅作为 DB miss 的回退

### Task 4: 扫描接口完成后写库

**Files**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`

- [ ] 在 `fetch_serenity_aistocks_recent_three_buy_times(...)` 中构建写库 rows
- [ ] 对 `ok / not_found / error / unsupported` 全部做 replace，避免旧值残留
- [ ] 保持接口 JSON 结构兼容现有前端

### Task 5: 模板与前端验证

**Files**
- Modify: `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`

- [ ] 确认首屏直接消费 SSR 注入的历史三买值
- [ ] 不新增额外首屏读取 API
- [ ] 保持现有点击扫描后的 DOM 更新逻辑

### Task 6: 回归验证

**Files**
- Modify:
  - `/Users/jiming/Documents/trae/chanlun-pro/src/chanlun/db.py`
  - `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/serenity_aistocks.py`
  - `/Users/jiming/Documents/trae/chanlun-pro/web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
  - `/Users/jiming/Documents/trae/chanlun-pro/test/test_serenity_aistocks.py`

- [ ] 跑完整 Serenity 测试
- [ ] 检查最近编辑文件 diagnostics
- [ ] 手动验证：扫描一次 -> 刷新页面 -> 首屏仍能看到上次扫描结果

建议命令：

```bash
pytest test/test_serenity_aistocks.py -v
```

## Verification

- 自动化验证

```bash
pytest test/test_serenity_aistocks.py -v
```

- 人工验证
  - 打开任一 `Serenity AI Stocks` Sheet。
  - 点击 `查找 3买时间`，确认表格出现扫描结果。
  - 刷新当前页面。
  - 首屏应直接显示上次扫描过的三买结果，而不是回到 `未扫描`。
  - 再次点击扫描后，新的扫描结果应覆盖旧值。
