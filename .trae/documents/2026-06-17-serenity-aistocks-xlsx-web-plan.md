# Serenity AI Stocks Excel 网页化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `serenity-aleabitoreddit-main/aistocks.xlsx` 做成现有 Flask 应用中的网页，提供“首页总览 + 分 sheet 明细”浏览，并为每只股票新增一个可定时自动刷新的价格列。

**Architecture:** 新增一个独立的 Serenity AI Stocks 数据模块，负责读取 `aistocks.xlsx`、标准化多 sheet 数据并生成总览/明细视图模型；在 `cl_app.__init__` 中新增页面路由和价格接口；前端使用单独模板渲染总览页与明细页，并通过轮询 JSON 接口定时刷新价格列。价格抓取优先复用现有 `a_share_matches_quotes.py` / `get_exchange(Market(...))` 链路，无法识别的标的保留原始行并显示不可用状态。

**Tech Stack:** Flask, Jinja2, Pandas/openpyxl, 现有 `chanlun.exchange` 行情接口, 现有 `a_share_matches_quotes.py` 价格快照工具

---

## Summary

- 目标文件位于 `serenity-aleabitoreddit-main/aistocks.xlsx`。
- 当前应用已经有成熟的 Flask 模板页、JSON 接口和行情抓取能力：
  - 页面模式：`/market_summary`、`/asset_news`、`/a_share_matches`
  - 价格抓取：`a_share_matches_quotes.py` 的 `fetch_tick_snapshots()` 和 `infer_project_quote_target()`
- 用户已明确的产品选择：
  - 展示方式：`首页总览 + 分 sheet`
  - 价格方式：`定时自动刷新`
  - 列展示：`保留原始列 + 加价格列`
- 关键实现难点不在网页框架，而在：
  - 多 sheet Excel 的统一解析
  - Excel 行内股票标识如何映射到现有行情接口
  - 页面定时刷新时如何只更新价格列，不重复渲染整表

## Current State Analysis

### 已确认的仓库事实

- Excel 文件存在：
  - `serenity-aleabitoreddit-main/aistocks.xlsx`
- 工作簿不是单 sheet：
  - 从文件结构可确认至少有 `sheet1` 到 `sheet10`
- 现有 Web 入口在：
  - `web/chanlun_chart/cl_app/__init__.py`
- 现有页面模板目录在：
  - `web/chanlun_chart/cl_app/templates`
- 现有可复用价格能力：
  - `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
    - `infer_project_quote_target()`
    - `fetch_tick_snapshots()`
    - `build_tick_snapshot()`
- 现有页面与接口模式参考：
  - 页面路由：`/a_share_matches`
  - POST JSON 接口：`/a_share_matches/project_ticks`

### 当前缺口

- 还没有任何读取 `aistocks.xlsx` 的 Web 模块
- 还没有针对 Serenity Excel 的页面路由与模板
- 还没有把 Excel 行数据映射为“可刷新价格列”的标准结构
- 还没有这部分功能的测试文件

## Proposed Changes

### 1. 新增独立数据模块：读取并标准化 `aistocks.xlsx`

**Files**

- Create: `web/chanlun_chart/cl_app/serenity_aistocks.py`

**What**

- 新增一个独立模块，负责：
  - 定位 `aistocks.xlsx`
  - 读取全部 sheet
  - 保留每个 sheet 的原始列顺序
  - 构建“总览页模型”和“单 sheet 明细模型”
  - 为每一行推断价格刷新所需的最小 quote target

**How**

- 使用 `pandas.ExcelFile` + `pd.read_excel()` 读取全部 sheet
- 每个 sheet 输出统一结构：

```python
{
    "sheet_name": "原始 Sheet 名",
    "sheet_slug": "slugified-name",
    "columns": ["原始列1", "原始列2", "...", "价格"],
    "rows": [
        {
            "row_id": "sheet_slug-1",
            "cells": {"原始列1": "...", "原始列2": "..."},
            "quote_target": {
                "market": "us",
                "code": "NVDA",
                "symbol": "NVDA",
                "status": "ok",
            },
            "price_text": "--",
            "price_status": "pending",
        }
    ],
    "row_count": 24,
}
```

- 总览页输出结构：

```python
{
    "workbook_name": "aistocks.xlsx",
    "sheet_count": 10,
    "total_row_count": 218,
    "sheets": [
        {
            "sheet_name": "...",
            "sheet_slug": "...",
            "row_count": 24,
            "has_price_candidates": 20,
            "sample_symbols": ["NVDA", "AVGO", "LITE"],
        }
    ],
}
```

**关键规则**

- 原始列顺序必须保留，不重排、不裁剪
- 新增列只允许在末尾加一个 `价格`
- 不要求把所有 sheet 合并成统一 schema

### 2. 定义价格映射规则，兼容未知标的

**Files**

- Create: `web/chanlun_chart/cl_app/serenity_aistocks.py`
- Reuse: `web/chanlun_chart/cl_app/a_share_matches_quotes.py`

**What**

- 为 Excel 每行推断价格抓取目标
- 对无法识别的行，不丢弃数据，只显示“价格不可用”

**How**

- 在 `serenity_aistocks.py` 内新增：
  - `_infer_row_quote_target(row: dict[str, Any], columns: list[str])`
  - `_normalize_excel_symbol(value: str)`
  - `_infer_market_from_symbol_or_text(...)`
- 推断优先级：
  1. 明确的代码/股票列
  2. 明确的市场/交易所列
  3. 代码样式推断
     - 纯美股 ticker：`us`
     - `SH./SZ./BJ.` 或 6/3/8 位 A 股代码：`a`
     - 4-5 位港股代码或 HK/HKEX 文字：`hk`
  4. 若仍无法识别：
     - `price_status = "unsupported"`
     - `price_text = "价格不可用"`

**为什么这样做**

- 用户要求保留原始 Excel 内容，不能因为行情不可识别而丢行
- 现有行情接口已支持 `a/hk/us`，优先复用即可

### 3. 新增页面路由与价格接口

**Files**

- Modify: `web/chanlun_chart/cl_app/__init__.py`

**What**

- 增加 Serenity AI Stocks 总览页
- 增加单个 sheet 明细页
- 增加仅返回价格数据的 JSON 接口

**路由设计**

- 页面：
  - `GET /serenity/aistocks`
  - `GET /serenity/aistocks/<sheet_slug>`
- 接口：
  - `POST /serenity/aistocks/prices`

**接口输入**

```json
{
  "items": [
    {
      "row_id": "sheet1-1",
      "market": "us",
      "code": "NVDA",
      "symbol": "NVDA"
    }
  ]
}
```

**接口输出**

```json
{
  "quotes": [
    {
      "row_id": "sheet1-1",
      "market": "us",
      "code": "NVDA",
      "price_text": "142.31",
      "rate_text": "+2.18%",
      "status": "ok"
    }
  ],
  "unsupported": [
    {
      "row_id": "sheet1-8",
      "status": "unsupported"
    }
  ]
}
```

**实现要点**

- 路由风格跟现有 `a_share_matches` 保持一致
- `prices` 接口只处理价格，不重复返回整行数据
- 价格接口内按 `market` 分组调用 `get_exchange(Market(...))` + `fetch_tick_snapshots()`

### 4. 新增两个模板：总览页和分表明细页

**Files**

- Create: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- Create: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

**What**

- 总览页：展示 workbook 摘要和各 sheet 导航卡片
- 明细页：展示单个 sheet 的原始表格，并在最后增加 `价格` 列

**总览页内容**

- workbook 名称
- sheet 数量
- 总行数
- 每个 sheet 的卡片：
  - sheet 名
  - 行数
  - 可尝试抓价的行数
  - 样本 ticker
  - “查看明细”按钮

**明细页内容**

- 当前 sheet 标题
- 返回总览入口
- 原始列完整表格
- 末尾新增：
  - `价格`
  - 可选附加小字：`涨跌幅`
- 首屏只加载 HTML 表格，价格通过 JS 异步刷新

**交互要求**

- 页面初次进入即抓一次价格
- 使用 `setInterval` 定时刷新价格
- 只更新价格单元格，不整页刷新
- 对不可用行显示固定文案：
  - `价格不可用`

### 5. 前端自动刷新协议

**Files**

- Create or inline in: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`

**What**

- 为明细页增加自动刷新脚本

**How**

- 在每个价格单元格写入：
  - `data-row-id`
  - `data-market`
  - `data-code`
  - `data-symbol`
- 页面 JS 流程：
  1. 扫描表格可报价行
  2. 首次调用 `/serenity/aistocks/prices`
  3. 按固定周期轮询刷新
  4. 把返回的 `price_text` 写回对应单元格
  5. 对失败项写入 `价格不可用`

**默认刷新周期**

- 先按 `60s` 设计
- 原因：满足“定时自动刷新”，且避免过于频繁打接口

### 6. 测试方案

**Files**

- Create: `test/test_serenity_aistocks.py`

**What**

- 覆盖 Excel 解析、sheet 总览、价格映射和模板关键渲染

**测试范围**

- `test_load_serenity_aistocks_workbook_returns_sheet_summaries`
  - 断言能读出多个 sheet
- `test_sheet_detail_preserves_original_columns_and_appends_price`
  - 断言列顺序保留，最后一列是 `价格`
- `test_infer_row_quote_target_handles_us_a_hk_and_unknown`
  - 断言美股/A 股/港股/未知标的的映射结果
- `test_serenity_aistocks_index_template_renders_sheet_cards`
  - 断言总览页出现 sheet 卡片和明细入口
- `test_serenity_aistocks_sheet_template_renders_price_cells_and_refresh_hooks`
  - 断言明细页出现 `价格` 列和刷新 data attributes

**说明**

- 优先做模块级和模板级测试
- 若现有 test client 方便复用，再补路由接口测试：
  - `GET /serenity/aistocks`
  - `GET /serenity/aistocks/<sheet_slug>`
  - `POST /serenity/aistocks/prices`

## Assumptions & Decisions

- 决策：功能接入现有 Flask 应用，而不是生成仓库外的独立静态页面
- 决策：按用户要求采用 `首页总览 + 分 sheet 明细`
- 决策：保留 Excel 原始列顺序，仅在最后增加 `价格`
- 决策：价格列采用前端轮询接口的方式自动刷新
- 决策：价格接口优先支持 `us/a/hk` 三类市场
- 决策：未知或无法识别标的保留原始行，显示 `价格不可用`
- 假设：仓库环境已具备读取 `.xlsx` 的 pandas/openpyxl 依赖
- 假设：Excel 至少能从某一列中识别出 ticker / code / symbol / 股票名称中的一种价格定位线索

## Verification Steps

- 打开总览页：
  - `GET /serenity/aistocks`
  - 可看到 workbook 摘要与各 sheet 卡片
- 打开任一明细页：
  - `GET /serenity/aistocks/<sheet_slug>`
  - 表格保留原始列
  - 最后一列为 `价格`
- 打开浏览器等待一个刷新周期：
  - 可识别标的价格自动刷新
  - 不可识别标的显示 `价格不可用`
- 运行测试：
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/test_serenity_aistocks.py -q`

## Implementation Tasks

### Task 1: 建立 Excel 解析模块

**Files:**
- Create: `web/chanlun_chart/cl_app/serenity_aistocks.py`
- Test: `test/test_serenity_aistocks.py`

- [ ] 写失败测试，锁定多 sheet 总览结构和原始列保留行为
- [ ] 实现 workbook 读取与 `sheet_slug`/`columns`/`rows` 输出
- [ ] 验证最后一列统一追加 `价格`

### Task 2: 建立价格目标推断与价格抓取

**Files:**
- Modify: `web/chanlun_chart/cl_app/serenity_aistocks.py`
- Reuse: `web/chanlun_chart/cl_app/a_share_matches_quotes.py`
- Test: `test/test_serenity_aistocks.py`

- [ ] 写失败测试，锁定 `us/a/hk/unsupported` 四类映射
- [ ] 实现 `_infer_row_quote_target()` 和按市场分组抓价逻辑
- [ ] 验证接口输出包含 `row_id + price_text + status`

### Task 3: 新增页面与价格接口路由

**Files:**
- Modify: `web/chanlun_chart/cl_app/__init__.py`
- Test: `test/test_serenity_aistocks.py`

- [ ] 写失败测试，锁定总览页、明细页、价格接口存在
- [ ] 实现 `GET /serenity/aistocks`
- [ ] 实现 `GET /serenity/aistocks/<sheet_slug>`
- [ ] 实现 `POST /serenity/aistocks/prices`

### Task 4: 新增总览页与明细页模板

**Files:**
- Create: `web/chanlun_chart/cl_app/templates/serenity_aistocks_index.html`
- Create: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`
- Test: `test/test_serenity_aistocks.py`

- [ ] 写失败测试，锁定 sheet 卡片、原始列和 `价格` 列渲染
- [ ] 实现总览页卡片和导航
- [ ] 实现明细页表格与价格占位单元格

### Task 5: 接入自动刷新与回归

**Files:**
- Modify: `web/chanlun_chart/cl_app/templates/serenity_aistocks_sheet.html`
- Test: `test/test_serenity_aistocks.py`

- [ ] 写失败测试，锁定价格列刷新 hooks
- [ ] 实现首屏抓价 + `60s` 轮询刷新
- [ ] 运行 `test/test_serenity_aistocks.py`
- [ ] 手工检查一张明细表的价格列是否按预期更新
